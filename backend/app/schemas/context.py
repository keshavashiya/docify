"""
Pydantic schemas for Context Assembly
"""
from pydantic import BaseModel, UUID4, Field
from typing import Optional, List, Dict
from datetime import datetime


class ChunkContext(BaseModel):
    """A chunk included in the assembled context"""
    chunk_id: UUID4
    resource_id: UUID4
    title: str = Field(..., description="Resource title")
    type: str = Field(default="document", description="Resource type")
    content: str = Field(..., description="Chunk content")
    score: float = Field(..., ge=0, le=1, description="Relevance score")
    token_count: int = Field(..., ge=0, description="Estimated token count")
    metadata: Dict = Field(default_factory=dict)
    truncated: bool = Field(default=False, description="Whether content was truncated")

    class Config:
        from_attributes = True


class DocumentMetadata(BaseModel):
    """Metadata for a document in the context"""
    resource_id: UUID4
    title: str
    type: str
    source_url: Optional[str] = None
    created_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    chunks_in_context: int = Field(default=0, description="Number of chunks from this doc")


class RelatedDocument(BaseModel):
    """A related document not in main results"""
    resource_id: UUID4
    title: str
    type: str
    relationship: str = Field(default="shared_tags", description="How it's related")


class AssembledContextResponse(BaseModel):
    """Response containing the assembled context"""
    primary_chunks: List[ChunkContext] = Field(
        default_factory=list,
        description="Most relevant chunks"
    )
    supporting_chunks: List[ChunkContext] = Field(
        default_factory=list,
        description="Additional supporting chunks"
    )
    document_metadata: List[DocumentMetadata] = Field(
        default_factory=list,
        description="Metadata for documents in context"
    )
    related_documents: List[RelatedDocument] = Field(
        default_factory=list,
        description="Related documents not in main results"
    )
    total_tokens: int = Field(default=0, description="Total tokens used")
    source_count: int = Field(default=0, description="Number of unique sources")
    has_conflicts: bool = Field(default=False, description="Whether conflicts detected")
    conflict_summary: Optional[str] = Field(None, description="Summary of conflicts")
    formatted_context: str = Field(
        default="",
        description="Formatted context string for LLM prompt"
    )


class ContextSummary(BaseModel):
    """Summary of assembled context"""
    primary_sources: int = Field(default=0)
    supporting_sources: int = Field(default=0)
    unique_documents: int = Field(default=0)
    related_documents: int = Field(default=0)
    total_tokens: int = Field(default=0)
    has_conflicts: bool = Field(default=False)
    documents: List[Dict] = Field(default_factory=list)


class ContextAssemblyRequest(BaseModel):
    """Request for context assembly"""
    workspace_id: UUID4
    query: str = Field(..., min_length=1, max_length=1000)
    max_tokens: int = Field(default=4000, ge=500, le=16000)
    include_related: bool = Field(default=True)
    deduplicate: bool = Field(default=True)
    search_type: str = Field(default="hybrid")
    top_k: int = Field(default=20, ge=1, le=100)
