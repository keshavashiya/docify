"""
Hybrid Search Service
Combines semantic (vector) search, keyword (BM25) search, and document graph traversal
"""
import logging
from typing import List, Dict, Optional
from uuid import UUID
from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import aggregate_order_by
from pgvector.sqlalchemy import Vector

from app.models.models import Chunk, Resource, Workspace
from app.schemas.search import SearchResult
from app.services.embeddings import EmbeddingsService
from app.services.query_expansion import QueryExpansionService

logger = logging.getLogger(__name__)


class SearchService:
    """Service for hybrid semantic + keyword + graph search"""

    def __init__(self, db: Session):
        self.db = db
        self.embeddings_service = EmbeddingsService()

    async def semantic_search(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 20
    ) -> List[tuple]:
        """
        Semantic search using vector similarity.

        Args:
            query: User query
            workspace_id: Workspace to search in
            top_k: Number of top results to return

        Returns:
            List of (chunk, distance, score) tuples
        """
        try:
            # Generate embedding for query
            query_embedding = await self.embeddings_service.embed(query)

            if query_embedding is None:
                logger.error("Failed to generate query embedding")
                return []

            # Query pgvector for nearest neighbors
            results = self.db.query(
                Chunk,
                Chunk.embedding.op('<->')(query_embedding).label('distance')
            ).join(
                Resource,
                Chunk.resource_id == Resource.id
            ).filter(
                Resource.workspace_id == workspace_id,
                Chunk.embedding.isnot(None)  # Only chunks with embeddings
            ).order_by(
                'distance'
            ).limit(top_k).all()

            # Convert distance to similarity score (0-1)
            # Distance is 0 for identical, higher for dissimilar
            semantic_results = []
            for chunk, distance in results:
                # Convert L2 distance to similarity
                similarity = 1 / (1 + float(distance))
                semantic_results.append((chunk, float(distance), similarity))

            logger.info(f"Semantic search returned {len(semantic_results)} results")
            return semantic_results

        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return []

    def keyword_search(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 20
    ) -> List[tuple]:
        """
        Keyword search using PostgreSQL full-text search (BM25-like).

        Args:
            query: User query
            workspace_id: Workspace to search in
            top_k: Number of top results to return

        Returns:
            List of (chunk, rank_score, score) tuples
        """
        try:
            # Create tsvector query from user query
            # Replace spaces with AND operator for better matching
            query_terms = query.split()
            ts_query = ' & '.join(query_terms)

            # PostgreSQL full-text search
            # This requires a tsvector column on chunks
            # For now, we'll use ILIKE as fallback
            results = self.db.query(Chunk).join(
                Resource,
                Chunk.resource_id == Resource.id
            ).filter(
                Resource.workspace_id == workspace_id
            )

            # Add relevance scoring - search in content and metadata
            scored_results = []
            for chunk in results:
                score = 0
                content_lower = chunk.content.lower()

                # Score based on term matches
                for term in query_terms:
                    term_lower = term.lower()
                    # Count occurrences
                    count = content_lower.count(term_lower)
                    if count > 0:
                        # Term found
                        score += count  # Each occurrence adds to score
                        # Bonus if at start of chunk
                        if content_lower.startswith(term_lower):
                            score += 2

                if score > 0:
                    scored_results.append((chunk, score, score / 100))

            # Sort by score descending
            scored_results.sort(key=lambda x: x[1], reverse=True)

            logger.info(f"Keyword search returned {len(scored_results)} results")
            return scored_results[:top_k]

        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []

    def document_graph_search(
        self,
        resource_ids: List[UUID],
        workspace_id: UUID,
        max_depth: int = 1
    ) -> List[Resource]:
        """
        Find related documents through document graph (citations).

        Args:
            resource_ids: Primary resources to expand from
            workspace_id: Workspace to search in
            max_depth: How many hops to traverse in the graph

        Returns:
            List of related resources
        """
        try:
            related_resources = set()

            for resource_id in resource_ids:
                resource = self.db.query(Resource).filter(
                    Resource.id == resource_id,
                    Resource.workspace_id == workspace_id
                ).first()

                if not resource:
                    continue

                # Get documents cited by this one
                citations = resource.resource_metadata.get('citations', [])
                if citations:
                    cited_docs = self.db.query(Resource).filter(
                        Resource.workspace_id == workspace_id,
                        Resource.title.in_(citations)
                    ).all()
                    related_resources.update([d.id for d in cited_docs])

                # Get documents that cite this one
                citing_docs = self.db.query(Resource).filter(
                    Resource.workspace_id == workspace_id,
                    Resource.resource_metadata['citations'].astext.contains(resource.title)
                ).all()
                related_resources.update([d.id for d in citing_docs])

            logger.info(f"Document graph search found {len(related_resources)} related resources")
            return [self.db.query(Resource).filter(Resource.id == rid).first() 
                    for rid in related_resources if rid not in resource_ids]

        except Exception as e:
            logger.error(f"Error in document graph search: {e}")
            return []

    def _combine_results_rrf(
        self,
        semantic_results: List[tuple],
        keyword_results: List[tuple],
        graph_chunks: List[Chunk],
        top_k: int = 20
    ) -> List[SearchResult]:
        """
        Combine results using Reciprocal Rank Fusion (RRF).

        RRF formula: score = 1 / (k + rank)
        where k is a constant (typically 60)

        Args:
            semantic_results: Results from semantic search (chunk, distance, similarity)
            keyword_results: Results from keyword search (chunk, rank_score, score)
            graph_chunks: Chunks from related documents
            top_k: Final number of results to return

        Returns:
            Combined, ranked search results
        """

        # Assign RRF scores
        combined_scores = {}  # chunk_id -> (chunk, combined_score, components)

        k = 60  # RRF constant

        # Semantic results (50% weight)
        for rank, (chunk, _, similarity) in enumerate(semantic_results, 1):
            rrf_score = (1 / (k + rank)) * 0.5
            if chunk.id not in combined_scores:
                combined_scores[chunk.id] = {
                    'chunk': chunk,
                    'semantic': rrf_score,
                    'keyword': 0,
                    'graph': 0,
                    'final': 0
                }
            else:
                combined_scores[chunk.id]['semantic'] = rrf_score

        # Keyword results (30% weight)
        for rank, (chunk, _, _) in enumerate(keyword_results, 1):
            rrf_score = (1 / (k + rank)) * 0.3
            if chunk.id not in combined_scores:
                combined_scores[chunk.id] = {
                    'chunk': chunk,
                    'semantic': 0,
                    'keyword': rrf_score,
                    'graph': 0,
                    'final': 0
                }
            else:
                combined_scores[chunk.id]['keyword'] = rrf_score

        # Graph chunks (20% weight)
        for rank, chunk in enumerate(graph_chunks, 1):
            rrf_score = (1 / (k + rank)) * 0.2
            if chunk.id not in combined_scores:
                combined_scores[chunk.id] = {
                    'chunk': chunk,
                    'semantic': 0,
                    'keyword': 0,
                    'graph': rrf_score,
                    'final': 0
                }
            else:
                combined_scores[chunk.id]['graph'] = rrf_score

        # Calculate final scores
        for chunk_id, scores in combined_scores.items():
            scores['final'] = scores['semantic'] + scores['keyword'] + scores['graph']

        # Sort by final score
        sorted_results = sorted(
            combined_scores.values(),
            key=lambda x: x['final'],
            reverse=True
        )[:top_k]

        # Convert to SearchResult objects
        search_results = []
        for result in sorted_results:
            chunk = result['chunk']
            resource = self.db.query(Resource).filter(Resource.id == chunk.resource_id).first()

            search_results.append(SearchResult(
                chunk_id=chunk.id,
                resource_id=resource.id,
                resource_title=resource.title,
                content=chunk.content,
                score=result['final'],
                source_info={
                    "page": chunk.page_number,
                    "section_title": chunk.section_title,
                    "type": resource.resource_type
                },
                search_components={
                    "semantic": result['semantic'],
                    "keyword": result['keyword'],
                    "graph": result['graph']
                }
            ))

        return search_results

    async def hybrid_search(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 20,
        use_query_expansion: bool = True
    ) -> List[SearchResult]:
        """
        Hybrid search combining semantic + keyword + graph search.

        Args:
            query: User query
            workspace_id: Workspace to search in
            top_k: Number of results to return
            use_query_expansion: Whether to expand query to multiple variants

        Returns:
            List of ranked search results
        """

        try:
            all_chunks = {}  # chunk_id -> chunk for deduplication

            if use_query_expansion:
                # Generate query variants
                queries = QueryExpansionService.combine_variants(query)
                logger.info(f"Searching with {len(queries)} query variants")
            else:
                queries = [query]

            # For each query variant, perform all three searches
            all_semantic = []
            all_keyword = []
            all_graph_chunks = []

            for q in queries:
                # Semantic search
                semantic = await self.semantic_search(q, workspace_id, top_k=top_k)
                all_semantic.extend(semantic)

                # Keyword search
                keyword = self.keyword_search(q, workspace_id, top_k=top_k)
                all_keyword.extend(keyword)

                # Get resource IDs from semantic results
                resource_ids = list(set(chunk.resource_id for chunk, _, _ in semantic))

                # Document graph search
                graph_resources = self.document_graph_search(
                    resource_ids,
                    workspace_id
                )

                # Get chunks from related resources
                for resource in graph_resources:
                    chunks = self.db.query(Chunk).filter(
                        Chunk.resource_id == resource.id
                    ).limit(3).all()
                    all_graph_chunks.extend(chunks)

            # Combine and deduplicate
            seen_ids = set()
            deduped_semantic = []
            for chunk, dist, sim in all_semantic:
                if chunk.id not in seen_ids:
                    deduped_semantic.append((chunk, dist, sim))
                    seen_ids.add(chunk.id)

            seen_ids = set()
            deduped_keyword = []
            for chunk, rank, score in all_keyword:
                if chunk.id not in seen_ids:
                    deduped_keyword.append((chunk, rank, score))
                    seen_ids.add(chunk.id)

            seen_ids = set()
            deduped_graph = []
            for chunk in all_graph_chunks:
                if chunk.id not in seen_ids:
                    deduped_graph.append(chunk)
                    seen_ids.add(chunk.id)

            # Combine using RRF
            results = self._combine_results_rrf(
                deduped_semantic,
                deduped_keyword,
                deduped_graph,
                top_k=top_k
            )

            logger.info(f"Hybrid search returned {len(results)} combined results")
            return results

        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            raise

    async def search(
        self,
        query: str,
        workspace_id: UUID,
        search_type: str = "hybrid",
        top_k: int = 20
    ) -> List[SearchResult]:
        """
        Generic search method supporting multiple types.

        Args:
            query: User query
            workspace_id: Workspace to search in
            search_type: "semantic", "keyword", or "hybrid"
            top_k: Number of results to return

        Returns:
            List of search results
        """

        if search_type == "semantic":
            results = await self.semantic_search(query, workspace_id, top_k)
            # Convert to SearchResult format
            return [
                SearchResult(
                    chunk_id=chunk.id,
                    resource_id=chunk.resource_id,
                    resource_title=chunk.resource.title,
                    content=chunk.content,
                    score=similarity,
                    source_info={
                        "page": chunk.page_number,
                        "section_title": chunk.section_title,
                        "type": chunk.resource.resource_type
                    }
                )
                for chunk, _, similarity in results
            ]

        elif search_type == "keyword":
            results = self.keyword_search(query, workspace_id, top_k)
            # Convert to SearchResult format
            return [
                SearchResult(
                    chunk_id=chunk.id,
                    resource_id=chunk.resource_id,
                    resource_title=chunk.resource.title,
                    content=chunk.content,
                    score=score,
                    source_info={
                        "page": chunk.page_number,
                        "section_title": chunk.section_title,
                        "type": chunk.resource.resource_type
                    }
                )
                for chunk, _, score in results
            ]

        else:  # hybrid
            return await self.hybrid_search(query, workspace_id, top_k)
