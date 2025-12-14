"""
Pydantic schemas for Conversation and Message
"""
from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional, List, Dict


class MessageBase(BaseModel):
    """Base message schema"""
    role: str = Field(..., pattern="^(user|assistant)$", description="Message role")
    content: str = Field(..., min_length=1, description="Message content")


class MessageCreate(MessageBase):
    """Schema for creating a message"""
    conversation_id: UUID4 = Field(..., description="Conversation this message belongs to")


class MessageResponse(MessageBase):
    """Schema for message response"""
    id: UUID4
    conversation_id: UUID4
    timestamp: datetime
    sources: List[UUID4] = Field(default_factory=list, description="Source resource IDs")
    citations: Dict = Field(default_factory=dict, description="Citation details")
    tokens_used: Optional[int]
    generation_time: Optional[int]
    model_used: Optional[str]

    class Config:
        from_attributes = True


class ConversationBase(BaseModel):
    """Base conversation schema"""
    title: Optional[str] = Field(None, max_length=500, description="Conversation title")
    topic: Optional[str] = Field(None, max_length=200, description="Main topic")


class ConversationCreate(ConversationBase):
    """Schema for creating a conversation"""
    workspace_id: UUID4 = Field(..., description="Workspace this conversation belongs to")


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation"""
    title: Optional[str] = Field(None, max_length=500)
    topic: Optional[str] = Field(None, max_length=200)


class ConversationResponse(ConversationBase):
    """Schema for conversation response"""
    id: UUID4
    workspace_id: UUID4
    created_at: datetime
    updated_at: datetime
    entities: List[str] = Field(default_factory=list)
    message_count: int
    token_usage: int

    class Config:
        from_attributes = True


class ConversationWithMessages(ConversationResponse):
    """Schema for conversation with messages"""
    messages: List[MessageResponse] = Field(default_factory=list)
