"""
Multi-Document Agent Manager
Top-level orchestrator for multi-document RAG queries (v2)

Coordinates:
- Query planning for strategy selection
- Document selection via agent pool
- Parallel retrieval from multiple documents
- Result fusion and ranking
- Response generation with citations
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.models import Resource, Chunk
from app.services.document_agent import (
    DocumentAgent,
    DocumentAgentPool,
    get_agent_pool
)
from app.services.query_planner import (
    QueryPlanner,
    QueryPlan,
    QueryType,
    SearchStrategy,
    get_query_planner
)
from app.services.llm import LLMService, get_llm_service
from app.services.embeddings import EmbeddingsService, get_embeddings_service
from app.services.hybrid_search import get_hybrid_search
from app.services.ollama_manager import get_ollama_manager
from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RetrievalResult:
    """Result from retrieving from a single document"""
    doc_id: UUID
    doc_title: str
    chunk_id: UUID
    content: str
    relevance_score: float
    confidence: float
    source_metadata: dict = field(default_factory=dict)


@dataclass
class FusedResult:
    """Fusion of results from multiple documents"""
    content: str
    doc_id: UUID
    doc_title: str
    chunk_id: UUID
    relevance_score: float
    confidence: float
    final_score: float
    source_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "doc_id": str(self.doc_id),
            "doc_title": self.doc_title,
            "chunk_id": str(self.chunk_id),
            "relevance_score": self.relevance_score,
            "final_score": self.final_score,
            "source_url": self.source_url,
        }


@dataclass
class MultiAgentResponse:
    """Complete response from multi-document query"""
    answer: str
    citations: List[Tuple[int, str, str]]  # [(index, source_title, url), ...]
    sources: List[str]
    source_documents: List[dict]
    confidence: float
    execution_time_ms: int
    query_plan: Optional[dict] = None
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "citations": [
                {"index": idx, "source": src, "url": url}
                for idx, src, url in self.citations
            ],
            "sources": self.sources,
            "source_documents": self.source_documents,
            "confidence": self.confidence,
            "execution_time_ms": self.execution_time_ms,
            "query_plan": self.query_plan,
            "metrics": self.metrics,
        }


# ============================================================================
# Multi-Document Agent
# ============================================================================

class MultiDocumentAgent:
    """
    Top-level orchestrator for multi-document RAG queries.

    Pipeline:
    1. Query Planning - Analyze query, determine strategy
    2. Document Selection - Score and select relevant documents
    3. Parallel Retrieval - Fetch chunks from multiple docs simultaneously
    4. Result Fusion - Combine and rank results
    5. Response Generation - LLM generates answer with citations
    """

    def __init__(
        self,
        db: Session,
        agent_pool: Optional[DocumentAgentPool] = None,
        query_planner: Optional[QueryPlanner] = None,
        llm_service: Optional[LLMService] = None,
        embeddings_service: Optional[EmbeddingsService] = None
    ):
        self.db = db
        self.agent_pool = agent_pool or get_agent_pool()
        self.query_planner = query_planner or get_query_planner()
        self.llm = llm_service or get_llm_service()
        self.embeddings = embeddings_service or get_embeddings_service()
        self.hybrid_search = get_hybrid_search()
        self.ollama_manager = get_ollama_manager()

    async def query(
        self,
        user_query: str,
        workspace_id: UUID,
        top_k_docs: Optional[int] = 3,  # Reduced from 5 for faster response
        use_query_planning: bool = True,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> MultiAgentResponse:
        """
        Execute a multi-document query.

        Args:
            user_query: User's question
            workspace_id: Workspace to search in
            top_k_docs: Override number of documents to use
            use_query_planning: Whether to use LLM for query planning

        Returns:
            MultiAgentResponse with answer, citations, and metrics
        """
        start_time = time.time()
        metrics = {}

        try:
            # Step 1: Query Planning
            plan_start = time.time()
            query_plan = await self.query_planner.plan_query(
                user_query,
                use_llm=use_query_planning
            )
            metrics["planning_ms"] = int((time.time() - plan_start) * 1000)

            # Override docs count if specified
            num_docs = top_k_docs or query_plan.num_documents_needed

            logger.info(f"Query plan: type={query_plan.query_type.value}, "
                       f"strategy={query_plan.search_strategy.value}, docs={num_docs}")

            # Step 2: Document Selection
            select_start = time.time()
            relevant_agents = await self._select_documents(
                user_query,
                workspace_id,
                top_k=num_docs,
                strategy=query_plan.search_strategy
            )
            metrics["selection_ms"] = int((time.time() - select_start) * 1000)
            metrics["docs_selected"] = len(relevant_agents)

            if not relevant_agents:
                return self._empty_response(user_query, query_plan, start_time)

            # Step 3: Parallel Retrieval
            retrieve_start = time.time()
            retrieval_results = await self._parallel_retrieve(
                user_query,
                workspace_id,
                relevant_agents,
                query_plan
            )
            metrics["retrieval_ms"] = int((time.time() - retrieve_start) * 1000)
            metrics["chunks_retrieved"] = len(retrieval_results)

            if not retrieval_results:
                return self._empty_response(user_query, query_plan, start_time)

            # Step 4: Result Fusion
            fuse_start = time.time()
            fused_results = self._fuse_and_rank_results(retrieval_results)
            metrics["fusion_ms"] = int((time.time() - fuse_start) * 1000)

            # Step 5: Response Generation
            gen_start = time.time()
            generation_results = await self._generate_response(
                user_query,
                fused_results,
                query_plan,
                conversation_history=conversation_history
            )
            llm_metrics = generation_results.get("llm_metrics", {})
            metrics["tokens_used"] = llm_metrics.get("eval_count", 0)
            metrics["prompt_tokens"] = llm_metrics.get("prompt_eval_count", 0)
            metrics["generation_ms"] = int((time.time() - gen_start) * 1000)

            # Step 6: Update access scores (fire and forget)
            asyncio.create_task(self._update_access_scores(relevant_agents))

            # Calculate total time
            execution_time_ms = int((time.time() - start_time) * 1000)

            return MultiAgentResponse(
                answer=generation_results["answer"],
                citations=generation_results["citations"],
                sources=generation_results["sources"],
                source_documents=generation_results["source_documents"],
                confidence=generation_results["confidence"],
                execution_time_ms=execution_time_ms,
                query_plan=query_plan.to_dict(),
                metrics=metrics
            )

        except Exception as e:
            logger.error(f"Multi-document query failed: {e}")
            raise

    async def _select_documents(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
        strategy: SearchStrategy = SearchStrategy.HYBRID
    ) -> List[Tuple[UUID, DocumentAgent, float]]:
        """
        Select most relevant documents for query.

        Returns list of (doc_id, agent, relevance_score) tuples.
        """
        # Get all resources in workspace
        resources = self.db.query(Resource).filter(
            Resource.workspace_id == workspace_id,
            Resource.embedding_status == "complete"
        ).all()

        if not resources:
            logger.warning(f"No resources found in workspace {workspace_id}")
            return []

        # Score each document
        scored_docs = []
        min_threshold = getattr(settings, 'AGENT_RELEVANCE_THRESHOLD', 0.1)

        for resource in resources:
            try:
                # Get or create agent for this document
                agent = await self.agent_pool.get_or_create(resource.id, self.db)

                # Calculate relevance score
                relevance = agent.get_relevance_score(query)

                if relevance >= min_threshold:
                    scored_docs.append((resource.id, agent, relevance))

            except Exception as e:
                logger.warning(f"Error scoring document {resource.id}: {e}")
                continue

        # Sort by relevance and return top K
        scored_docs.sort(key=lambda x: x[2], reverse=True)
        selected = scored_docs[:top_k]

        logger.info(f"Selected {len(selected)}/{len(resources)} documents for query")

        return selected

    async def _parallel_retrieve(
        self,
        query: str,
        workspace_id: UUID,
        agents: List[Tuple[UUID, DocumentAgent, float]],
        query_plan: QueryPlan
    ) -> List[RetrievalResult]:
        """
        Retrieve relevant chunks from multiple documents in parallel using SQL.
        """
        # Get selected document IDs
        doc_ids = [str(doc_id) for doc_id, _, _ in agents]

        # Use HybridSearchEngine for optimized SQL-level search
        # We search across all selected documents in the workspace
        hybrid_results = await self.hybrid_search.search(
            query=query,
            db=self.db,
            workspace_id=str(workspace_id),
            top_k=query_plan.num_documents_needed * 4,
            strategy=query_plan.search_strategy
        )

        # Map back to RetrievalResult format
        # Filter for only chunks from selected documents
        selected_doc_set = {doc_id for doc_id, _, _ in agents}

        results = []
        for res in hybrid_results:
            doc_id = UUID(res.resource_id)
            if doc_id in selected_doc_set:
                results.append(RetrievalResult(
                    doc_id=doc_id,
                    doc_title=res.resource_title,
                    chunk_id=UUID(res.chunk_id),
                    content=res.content,
                    relevance_score=res.vector_score,
                    confidence=res.rrf_score, # Use RRF score as confidence
                    source_metadata={
                        "bm25": res.bm25_score,
                        "rank": res.rank
                    }
                ))

        return results

    def _fuse_and_rank_results(
        self,
        results: List[RetrievalResult],
        top_k: int = 10
    ) -> List[FusedResult]:
        """
        Fuse results from multiple documents and re-rank.

        Uses multi-factor scoring:
        - Relevance score (40%)
        - Confidence (30%)
        - Source quality (30%)
        """
        fused = []

        for result in results:
            # Calculate source quality boost
            source_type = result.source_metadata.get("type", "text")
            source_boost = 1.0
            if source_type in ["pdf", "paper"]:
                source_boost = 1.2  # Boost academic sources
            elif source_type in ["code"]:
                source_boost = 1.1  # Boost code

            # Calculate final score
            final_score = (
                result.relevance_score * 0.4 +
                result.confidence * 0.3 +
                (source_boost * 0.3)
            )

            fused.append(FusedResult(
                content=result.content,
                doc_id=result.doc_id,
                doc_title=result.doc_title,
                chunk_id=result.chunk_id,
                relevance_score=result.relevance_score,
                confidence=result.confidence,
                final_score=final_score,
                source_url=result.source_metadata.get("url"),
            ))

        # Sort by final score
        fused.sort(key=lambda x: x.final_score, reverse=True)

        # Deduplicate by content (keep highest scored)
        seen_content = set()
        deduplicated = []
        for item in fused:
            content_key = item.content[:200]  # First 200 chars as key
            if content_key not in seen_content:
                seen_content.add(content_key)
                deduplicated.append(item)

        return deduplicated[:top_k]

    async def _generate_response(
        self,
        query: str,
        results: List[FusedResult],
        query_plan: QueryPlan,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> dict:
        """Generate final response with citations using LLM"""

        # Build context from results
        context_parts = []
        for i, result in enumerate(results):
            context_parts.append(
                f"[Source {i+1}: {result.doc_title}]\n{result.content}"
            )

        context = "\n\n---\n\n".join(context_parts)

        # Build prompt based on query type
        if query_plan.query_type == QueryType.COMPARISON:
            system_instruction = "Compare and contrast the information from different sources."
        elif query_plan.query_type == QueryType.SYNTHESIS:
            system_instruction = "Synthesize information across all sources into a coherent answer."
        elif query_plan.query_type == QueryType.SUMMARY:
            system_instruction = "Provide a concise summary based on the sources."
        else:
            system_instruction = "Answer the question based on the provided sources."

        # Format history
        history_text = ""
        if conversation_history:
            history_parts = []
            for msg in conversation_history[-3:]: # Only last 3 for context
                role = "User" if msg["role"] == "user" else "Assistant"
                history_parts.append(f"{role}: {msg['content']}")
            history_text = "Recent Conversation:\n" + "\n".join(history_parts) + "\n\n"

        prompt = f"""You are a helpful research assistant. {system_instruction}

IMPORTANT RULES:
1. ONLY use information from the provided sources.
2. YOU MUST CITE sources using [1], [2], etc. after each sentence or claim that uses information from that source. Example: "The project started in 2023 [1]."
3. If information is not in the sources, say "I don't have information about that".
4. If multiple sources support a claim, cite all of them: [1][2].
5. Be concise but thorough.

{history_text}User Question: {query}

Sources:
{context}

Answer:"""

        # Get tier-optimized parameters
        hw_params = self.ollama_manager.get_generation_params(
            task_type="summary" if query_plan.query_type == QueryType.SUMMARY else "chat"
        )

        llm_metrics = {}
        # Generate response
        try:
            answer, llm_metrics = await self.llm.call(
                prompt,
                max_tokens=hw_params.get("num_predict", 800),
                temperature=hw_params.get("temperature", 0.3),
                options=hw_params # Pass tier-optimized options
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            answer = "I'm sorry, I couldn't generate a response. Please try again."

        # Extract citations
        citations = self._extract_citations(answer, results)

        # Get unique sources
        sources = list(dict.fromkeys([r.doc_title for r in results]))

        # Build source documents list
        source_documents = [r.to_dict() for r in results[:5]]

        # Calculate confidence
        avg_score = sum(r.final_score for r in results) / len(results) if results else 0
        confidence = min(1.0, avg_score * (1 + len(citations) * 0.1))

        return {
            "answer": answer,
            "citations": citations,
            "sources": sources,
            "source_documents": source_documents,
            "confidence": confidence,
            "llm_metrics": llm_metrics
        }

    def _extract_citations(
        self,
        text: str,
        results: List[FusedResult]
    ) -> List[Tuple[int, str, str]]:
        """Extract citation markers from response text"""
        import re

        citations = []
        seen_indices = set()

        # Find all [N] patterns
        pattern = r'\[(\d+)\]'
        matches = re.finditer(pattern, text)

        for match in matches:
            idx = int(match.group(1)) - 1  # Convert to 0-indexed
            if 0 <= idx < len(results) and idx not in seen_indices:
                seen_indices.add(idx)
                result = results[idx]
                citations.append((
                    idx + 1,  # 1-indexed for display
                    result.doc_title,
                    result.source_url or ""
                ))

        return citations

    def _estimate_chunk_confidence(self, chunk: Chunk) -> float:
        """Estimate confidence based on chunk properties"""
        confidence = 0.5  # Base confidence

        # Longer chunks = more context = higher confidence
        if chunk.token_count:
            if chunk.token_count > 200:
                confidence += 0.2
            elif chunk.token_count > 100:
                confidence += 0.1

        # Has section title = more structured = higher confidence
        if chunk.section_title:
            confidence += 0.15

        # Metadata presence
        if chunk.chunk_metadata:
            confidence += 0.1

        return min(1.0, confidence)

    async def _update_access_scores(
        self,
        agents: List[Tuple[UUID, DocumentAgent, float]]
    ):
        """Update access statistics for used documents"""
        try:
            from datetime import datetime

            for doc_id, agent, _ in agents:
                agent.update_access_score()

                # Update in database
                resource = self.db.query(Resource).filter(
                    Resource.id == doc_id
                ).first()

                if resource:
                    resource.access_count = (resource.access_count or 0) + 1
                    resource.last_accessed_at = datetime.utcnow()

            self.db.commit()

        except Exception as e:
            logger.warning(f"Failed to update access scores: {e}")
            self.db.rollback()

    def _empty_response(
        self,
        query: str,
        query_plan: QueryPlan,
        start_time: float
    ) -> MultiAgentResponse:
        """Generate empty response when no documents found"""
        return MultiAgentResponse(
            answer="I couldn't find any relevant documents to answer your question. "
                   "Please make sure documents have been uploaded and processed.",
            citations=[],
            sources=[],
            source_documents=[],
            confidence=0.0,
            execution_time_ms=int((time.time() - start_time) * 1000),
            query_plan=query_plan.to_dict(),
            metrics={"error": "no_documents_found"}
        )


# ============================================================================
# Factory Functions
# ============================================================================

def get_multi_document_agent(db: Session) -> MultiDocumentAgent:
    """Create a MultiDocumentAgent with default dependencies"""
    return MultiDocumentAgent(db=db)
