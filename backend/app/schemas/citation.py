"""
Pydantic schemas for Citation Verification
"""
from pydantic import BaseModel, UUID4, Field
from typing import Optional, List, Dict


class CitationDetail(BaseModel):
    """Details of a verified citation"""
    citation_id: int = Field(..., description="Source number [Source N]")
    claim: str = Field(..., description="The claim text")
    source: str = Field(..., description="Source document title")
    source_type: str = Field(default="document")
    chunk_id: Optional[UUID4] = None
    resource_id: Optional[UUID4] = None
    page: Optional[int] = None
    section: Optional[str] = None
    verified: bool = Field(default=False)
    overlap_score: float = Field(default=0.0, ge=0, le=1)
    matching_text: Optional[str] = Field(None, description="Best matching text from source")
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class AccuracyMetrics(BaseModel):
    """Accuracy metrics for a response"""
    total_claims: int = Field(default=0)
    verified_claims: int = Field(default=0)
    verification_score: float = Field(default=0.0, ge=0, le=1)
    has_hallucinations: bool = Field(default=False)


class VerificationResponse(BaseModel):
    """Complete verification response"""
    citations: List[CitationDetail] = Field(default_factory=list)
    unverified_claims: List[str] = Field(default_factory=list)
    accuracy_metrics: AccuracyMetrics
    hallucination_details: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    summary: Optional[str] = Field(None, description="Human-readable summary")


class VerificationRequest(BaseModel):
    """Request for citation verification"""
    response_text: str = Field(..., description="The LLM response to verify")
    strict_mode: bool = Field(default=True, description="Flag uncited claims as hallucinations")


class CitationStats(BaseModel):
    """Statistics about citations in a conversation"""
    total_messages: int = Field(default=0)
    total_citations: int = Field(default=0)
    verified_citations: int = Field(default=0)
    average_verification_score: float = Field(default=0.0)
    unique_sources_cited: int = Field(default=0)
    hallucination_incidents: int = Field(default=0)
