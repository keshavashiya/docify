"""
Pydantic schemas for Workspace
"""
from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional, Dict


class WorkspaceBase(BaseModel):
    """Base workspace schema"""
    name: str = Field(..., min_length=1, max_length=200, description="Workspace name")
    workspace_type: str = Field(default="personal", description="Type: personal, team, or hybrid")
    settings: Dict = Field(default_factory=dict, description="Workspace settings")


class WorkspaceCreate(WorkspaceBase):
    """Schema for creating a workspace"""
    pass


class WorkspaceUpdate(BaseModel):
    """Schema for updating a workspace"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    workspace_type: Optional[str] = None
    settings: Optional[Dict] = None


class WorkspaceResponse(WorkspaceBase):
    """Schema for workspace response"""
    id: UUID4
    created_at: datetime

    class Config:
        from_attributes = True
