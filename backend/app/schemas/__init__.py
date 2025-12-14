"""
Pydantic schemas package
"""
from app.schemas.workspace import (
    WorkspaceBase,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse
)
from app.schemas.resource import (
    ResourceBase,
    ResourceCreate,
    ResourceUpdate,
    ResourceResponse,
    ResourceListResponse
)
from app.schemas.chunk import (
    ChunkBase,
    ChunkCreate,
    ChunkResponse,
    ChunkWithEmbedding,
    ChunkSearchResult
)
from app.schemas.conversation import (
    MessageBase,
    MessageCreate,
    MessageResponse,
    ConversationBase,
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationWithMessages
)
from app.schemas.context import (
    ChunkContext,
    DocumentMetadata,
    RelatedDocument,
    AssembledContextResponse,
    ContextSummary,
    ContextAssemblyRequest
)
from app.schemas.prompt import (
    PromptTypeEnum,
    PromptRequest,
    GeneratedPrompt,
    PromptResponse,
    ConversationMessage,
    FollowUpPromptRequest
)
from app.schemas.citation import (
    CitationDetail,
    AccuracyMetrics,
    VerificationResponse,
    VerificationRequest,
    CitationStats
)
from app.schemas.generation import (
    GenerationMetricsResponse,
    ContextSummaryResponse,
    GeneratedMessageResponse,
    GenerateMessageRequest,
    RegenerateRequest,
    PipelineStats
)

__all__ = [
    # Workspace
    "WorkspaceBase",
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceResponse",
    # Resource
    "ResourceBase",
    "ResourceCreate",
    "ResourceUpdate",
    "ResourceResponse",
    "ResourceListResponse",
    # Chunk
    "ChunkBase",
    "ChunkCreate",
    "ChunkResponse",
    "ChunkWithEmbedding",
    "ChunkSearchResult",
    # Conversation & Message
    "MessageBase",
    "MessageCreate",
    "MessageResponse",
    "ConversationBase",
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationResponse",
    "ConversationWithMessages",
    # Context Assembly
    "ChunkContext",
    "DocumentMetadata",
    "RelatedDocument",
    "AssembledContextResponse",
    "ContextSummary",
    "ContextAssemblyRequest",
    # Prompt Engineering
    "PromptTypeEnum",
    "PromptRequest",
    "GeneratedPrompt",
    "PromptResponse",
    "ConversationMessage",
    "FollowUpPromptRequest",
    # Citation Verification
    "CitationDetail",
    "AccuracyMetrics",
    "VerificationResponse",
    "VerificationRequest",
    "CitationStats",
    # Message Generation
    "GenerationMetricsResponse",
    "ContextSummaryResponse",
    "GeneratedMessageResponse",
    "GenerateMessageRequest",
    "RegenerateRequest",
    "PipelineStats",
]
