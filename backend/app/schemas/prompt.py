"""
Pydantic schemas for Prompt Engineering
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from enum import Enum


class PromptTypeEnum(str, Enum):
    """Types of prompts for different use cases"""
    QA = "qa"
    SUMMARY = "summary"
    COMPARE = "compare"
    EXTRACT = "extract"
    EXPLAIN = "explain"


class PromptRequest(BaseModel):
    """Request for prompt generation"""
    query: str = Field(..., min_length=1, max_length=2000)
    prompt_type: PromptTypeEnum = Field(default=PromptTypeEnum.QA)
    additional_instructions: Optional[str] = Field(None, max_length=500)
    include_history: bool = Field(default=True)


class GeneratedPrompt(BaseModel):
    """A generated prompt ready for LLM"""
    system: str = Field(..., description="System prompt")
    user: str = Field(..., description="User prompt with context")
    prompt_type: str = Field(..., description="Type of prompt used")
    source_count: int = Field(default=0, description="Number of sources in context")
    has_conflicts: bool = Field(default=False, description="Whether sources have conflicts")
    estimated_tokens: int = Field(default=0, description="Estimated token count")


class PromptResponse(BaseModel):
    """Response containing the generated prompt"""
    prompt: GeneratedPrompt
    context_summary: Dict = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    """A message in conversation history"""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class FollowUpPromptRequest(BaseModel):
    """Request for follow-up prompt generation"""
    query: str = Field(..., min_length=1, max_length=2000)
    previous_answer: str = Field(..., description="The previous assistant response")
    conversation_history: List[ConversationMessage] = Field(default_factory=list)
