"""
Multi-Agent Query API Endpoint (v2)
New endpoint for multi-document agent queries
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.agent_manager import MultiDocumentAgent, get_multi_document_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["v2-agent"])


# ============================================================================
# Request/Response Models
# ============================================================================

class MultiAgentQueryRequest(BaseModel):
    """Request for multi-agent query"""
    query: str = Field(..., min_length=1, max_length=2000, description="User's question")
    workspace_id: UUID = Field(..., description="Workspace to search in")
    top_k_documents: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Override number of documents to use"
    )
    use_query_planning: bool = Field(
        default=True,
        description="Use LLM for query planning"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What are the main findings about machine learning?",
                "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
                "top_k_documents": 5,
                "use_query_planning": True
            }
        }


class CitationResponse(BaseModel):
    """Citation in response"""
    index: int
    source: str
    url: Optional[str] = None


class SourceDocumentResponse(BaseModel):
    """Source document metadata"""
    content: str
    doc_id: str
    doc_title: str
    chunk_id: str
    relevance_score: float
    final_score: float
    source_url: Optional[str] = None


class QueryPlanResponse(BaseModel):
    """Query plan details"""
    query_type: str
    search_strategy: str
    num_documents_needed: int
    requires_synthesis: bool
    estimated_complexity: int
    confidence: float
    reasoning: Optional[str] = None


class MultiAgentQueryResponse(BaseModel):
    """Response from multi-agent query"""
    answer: str
    citations: list[CitationResponse]
    sources: list[str]
    source_documents: list[SourceDocumentResponse]
    confidence: float
    execution_time_ms: int
    query_plan: Optional[QueryPlanResponse] = None
    metrics: dict = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "answer": "Based on the documents, machine learning involves... [1]",
                "citations": [{"index": 1, "source": "ML Paper.pdf", "url": None}],
                "sources": ["ML Paper.pdf", "Notes.md"],
                "source_documents": [],
                "confidence": 0.85,
                "execution_time_ms": 2500,
                "query_plan": {
                    "query_type": "qa",
                    "search_strategy": "hybrid",
                    "num_documents_needed": 3
                }
            }
        }


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/query", response_model=MultiAgentQueryResponse)
async def multi_agent_query(
    request: MultiAgentQueryRequest,
    db: Session = Depends(get_db)
) -> MultiAgentQueryResponse:
    """
    Query using multi-document agent system (v2).

    This endpoint uses the new multi-document agent architecture for:
    - Intelligent query planning
    - Document selection via relevance scoring
    - Parallel retrieval from multiple documents
    - Result fusion and ranking
    - LLM response generation with citations

    Returns:
        MultiAgentQueryResponse with answer, citations, and metrics
    """
    logger.info(f"Multi-agent query: {request.query[:100]}...")

    try:
        # Get multi-document agent
        agent = get_multi_document_agent(db)

        # Execute query
        response = await agent.query(
            user_query=request.query,
            workspace_id=request.workspace_id,
            top_k_docs=request.top_k_documents,
            use_query_planning=request.use_query_planning
        )

        # Convert to response model
        return MultiAgentQueryResponse(
            answer=response.answer,
            citations=[
                CitationResponse(index=idx, source=src, url=url or None)
                for idx, src, url in response.citations
            ],
            sources=response.sources,
            source_documents=[
                SourceDocumentResponse(**doc) for doc in response.source_documents
            ],
            confidence=response.confidence,
            execution_time_ms=response.execution_time_ms,
            query_plan=QueryPlanResponse(**response.query_plan) if response.query_plan else None,
            metrics=response.metrics
        )

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Query processing failed: {str(e)}"
        )


@router.get("/agent-pool/stats")
async def get_agent_pool_stats(
    db: Session = Depends(get_db)
) -> dict:
    """
    Get statistics about the document agent pool.

    Returns current pool utilization, active agents, and memory usage.
    """
    from app.services.document_agent import get_agent_pool

    pool = get_agent_pool()
    return pool.get_stats()


@router.post("/agent-pool/clear")
async def clear_agent_pool(
    db: Session = Depends(get_db)
) -> dict:
    """
    Clear all agents from the pool.

    Useful for freeing memory or resetting state.
    """
    from app.services.document_agent import get_agent_pool

    pool = get_agent_pool()
    pool.clear()

    return {"status": "cleared", "message": "Agent pool cleared successfully"}
