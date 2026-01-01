"""
Enhanced Hybrid Search Service
Combined vector + BM25 search with Reciprocal Rank Fusion (v2 Phase 3)

Features:
- Vector (semantic) search via pgvector
- BM25 keyword search for exact matches
- Reciprocal Rank Fusion (RRF) to combine results
- Configurable weights for different query types
"""
import logging
import re
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass
from collections import defaultdict

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.models.models import Resource, Chunk
from app.services.embeddings import EmbeddingsService, get_embeddings_service
from app.services.query_planner import SearchStrategy

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """Result from hybrid search"""
    chunk_id: str
    resource_id: str
    resource_title: str
    content: str
    vector_score: float
    bm25_score: float
    rrf_score: float
    rank: int

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "resource_title": self.resource_title,
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "vector_score": round(self.vector_score, 4),
            "bm25_score": round(self.bm25_score, 4),
            "rrf_score": round(self.rrf_score, 4),
            "rank": self.rank,
        }


class HybridSearchEngine:
    """
    Combines vector similarity and BM25 keyword search.

    Uses Reciprocal Rank Fusion (RRF) to merge rankings:
    RRF(d) = Σ 1 / (k + rank_i(d))

    where k=60 is a standard constant that prevents high-ranking
    documents from dominating.
    """

    RRF_K = 60  # Standard RRF constant

    def __init__(
        self,
        embeddings_service: Optional[EmbeddingsService] = None,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4
    ):
        """
        Initialize hybrid search engine.

        Args:
            embeddings_service: Service for generating embeddings
            vector_weight: Weight for vector search in final ranking
            bm25_weight: Weight for BM25 search in final ranking
        """
        self.embeddings = embeddings_service or get_embeddings_service()
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight

        # BM25 index cache (workspace_id -> BM25Okapi)
        self._bm25_cache: Dict[str, tuple] = {}

    async def search(
        self,
        query: str,
        db: Session,
        workspace_id: str,
        top_k: int = 10,
        strategy: SearchStrategy = SearchStrategy.HYBRID,
        min_score: float = 0.0
    ) -> List[HybridSearchResult]:
        """
        Perform hybrid search combining vector and BM25.

        Args:
            query: Search query
            db: Database session
            workspace_id: Workspace to search in
            top_k: Number of results to return
            strategy: Search strategy (semantic, keyword, hybrid)
            min_score: Minimum RRF score threshold

        Returns:
            List of HybridSearchResult sorted by RRF score
        """
        results = []

        # Get vector results
        vector_results = {}
        if strategy in [SearchStrategy.SEMANTIC, SearchStrategy.HYBRID]:
            vector_results = await self._vector_search(
                query, db, workspace_id, top_k * 2
            )

        # Get BM25 results
        bm25_results = {}
        if strategy in [SearchStrategy.KEYWORD, SearchStrategy.HYBRID]:
            bm25_results = self._bm25_search(
                query, db, workspace_id, top_k * 2
            )

        # Combine results using RRF
        combined = self._reciprocal_rank_fusion(
            vector_results,
            bm25_results,
            strategy
        )

        # Build result objects
        chunk_ids = list(combined.keys())[:top_k]
        chunks_data = self._get_chunk_data(db, chunk_ids)

        for rank, (chunk_id, rrf_score) in enumerate(
            sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]
        ):
            if rrf_score < min_score:
                continue

            chunk_data = chunks_data.get(chunk_id, {})
            results.append(HybridSearchResult(
                chunk_id=chunk_id,
                resource_id=chunk_data.get("resource_id", ""),
                resource_title=chunk_data.get("resource_title", "Unknown"),
                content=chunk_data.get("content", ""),
                vector_score=vector_results.get(chunk_id, 0.0),
                bm25_score=bm25_results.get(chunk_id, 0.0),
                rrf_score=rrf_score,
                rank=rank + 1
            ))

        return results

    async def _vector_search(
        self,
        query: str,
        db: Session,
        workspace_id: str,
        top_k: int
    ) -> Dict[str, float]:
        """Perform vector similarity search using pgvector"""
        results = {}

        try:
            # Get query embedding
            query_embedding = self.embeddings.embed(query)
            if not query_embedding:
                return results

            # Query pgvector with cosine distance
            # Note: pgvector uses <=> for cosine distance (1 - similarity)
            from sqlalchemy import text

            sql = text("""
                SELECT
                    c.id::text as chunk_id,
                    1 - (c.embedding <=> :embedding) as similarity
                FROM chunks c
                JOIN resources r ON c.resource_id = r.id
                WHERE r.workspace_id = :workspace_id
                    AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> :embedding
                LIMIT :top_k
            """)

            result = db.execute(sql, {
                "embedding": str(query_embedding),
                "workspace_id": str(workspace_id),
                "top_k": top_k
            })

            for row in result:
                results[row.chunk_id] = float(row.similarity)

        except Exception as e:
            logger.error(f"Vector search error: {e}")

        return results

    def _bm25_search(
        self,
        query: str,
        db: Session,
        workspace_id: str,
        top_k: int
    ) -> Dict[str, float]:
        """Perform BM25 keyword search"""
        results = {}

        try:
            # Get or build BM25 index
            bm25, chunk_ids, chunk_texts = self._get_bm25_index(db, workspace_id)

            if bm25 is None or not chunk_ids:
                return results

            # Tokenize query
            query_tokens = self._tokenize(query)

            # Get BM25 scores
            scores = bm25.get_scores(query_tokens)

            # Get top K
            scored_indices = sorted(
                enumerate(scores),
                key=lambda x: x[1],
                reverse=True
            )[:top_k]

            # Normalize scores
            max_score = max(s for _, s in scored_indices) if scored_indices else 1.0

            for idx, score in scored_indices:
                if score > 0:
                    results[chunk_ids[idx]] = score / max_score

        except Exception as e:
            logger.error(f"BM25 search error: {e}")

        return results

    def _get_bm25_index(
        self,
        db: Session,
        workspace_id: str
    ) -> Tuple[Optional[BM25Okapi], List[str], List[str]]:
        """Get or build BM25 index for workspace"""
        cache_key = str(workspace_id)

        # Check cache
        if cache_key in self._bm25_cache:
            return self._bm25_cache[cache_key]

        # Build index
        chunks = db.query(Chunk).join(Resource).filter(
            Resource.workspace_id == workspace_id
        ).all()

        if not chunks:
            return None, [], []

        chunk_ids = [str(c.id) for c in chunks]
        chunk_texts = [c.content for c in chunks]

        # Tokenize all documents
        tokenized = [self._tokenize(text) for text in chunk_texts]

        # Build BM25 index
        bm25 = BM25Okapi(tokenized)

        # Cache (with limited size to prevent memory bloat)
        if len(self._bm25_cache) > 50:
            # Remove oldest entry
            oldest = next(iter(self._bm25_cache))
            del self._bm25_cache[oldest]

        self._bm25_cache[cache_key] = (bm25, chunk_ids, chunk_texts)

        logger.debug(f"Built BM25 index for workspace {workspace_id}: {len(chunks)} chunks")

        return bm25, chunk_ids, chunk_texts

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text for BM25"""
        # Simple tokenization: lowercase, remove punctuation, split on whitespace
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = text.split()

        # Remove very short tokens
        tokens = [t for t in tokens if len(t) > 2]

        return tokens

    def _reciprocal_rank_fusion(
        self,
        vector_results: Dict[str, float],
        bm25_results: Dict[str, float],
        strategy: SearchStrategy
    ) -> Dict[str, float]:
        """
        Combine rankings using Reciprocal Rank Fusion.

        RRF score = w1 * (1 / (k + rank_vector)) + w2 * (1 / (k + rank_bm25))
        """
        combined = defaultdict(float)

        # Adjust weights based on strategy
        if strategy == SearchStrategy.SEMANTIC:
            v_weight, b_weight = 1.0, 0.0
        elif strategy == SearchStrategy.KEYWORD:
            v_weight, b_weight = 0.0, 1.0
        else:
            v_weight, b_weight = self.vector_weight, self.bm25_weight

        # Convert scores to ranks
        vector_ranks = self._scores_to_ranks(vector_results)
        bm25_ranks = self._scores_to_ranks(bm25_results)

        # Calculate RRF for all documents
        all_chunk_ids = set(vector_results.keys()) | set(bm25_results.keys())

        for chunk_id in all_chunk_ids:
            rrf_score = 0.0

            if chunk_id in vector_ranks and v_weight > 0:
                rrf_score += v_weight * (1.0 / (self.RRF_K + vector_ranks[chunk_id]))

            if chunk_id in bm25_ranks and b_weight > 0:
                rrf_score += b_weight * (1.0 / (self.RRF_K + bm25_ranks[chunk_id]))

            combined[chunk_id] = rrf_score

        return dict(combined)

    def _scores_to_ranks(self, scores: Dict[str, float]) -> Dict[str, int]:
        """Convert scores to ranks (1-indexed)"""
        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return {item[0]: rank + 1 for rank, item in enumerate(sorted_items)}

    def _get_chunk_data(
        self,
        db: Session,
        chunk_ids: List[str]
    ) -> Dict[str, dict]:
        """Get chunk and resource data for results"""
        data = {}

        if not chunk_ids:
            return data

        try:
            chunks = db.query(Chunk).filter(
                Chunk.id.in_(chunk_ids)
            ).all()

            resource_ids = [c.resource_id for c in chunks]
            resources = {
                r.id: r for r in
                db.query(Resource).filter(Resource.id.in_(resource_ids)).all()
            }

            for chunk in chunks:
                resource = resources.get(chunk.resource_id)
                data[str(chunk.id)] = {
                    "resource_id": str(chunk.resource_id),
                    "resource_title": resource.title if resource else "Unknown",
                    "content": chunk.content,
                }

        except Exception as e:
            logger.error(f"Error fetching chunk data: {e}")

        return data

    def clear_cache(self, workspace_id: Optional[str] = None):
        """Clear BM25 cache"""
        if workspace_id:
            self._bm25_cache.pop(str(workspace_id), None)
        else:
            self._bm25_cache.clear()
        logger.info("BM25 cache cleared")


# Singleton instance
_hybrid_search: Optional[HybridSearchEngine] = None


def get_hybrid_search() -> HybridSearchEngine:
    """Get or create hybrid search singleton"""
    global _hybrid_search
    if _hybrid_search is None:
        _hybrid_search = HybridSearchEngine()
    return _hybrid_search
