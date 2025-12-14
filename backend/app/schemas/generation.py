"""
Pydantic schemas for Message Generation
"""
from pydantic import BaseModel, UUID4, Field
from typing import Optional, List, Dict
from datetime import datetime


class GenerationMetricsResponse(BaseModel):
    """Metrics from message generation"""
    search_time_ms: int = Field(default=0)
    rerank_time_ms: int = Field(default=0)
    context_time_ms: int = Field(default=0)
    prompt_time_ms: int = Field(default=0)
    llm_time_ms: int = Field(default=0)
    verification_time_ms: int = Field(default=0)
    total_time_ms: int = Field(default=0)
    tokens_used: int = Field(default=0)
    sources_used: int = Field(default=0)
    model_used: str = Field(default="")


class ContextSummaryResponse(BaseModel):
    """Summary of context used for generation"""
    primary_sources: int = Field(default=0)
    supporting_sources: int = Field(default=0)
    unique_documents: int = Field(default=0)
    related_documents: int = Field(default=0)
    total_tokens: int = Field(default=0)
    has_conflicts: bool = Field(default=False)


class GeneratedMessageResponse(BaseModel):
    """Response from message generation"""
    message_id: Optional[UUID4] = Field(None, description="ID of the created message")
    content: str = Field(default="", description="Generated response text")
    sources: List[UUID4] = Field(default_factory=list, description="Source resource IDs")
    citations: Dict = Field(default_factory=dict, description="Citation verification details")
    metrics: Optional[GenerationMetricsResponse] = None
    context_summary: Optional[ContextSummaryResponse] = None
    warnings: List[str] = Field(default_factory=list)
    status: str = Field(default="complete", description="Status of message (pending, streaming, complete, error)")
    
    class Config:
        from_attributes = True


class MessageStatusResponse(BaseModel):
    """Response with message status (for async polling)"""
    message_id: UUID4
    status: str = Field(..., description="pending, streaming, complete, error")
    content: str = Field(default="", description="Partial or complete content")
    generation_task_id: Optional[str] = Field(None, description="Celery task ID")
    sources: List[UUID4] = Field(default_factory=list)
    citations: Dict = Field(default_factory=dict)
    tokens_used: Optional[int] = None
    generation_time: Optional[int] = None
    model_used: Optional[str] = None
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class MessageStreamResponse(BaseModel):
    """Streaming response for WebSocket"""
    message_id: UUID4
    token: str = Field(..., description="Generated token")
    is_final: bool = Field(default=False)
    token_count: Optional[int] = Field(None, description="Total tokens generated so far")


class GenerateMessageRequest(BaseModel):
    """Request for message generation"""
    query: str = Field(..., min_length=1, max_length=2000, description="User's question")
    workspace_id: UUID4 = Field(..., description="Workspace to search in")
    conversation_id: Optional[UUID4] = Field(None, description="Conversation to add message to")
    prompt_type: str = Field(default="qa", description="Type of prompt (qa, summary, compare, extract)")
    max_context_tokens: int = Field(default=4000, ge=500, le=16000)
    top_k: int = Field(default=20, ge=1, le=100)
    llm_max_tokens: int = Field(default=1500, ge=100, le=4000)
    temperature: float = Field(default=0.3, ge=0, le=1)
    provider: str = Field(default="ollama", description="LLM provider")
    model: Optional[str] = Field(None, description="Specific model to use")
    verify_citations: bool = Field(default=True, description="Whether to verify citations")
    save_message: bool = Field(default=True, description="Whether to save to database")


class RegenerateRequest(BaseModel):
    """Request to regenerate a response"""
    message_id: UUID4 = Field(..., description="Message to regenerate")
    temperature: Optional[float] = Field(None, ge=0, le=1)
    model: Optional[str] = Field(None)
    provider: Optional[str] = Field(None)


class PipelineStats(BaseModel):
    """Statistics about the generation pipeline"""
    services: Dict[str, str] = Field(default_factory=dict)
    defaults: Dict[str, int | float] = Field(default_factory=dict)


class StreamChunk(BaseModel):
    """A chunk of streamed response (for future streaming support)"""
    content: str
    is_final: bool = False
    sources: Optional[List[UUID4]] = None
    metrics: Optional[GenerationMetricsResponse] = None
