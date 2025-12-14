"""
Context Assembly Service
Builds document relationships, assembles context for LLM with token budget management
"""
import logging
from typing import List, Dict, Optional, Set, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import ARRAY

from app.models.models import Resource, Chunk
from app.schemas.search import SearchResult, EnhancedSearchResult

logger = logging.getLogger(__name__)


class DocumentNode:
    """Represents a document in the relationship graph"""
    
    def __init__(self, resource_id: UUID, title: str, resource_type: str):
        self.resource_id = resource_id
        self.title = title
        self.resource_type = resource_type
        self.related_docs: Set[UUID] = set()
        self.chunks_used: List[UUID] = []
        self.relevance_score: float = 0.0
        self.metadata: Dict = {}


class ContextWindow:
    """Manages token budget for context assembly"""
    
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.used_tokens = 0
        self.chunks: List[Dict] = []
        self.metadata_tokens = 200  # Reserve for metadata/structure
    
    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.used_tokens - self.metadata_tokens
    
    def can_add(self, token_count: int) -> bool:
        return token_count <= self.available_tokens
    
    def add_chunk(self, chunk_data: Dict, token_count: int) -> bool:
        if not self.can_add(token_count):
            return False
        self.chunks.append(chunk_data)
        self.used_tokens += token_count
        return True


class AssembledContext:
    """The final assembled context for LLM consumption"""
    
    def __init__(self):
        self.primary_chunks: List[Dict] = []
        self.supporting_chunks: List[Dict] = []
        self.document_metadata: List[Dict] = []
        self.related_documents: List[Dict] = []
        self.total_tokens: int = 0
        self.source_count: int = 0
        self.has_conflicts: bool = False
        self.conflict_summary: Optional[str] = None
    
    def to_prompt_context(self) -> str:
        """Convert to formatted string for LLM prompt"""
        sections = []
        
        # Primary sources section
        if self.primary_chunks:
            sections.append("## PRIMARY SOURCES (Most Relevant)")
            for i, chunk in enumerate(self.primary_chunks, 1):
                sections.append(f"\n### Source [{i}]: {chunk['title']}")
                sections.append(f"Type: {chunk['type']} | Relevance: {chunk['score']:.2f}")
                sections.append(f"\n{chunk['content']}\n")
        
        # Supporting sources section
        if self.supporting_chunks:
            sections.append("\n## SUPPORTING SOURCES (Additional Context)")
            for i, chunk in enumerate(self.supporting_chunks, 1):
                idx = len(self.primary_chunks) + i
                sections.append(f"\n### Source [{idx}]: {chunk['title']}")
                sections.append(f"Type: {chunk['type']} | Relevance: {chunk['score']:.2f}")
                sections.append(f"\n{chunk['content']}\n")
        
        # Related documents (metadata only)
        if self.related_documents:
            sections.append("\n## RELATED DOCUMENTS (For Reference)")
            for doc in self.related_documents[:5]:  # Limit to 5
                sections.append(f"- {doc['title']} ({doc['type']})")
        
        # Conflict warning
        if self.has_conflicts and self.conflict_summary:
            sections.append(f"\n## ⚠️ CONFLICT NOTICE\n{self.conflict_summary}")
        
        return "\n".join(sections)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API response"""
        return {
            "primary_chunks": self.primary_chunks,
            "supporting_chunks": self.supporting_chunks,
            "document_metadata": self.document_metadata,
            "related_documents": self.related_documents,
            "total_tokens": self.total_tokens,
            "source_count": self.source_count,
            "has_conflicts": self.has_conflicts,
            "conflict_summary": self.conflict_summary,
            "formatted_context": self.to_prompt_context()
        }


class ContextAssemblyService:
    """Service for assembling context from search results for LLM consumption"""
    
    # Token budget defaults
    DEFAULT_MAX_TOKENS = 2000
    PRIMARY_BUDGET_RATIO = 0.6  # 60% for primary sources
    SUPPORTING_BUDGET_RATIO = 0.3  # 30% for supporting
    METADATA_BUDGET_RATIO = 0.1  # 10% for metadata
    
    # Approximate tokens per character (conservative estimate)
    CHARS_PER_TOKEN = 4
    
    def __init__(self, db: Session):
        self.db = db
        self._document_graph: Dict[UUID, DocumentNode] = {}
    
    def assemble_context(
        self,
        results: List[EnhancedSearchResult],
        query: str,
        workspace_id: UUID,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        include_related: bool = True,
        deduplicate: bool = True
    ) -> AssembledContext:
        """
        Assemble context from search results for LLM consumption.
        
        Args:
            results: Reranked search results
            query: Original user query
            workspace_id: Workspace context
            max_tokens: Maximum token budget
            include_related: Whether to include related documents
            deduplicate: Whether to deduplicate similar content
            
        Returns:
            AssembledContext ready for LLM prompt
        """
        if not results:
            logger.warning("No results to assemble context from")
            return AssembledContext()
        
        logger.info(f"Assembling context from {len(results)} results (max {max_tokens} tokens)")
        
        # Step 1: Build document relationship graph
        self._build_document_graph(results, workspace_id)
        
        # Step 2: Deduplicate if enabled
        if deduplicate:
            results = self._deduplicate_results(results)
        
        # Step 3: Categorize results (primary vs supporting)
        primary, supporting = self._categorize_results(results)
        
        # Step 4: Allocate token budgets
        primary_budget = int(max_tokens * self.PRIMARY_BUDGET_RATIO)
        supporting_budget = int(max_tokens * self.SUPPORTING_BUDGET_RATIO)
        
        # Step 5: Fill primary context
        context = AssembledContext()
        context.primary_chunks = self._fill_context_window(
            primary, primary_budget
        )
        
        # Step 6: Fill supporting context
        context.supporting_chunks = self._fill_context_window(
            supporting, supporting_budget
        )
        
        # Step 7: Add document metadata
        context.document_metadata = self._extract_document_metadata(results)
        
        # Step 8: Find related documents
        if include_related:
            context.related_documents = self._find_related_documents(
                results, workspace_id
            )
        
        # Step 9: Handle conflicts
        conflicts = self._extract_conflicts(results)
        if conflicts:
            context.has_conflicts = True
            context.conflict_summary = self._summarize_conflicts(conflicts)
        
        # Step 10: Calculate totals
        context.total_tokens = self._calculate_total_tokens(context)
        context.source_count = len(set(
            c['resource_id'] for c in context.primary_chunks + context.supporting_chunks
        ))
        
        logger.info(
            f"Context assembled: {len(context.primary_chunks)} primary, "
            f"{len(context.supporting_chunks)} supporting, "
            f"{context.total_tokens} tokens"
        )
        
        return context
    
    def _build_document_graph(
        self,
        results: List[SearchResult],
        workspace_id: UUID
    ) -> None:
        """Build a graph of document relationships based on search results"""
        self._document_graph.clear()
        
        # Create nodes for each unique document
        resource_ids = set(r.resource_id for r in results)
        
        for result in results:
            if result.resource_id not in self._document_graph:
                self._document_graph[result.resource_id] = DocumentNode(
                    resource_id=result.resource_id,
                    title=result.resource_title,
                    resource_type=result.source_info.get('type', 'unknown')
                )
            
            node = self._document_graph[result.resource_id]
            node.chunks_used.append(result.chunk_id)
            node.relevance_score = max(
                node.relevance_score,
                result.final_score or result.score
            )
        
        # Find relationships between documents (same tags, similar metadata)
        self._discover_relationships(workspace_id)
    
    def _discover_relationships(self, workspace_id: UUID) -> None:
        """Discover relationships between documents in the graph"""
        if len(self._document_graph) < 2:
            return
        
        # Get resources for relationship analysis
        resource_ids = list(self._document_graph.keys())
        resources = self.db.query(Resource).filter(
            Resource.id.in_(resource_ids),
            Resource.workspace_id == workspace_id
        ).all()
        
        resource_map = {r.id: r for r in resources}
        
        # Find relationships based on shared tags
        for rid1, node1 in self._document_graph.items():
            r1 = resource_map.get(rid1)
            if not r1 or not r1.tags:
                continue
            
            tags1 = set(r1.tags) if r1.tags else set()
            
            for rid2, node2 in self._document_graph.items():
                if rid1 >= rid2:  # Avoid duplicates and self-reference
                    continue
                
                r2 = resource_map.get(rid2)
                if not r2 or not r2.tags:
                    continue
                
                tags2 = set(r2.tags) if r2.tags else set()
                
                # If they share any tags, they're related
                if tags1 & tags2:
                    node1.related_docs.add(rid2)
                    node2.related_docs.add(rid1)
    
    def _deduplicate_results(
        self,
        results: List[SearchResult]
    ) -> List[SearchResult]:
        """Remove near-duplicate content from results"""
        if len(results) <= 1:
            return results
        
        deduplicated = []
        seen_content_hashes = set()
        
        for result in results:
            # Create a simple content signature (first 200 chars normalized)
            content_sig = result.content[:200].lower().strip()
            content_hash = hash(content_sig)
            
            if content_hash not in seen_content_hashes:
                seen_content_hashes.add(content_hash)
                deduplicated.append(result)
        
        logger.info(f"Deduplication: {len(results)} -> {len(deduplicated)} results")
        return deduplicated
    
    def _categorize_results(
        self,
        results: List[SearchResult]
    ) -> Tuple[List[SearchResult], List[SearchResult]]:
        """
        Categorize results into primary (high relevance) and supporting.
        
        Primary: top 30% or score > 0.7
        Supporting: rest
        """
        if not results:
            return [], []
        
        # Use final_score if available, else score
        scored = [(r, r.final_score or r.score) for r in results]
        scored.sort(key=lambda x: x[1], reverse=True)
        
        # Primary: top 30% or score > 0.7
        primary_count = max(1, len(scored) // 3)
        primary_threshold = 0.7
        
        primary = []
        supporting = []
        
        for i, (result, score) in enumerate(scored):
            if i < primary_count or score >= primary_threshold:
                primary.append(result)
            else:
                supporting.append(result)
        
        return primary, supporting
    
    def _fill_context_window(
        self,
        results: List[SearchResult],
        max_tokens: int
    ) -> List[Dict]:
        """Fill context window with chunks up to token budget"""
        window = ContextWindow(max_tokens=max_tokens)
        chunks = []
        
        for result in results:
            # Estimate token count
            token_count = self._estimate_tokens(result.content)
            
            chunk_data = {
                "chunk_id": str(result.chunk_id),
                "resource_id": str(result.resource_id),
                "title": result.resource_title,
                "type": result.source_info.get('type', 'document'),
                "content": result.content,
                "score": result.final_score or result.score,
                "token_count": token_count,
                "metadata": {
                    "section": result.source_info.get('section_title'),
                    "page": result.source_info.get('page')
                }
            }
            
            if window.add_chunk(chunk_data, token_count):
                chunks.append(chunk_data)
            else:
                # Try to truncate content to fit
                available = window.available_tokens
                if available > 100:  # Only if we have meaningful space
                    truncated_content = result.content[:available * self.CHARS_PER_TOKEN]
                    chunk_data['content'] = truncated_content + "..."
                    chunk_data['token_count'] = available
                    chunk_data['truncated'] = True
                    window.add_chunk(chunk_data, available)
                    chunks.append(chunk_data)
                break  # No more space
        
        return chunks
    
    def _extract_document_metadata(
        self,
        results: List[SearchResult]
    ) -> List[Dict]:
        """Extract metadata for documents in results"""
        metadata = []
        seen_resources = set()
        
        for result in results:
            if result.resource_id in seen_resources:
                continue
            seen_resources.add(result.resource_id)
            
            # Get resource from DB for full metadata
            resource = self.db.query(Resource).filter(
                Resource.id == result.resource_id
            ).first()
            
            if resource:
                metadata.append({
                    "resource_id": str(resource.id),
                    "title": resource.title,
                    "type": resource.resource_type,
                    "source_url": resource.source_url,
                    "created_at": resource.created_at.isoformat() if resource.created_at else None,
                    "tags": resource.tags or [],
                    "chunks_in_context": sum(
                        1 for r in results if r.resource_id == resource.id
                    )
                })
        
        return metadata
    
    def _find_related_documents(
        self,
        results: List[SearchResult],
        workspace_id: UUID
    ) -> List[Dict]:
        """Find documents related to those in the results but not in results"""
        result_resource_ids = set(r.resource_id for r in results)
        related = []
        
        # Get related via graph
        for resource_id in result_resource_ids:
            if resource_id in self._document_graph:
                node = self._document_graph[resource_id]
                for related_id in node.related_docs:
                    if related_id not in result_resource_ids:
                        resource = self.db.query(Resource).filter(
                            Resource.id == related_id
                        ).first()
                        if resource and resource.id not in [r['resource_id'] for r in related]:
                            related.append({
                                "resource_id": str(resource.id),
                                "title": resource.title,
                                "type": resource.resource_type,
                                "relationship": "shared_tags"
                            })
        
        # Also find by shared tags if we have few related
        if len(related) < 3:
            # Get tags from result resources
            all_tags = set()
            for resource_id in result_resource_ids:
                resource = self.db.query(Resource).filter(
                    Resource.id == resource_id
                ).first()
                if resource and resource.tags:
                    all_tags.update(resource.tags)
            
            if all_tags:
                # Find other resources with same tags using PostgreSQL array overlap operator
                # Build OR condition: tags && ARRAY['tag1', 'tag2', ...]
                from sqlalchemy import text
                tag_list = list(all_tags)
                tag_related = self.db.query(Resource).filter(
                    Resource.workspace_id == workspace_id,
                    Resource.id.notin_(result_resource_ids),
                    Resource.tags.op('&&')(tag_list)  # PostgreSQL overlap operator
                ).limit(5).all()
                
                for resource in tag_related:
                    if str(resource.id) not in [r['resource_id'] for r in related]:
                        related.append({
                            "resource_id": str(resource.id),
                            "title": resource.title,
                            "type": resource.resource_type,
                            "relationship": "shared_tags"
                        })
        
        return related[:10]  # Limit to 10
    
    def _extract_conflicts(
        self,
        results: List[SearchResult]
    ) -> List[Tuple[SearchResult, SearchResult]]:
        """Extract conflict pairs from results"""
        conflicts = []
        
        for result in results:
            if hasattr(result, 'conflicts') and result.conflicts:
                for conflict_id in result.conflicts:
                    # Find the conflicting result
                    conflicting = next(
                        (r for r in results if r.chunk_id == conflict_id),
                        None
                    )
                    if conflicting:
                        # Avoid duplicates (A conflicts with B = B conflicts with A)
                        pair = tuple(sorted([result.chunk_id, conflict_id], key=str))
                        if pair not in [(c[0].chunk_id, c[1].chunk_id) for c in conflicts]:
                            conflicts.append((result, conflicting))
        
        return conflicts
    
    def _summarize_conflicts(
        self,
        conflicts: List[Tuple[SearchResult, SearchResult]]
    ) -> str:
        """Create a summary of detected conflicts"""
        if not conflicts:
            return ""
        
        summaries = []
        for r1, r2 in conflicts[:3]:  # Limit to top 3 conflicts
            summaries.append(
                f"- '{r1.resource_title}' may conflict with '{r2.resource_title}'"
            )
        
        if len(conflicts) > 3:
            summaries.append(f"- ... and {len(conflicts) - 3} more potential conflicts")
        
        return "The following sources may contain conflicting information:\n" + "\n".join(summaries)
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text"""
        return len(text) // self.CHARS_PER_TOKEN
    
    def _calculate_total_tokens(self, context: AssembledContext) -> int:
        """Calculate total tokens used in context"""
        total = 0
        
        for chunk in context.primary_chunks:
            total += chunk.get('token_count', 0)
        
        for chunk in context.supporting_chunks:
            total += chunk.get('token_count', 0)
        
        # Add estimate for metadata and structure
        total += 200
        
        return total
    
    def get_context_summary(self, context: AssembledContext) -> Dict:
        """Get a summary of the assembled context"""
        return {
            "primary_sources": len(context.primary_chunks),
            "supporting_sources": len(context.supporting_chunks),
            "unique_documents": context.source_count,
            "related_documents": len(context.related_documents),
            "total_tokens": context.total_tokens,
            "has_conflicts": context.has_conflicts,
            "documents": [
                {
                    "title": m["title"],
                    "type": m["type"],
                    "chunks_used": m["chunks_in_context"]
                }
                for m in context.document_metadata
            ]
        }
