"""
Pydantic schemas for Search
"""
from pydantic import BaseModel, UUID4, Field
from typing import Optional, List, Dict
from datetime import datetime


class SearchResult(BaseModel):
    """Individual search result (chunk)"""
    chunk_id: UUID4
    resource_id: UUID4
    resource_title: str
    content: str = Field(..., description="Chunk content")
    score: float = Field(..., ge=0, le=1, description="Relevance score (0-1)")
    source_info: Dict = Field(default_factory=dict)
    search_components: Dict = Field(default_factory=dict)
    
    # Reranking fields (populated after reranking)
    final_score: Optional[float] = Field(None, ge=0, le=1, description="Final score after reranking")
    rerank_scores: Dict = Field(default_factory=dict, description="Breakdown of reranking factors")
    conflicts: List[UUID4] = Field(default_factory=list, description="IDs of conflicting results")
    conflict_count: int = Field(default=0, description="Number of conflicts")

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    """Search request"""
    query: str = Field(..., min_length=1, max_length=1000)
    workspace_id: UUID4
    search_type: str = Field(default="hybrid", description="semantic, keyword, or hybrid")
    top_k: int = Field(default=20, ge=1, le=100)
    use_query_expansion: bool = Field(default=True)


class ConfidenceMetrics(BaseModel):
    """Confidence metrics for a result"""
    overall: float = Field(..., ge=0, le=1, description="Overall confidence score")
    citation_strength: float = Field(ge=0, le=1, description="How often cited by others")
    recency_strength: float = Field(ge=0, le=1, description="How recent the source is")
    specificity_strength: float = Field(ge=0, le=1, description="How directly it answers query")
    source_quality: float = Field(ge=0, le=1, description="Quality of source document")
    conflict_risk: float = Field(ge=0, le=1, description="Risk due to conflicting sources")
    is_primary: bool = Field(description="Is this a primary source for the query")


class EnhancedSearchResult(SearchResult):
    """Enhanced search result with confidence and explanation"""
    confidence: Optional[ConfidenceMetrics] = Field(None)
    explanation: Optional[str] = Field(None, description="Why this result was ranked this way")


class SearchResponse(BaseModel):
    """Search response"""
    query: str
    total_results: int
    results: List[EnhancedSearchResult]
    execution_time_ms: float = Field(description="Time taken to execute search")
    query_variants: Optional[List[str]] = Field(None, description="Query variants used")
    reranked: bool = Field(default=False, description="Whether results were reranked")
    conflicts_detected: int = Field(default=0, description="Number of conflicts detected")


class QueryExpansionRequest(BaseModel):
    """Query expansion request"""
    query: str = Field(..., min_length=1, max_length=1000)
    max_variants: int = Field(default=4, ge=2, le=10)
    use_llm: bool = Field(default=True)


class QueryExpansionResponse(BaseModel):
    """Query expansion response"""
    original_query: str
    variants: List[str]
    count: int
