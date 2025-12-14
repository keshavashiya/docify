"""
Re-Ranking Service
Multi-factor ranking with conflict detection and confidence scoring
"""
import logging
from typing import List, Dict, Optional, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.models import Resource, Chunk
from app.schemas.search import SearchResult
from app.services.llm import call_llm

logger = logging.getLogger(__name__)


class ReRankingService:
    """Service for re-ranking search results with multiple factors"""

    def __init__(self, db: Session):
        self.db = db

    def rerank(
        self,
        results: List[SearchResult],
        query: str,
        workspace_id: UUID,
        detect_conflicts: bool = True
    ) -> List[SearchResult]:
        """
        Re-rank search results using multiple factors.

        Factors:
        1. Base relevance score (40%)
        2. Citation frequency (15%) - How often is source cited
        3. Recency (15%) - When was document added
        4. Specificity (15%) - How directly does it address query
        5. Source quality (15%) - Document type, metadata

        Args:
            results: Initial search results
            query: User query
            workspace_id: Workspace context
            detect_conflicts: Whether to detect conflicting statements

        Returns:
            Re-ranked results with updated scores and metadata
        """

        if not results:
            logger.warning("No results to re-rank")
            return []

        logger.info(f"Re-ranking {len(results)} results")

        # Calculate all scoring factors
        for result in results:
            result.rerank_scores = {}

            # Factor 1: Base relevance (40%)
            base_score = result.score  # Already normalized 0-1
            result.rerank_scores['base'] = base_score * 0.40

            # Factor 2: Citation frequency (15%)
            citation_score = self._score_citation_frequency(result, results)
            result.rerank_scores['citation'] = citation_score * 0.15

            # Factor 3: Recency (15%)
            recency_score = self._score_recency(result)
            result.rerank_scores['recency'] = recency_score * 0.15

            # Factor 4: Specificity (15%)
            specificity_score = self._score_specificity(result, query)
            result.rerank_scores['specificity'] = specificity_score * 0.15

            # Factor 5: Source quality (15%)
            quality_score = self._score_source_quality(result)
            result.rerank_scores['quality'] = quality_score * 0.15

            # Calculate final score
            result.final_score = sum(result.rerank_scores.values())

        # Detect conflicts if enabled
        if detect_conflicts:
            conflicts_map = self._detect_conflicts(results, query)
            for result in results:
                if result.chunk_id in conflicts_map:
                    result.conflicts = conflicts_map[result.chunk_id]
                    result.conflict_count = len(conflicts_map[result.chunk_id])
                    # Penalize conflicting results slightly
                    result.final_score *= (1 - (len(conflicts_map[result.chunk_id]) * 0.05))
                else:
                    result.conflicts = []
                    result.conflict_count = 0

        # Sort by final score
        reranked = sorted(results, key=lambda x: x.final_score, reverse=True)

        logger.info(f"Re-ranking complete. Top result score: {reranked[0].final_score:.3f}")
        return reranked

    def _score_citation_frequency(
        self,
        result: SearchResult,
        all_results: List[SearchResult]
    ) -> float:
        """
        Score based on how often this resource is cited by others.

        Higher citation frequency = more likely to be a key source.

        Args:
            result: Result to score
            all_results: All results for comparison

        Returns:
            Score 0-1
        """
        try:
            resource = self.db.query(Resource).filter(
                Resource.id == result.resource_id
            ).first()

            if not resource:
                return 0.0

            # Count citations
            citation_count = resource.citation_count or 0

            # Max possible citations (other documents in results)
            max_citations = len(set(r.resource_id for r in all_results if r.resource_id != result.resource_id))

            if max_citations == 0:
                return 0.5  # Single result, neutral score

            # Normalize
            score = min(1.0, citation_count / max(max_citations, 1))

            logger.debug(f"Citation score for {result.resource_title}: {score:.3f}")
            return score

        except Exception as e:
            logger.error(f"Error scoring citations: {e}")
            return 0.5

    def _score_recency(self, result: SearchResult) -> float:
        """
        Score based on how recent the resource is.

        Newer documents are preferred, but with graceful degradation.
        Documents older than 1 year get lower scores.

        Args:
            result: Result to score

        Returns:
            Score 0-1
        """
        try:
            resource = self.db.query(Resource).filter(
                Resource.id == result.resource_id
            ).first()

            if not resource or not resource.created_at:
                return 0.5  # Unknown, neutral score

            # Calculate days old
            days_old = (datetime.utcnow() - resource.created_at).days

            # Scoring function
            # Recent (< 30 days): 1.0
            # 6 months: 0.8
            # 1 year: 0.6
            # 2 years: 0.4
            # 3+ years: 0.2

            if days_old < 30:
                return 1.0
            elif days_old < 90:
                return 0.9
            elif days_old < 180:
                return 0.8
            elif days_old < 365:
                return 0.6
            elif days_old < 730:
                return 0.4
            else:
                return 0.2

        except Exception as e:
            logger.error(f"Error scoring recency: {e}")
            return 0.5

    def _score_specificity(self, result: SearchResult, query: str) -> float:
        """
        Score based on how directly the chunk addresses the query.

        High specificity = chunk directly answers the question.

        Args:
            result: Result to score
            query: User query

        Returns:
            Score 0-1
        """
        try:
            content = result.content.lower()
            query_lower = query.lower()

            # Exact phrase match (highest)
            if query_lower in content:
                return 1.0

            # All query terms present
            query_terms = set(query_lower.split())
            content_terms = set(content.split())
            overlap = len(query_terms & content_terms) / len(query_terms)

            # High overlap = specific answer
            return overlap

        except Exception as e:
            logger.error(f"Error scoring specificity: {e}")
            return 0.5

    def _score_source_quality(self, result: SearchResult) -> float:
        """
        Score based on source document quality.

        Different document types have different quality weights:
        - PDF research papers: 1.0 (highest)
        - Word documents: 0.8
        - Markdown: 0.8
        - Excel: 0.6
        - Text: 0.5
        - Web/URL: 0.7

        Also consider if document has metadata.

        Args:
            result: Result to score

        Returns:
            Score 0-1
        """
        try:
            resource = self.db.query(Resource).filter(
                Resource.id == result.resource_id
            ).first()

            if not resource:
                return 0.5

            # Type-based scoring
            type_scores = {
                'pdf': 1.0,
                'research': 1.0,
                'academic': 1.0,
                'word': 0.8,
                'docx': 0.8,
                'markdown': 0.8,
                'md': 0.8,
                'excel': 0.6,
                'xlsx': 0.6,
                'csv': 0.6,
                'text': 0.5,
                'txt': 0.5,
                'url': 0.7,
                'web': 0.7,
            }

            resource_type = resource.resource_type.lower()
            base_score = type_scores.get(resource_type, 0.5)

            # Boost if has rich metadata
            metadata_boost = 0.0
            if resource.resource_metadata:
                if resource.resource_metadata.get('title'):
                    metadata_boost += 0.05
                if resource.resource_metadata.get('author'):
                    metadata_boost += 0.05
                if resource.resource_metadata.get('pages'):
                    metadata_boost += 0.05

            final_score = min(1.0, base_score + metadata_boost)

            logger.debug(f"Quality score for {result.resource_title}: {final_score:.3f}")
            return final_score

        except Exception as e:
            logger.error(f"Error scoring source quality: {e}")
            return 0.5

    def _detect_conflicts(
        self,
        results: List[SearchResult],
        query: str,
        conflict_threshold: float = 0.7
    ) -> Dict[UUID, List[UUID]]:
        """
        Detect conflicting statements across sources.

        Compares top results to find contradictions.

        Args:
            results: Search results
            query: User query
            conflict_threshold: Confidence level for conflict (0-1)

        Returns:
            Map of chunk_id -> list of conflicting chunk_ids
        """
        conflicts = {}

        # Only check top 5 results for conflicts (performance)
        top_results = results[:5]

        logger.info(f"Checking {len(top_results)} results for conflicts")

        for i, result1 in enumerate(top_results):
            conflicts[result1.chunk_id] = []

            for result2 in top_results[i+1:]:
                # Skip if same resource (probably not conflicts)
                if result1.resource_id == result2.resource_id:
                    continue

                conflict = self._check_conflict(
                    result1,
                    result2,
                    query
                )

                if conflict:
                    conflicts[result1.chunk_id].append(result2.chunk_id)
                    if result2.chunk_id not in conflicts:
                        conflicts[result2.chunk_id] = []
                    conflicts[result2.chunk_id].append(result1.chunk_id)

        return conflicts

    def _check_conflict(
        self,
        result1: SearchResult,
        result2: SearchResult,
        query: str
    ) -> bool:
        """
        Check if two results have conflicting information.

        Uses LLM to detect subtle conflicts.

        Args:
            result1: First result
            result2: Second result
            query: User query

        Returns:
            True if conflict detected
        """
        try:
            prompt = f"""You are a fact-checking expert. Analyze these two statements from different sources.

QUERY: "{query}"

STATEMENT 1 (from {result1.resource_title}):
"{result1.content[:300]}"

STATEMENT 2 (from {result2.resource_title}):
"{result2.content[:300]}"

Do these statements contradict each other or present conflicting information about the query?
Answer ONLY with: YES or NO

Examples of conflicts:
- "X is true" vs "X is false"
- "GDP was 5%" vs "GDP was 3%"  
- "Study A found X" vs "Study B found Y" (different findings)

Examples of NOT conflicts:
- Same information from different sources
- One source more specific than other
- Both say "X is true"
- Compatible information that adds to each other"""

            response = call_llm(
                prompt,
                provider="ollama",
                max_tokens=10,
                temperature=0.1  # Low temp for consistency
            )

            is_conflict = "YES" in response.upper()

            if is_conflict:
                logger.warning(
                    f"Conflict detected between {result1.resource_title} and {result2.resource_title}"
                )

            return is_conflict

        except Exception as e:
            logger.error(f"Error checking conflict: {e}")
            return False  # Safe default

    def calculate_confidence(self, result: SearchResult) -> Dict[str, float]:
        """
        Calculate confidence metrics for a result.

        Args:
            result: Search result with scores

        Returns:
            Dict with various confidence metrics
        """
        try:
            confidence = {
                'overall': result.final_score,  # 0-1
                'citation_strength': result.rerank_scores.get('citation', 0) / 0.15,  # Denormalize
                'recency_strength': result.rerank_scores.get('recency', 0) / 0.15,
                'specificity_strength': result.rerank_scores.get('specificity', 0) / 0.15,
                'source_quality': result.rerank_scores.get('quality', 0) / 0.15,
                'conflict_risk': (result.conflict_count or 0) / 5,  # Risk per conflict
                'is_primary': result.rerank_scores.get('base', 0) > 0.5,
            }

            # Adjust overall confidence based on conflicts
            if result.conflict_count and result.conflict_count > 0:
                confidence['overall'] *= (1 - (result.conflict_count * 0.1))

            return confidence

        except Exception as e:
            logger.error(f"Error calculating confidence: {e}")
            return {
                'overall': result.final_score,
                'conflict_risk': 0.0
            }

    def get_reranking_explanation(self, result: SearchResult) -> str:
        """
        Generate human-readable explanation for why result was ranked this way.

        Args:
            result: Ranked search result

        Returns:
            Explanation string
        """
        try:
            explanation = f"Score: {result.final_score:.1%}\n"
            explanation += "Factors:\n"

            if hasattr(result, 'rerank_scores'):
                for factor, score in result.rerank_scores.items():
                    pct = (score / result.final_score * 100) if result.final_score > 0 else 0
                    explanation += f"  • {factor.capitalize()}: {score:.3f} ({pct:.0f}%)\n"

            if hasattr(result, 'conflict_count') and result.conflict_count:
                explanation += f"\n⚠️ {result.conflict_count} conflicting source(s) found"

            return explanation

        except Exception as e:
            logger.error(f"Error generating explanation: {e}")
            return ""
