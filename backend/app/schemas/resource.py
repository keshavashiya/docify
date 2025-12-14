"""
Pydantic schemas for Resource
"""
from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional, List, Dict


class ResourceBase(BaseModel):
    """Base resource schema"""
    title: str = Field(..., min_length=1, max_length=500, description="Resource title")
    resource_type: str = Field(..., description="Type: pdf, url, text, image, etc.")
    source_url: Optional[str] = Field(None, description="Original URL if applicable")
    tags: List[str] = Field(default_factory=list, description="Tags for organization")
    notes: Optional[str] = Field(None, description="User notes about the resource")


class ResourceCreate(ResourceBase):
    """Schema for creating a resource"""
    workspace_id: UUID4 = Field(..., description="Workspace this resource belongs to")


class ResourceUpdate(BaseModel):
    """Schema for updating a resource"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class ResourceResponse(ResourceBase):
    """Schema for resource response"""
    id: UUID4
    content_hash: str
    file_size: Optional[int]
    created_at: datetime
    last_accessed: datetime
    is_duplicate_of: Optional[UUID4]
    resource_metadata: Dict = Field(default_factory=dict)
    chunks_count: int
    embedding_status: str
    workspace_id: UUID4
    query_count: int
    citation_count: int

    class Config:
        from_attributes = True


class ResourceListResponse(BaseModel):
    """Schema for paginated resource list"""
    resources: List[ResourceResponse]
    total: int
    page: int
    page_size: int
