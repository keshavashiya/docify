"""
Pydantic schemas for Chunk
"""
from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional, Dict, List


class ChunkBase(BaseModel):
    """Base chunk schema"""
    content: str = Field(..., description="Chunk text content")
    sequence: int = Field(..., ge=0, description="Sequence number in document")
    section_title: Optional[str] = Field(None, max_length=500, description="Section heading")
    page_number: Optional[int] = Field(None, ge=1, description="Page number if applicable")


class ChunkCreate(ChunkBase):
    """Schema for creating a chunk"""
    resource_id: UUID4 = Field(..., description="Resource this chunk belongs to")
    token_count: Optional[int] = Field(None, ge=0, description="Number of tokens")
    metadata: Dict = Field(default_factory=dict, description="Additional metadata")
    section_level: Optional[int] = Field(None, ge=1, le=6, description="Heading level")


class ChunkResponse(ChunkBase):
    """Schema for chunk response"""
    id: UUID4
    resource_id: UUID4
    token_count: Optional[int]
    section_level: Optional[int]
    metadata: Dict
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkWithEmbedding(ChunkResponse):
    """Schema for chunk with embedding vector"""
    embedding: Optional[List[float]] = Field(None, description="768-dim embedding vector")


class ChunkSearchResult(ChunkResponse):
    """Schema for search result with relevance score"""
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    resource_title: str = Field(..., description="Title of source resource")
