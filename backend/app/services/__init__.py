"""
Services package
"""
from app.services.deduplication import DeduplicationService
from app.services.chunking import ChunkingService
from app.services.llm import LLMService, get_llm_service, call_llm
from app.services.embeddings import EmbeddingsService, get_embeddings_service
from app.services.query_expansion import QueryExpansionService
from app.services.search import SearchService
from app.services.reranking import ReRankingService
from app.services.context_assembly import ContextAssemblyService, AssembledContext
from app.services.prompt_engineering import PromptEngineeringService, PromptType
from app.services.citation_verification import CitationVerificationService, VerificationResult
from app.services.message_generation import MessageGenerationService, GeneratedMessage
from app.services.document_agent import (
    DocumentAgent,
    DocumentAgentPool,
    DocumentMetadata,
    get_agent_pool,
    extract_keywords
)
from app.services.query_planner import (
    QueryPlanner,
    QueryPlan,
    QueryType,
    SearchStrategy,
    get_query_planner
)
from app.services.agent_manager import (
    MultiDocumentAgent,
    MultiAgentResponse,
    get_multi_document_agent
)
from app.services.adaptive_chunking import (
    AdaptiveChunkingService,
    DocumentType,
    get_adaptive_chunker
)
from app.services.embedding_optimizer import (
    EmbeddingOptimizer,
    get_embedding_optimizer
)
from app.services.hybrid_search import (
    HybridSearchEngine,
    HybridSearchResult,
    get_hybrid_search
)
from app.services.ollama_manager import (
    OllamaManager,
    get_ollama_manager
)

__all__ = [
    "DeduplicationService",
    "ChunkingService",
    "LLMService",
    "get_llm_service",
    "call_llm",
    "EmbeddingsService",
    "get_embeddings_service",
    "QueryExpansionService",
    "SearchService",
    "ReRankingService",
    "ContextAssemblyService",
    "AssembledContext",
    "PromptEngineeringService",
    "PromptType",
    "CitationVerificationService",
    "VerificationResult",
    "MessageGenerationService",
    "GeneratedMessage",
    # Document Agent (v2 Phase 1)
    "DocumentAgent",
    "DocumentAgentPool",
    "DocumentMetadata",
    "get_agent_pool",
    "extract_keywords",
    # Query Planner (v2 Phase 2)
    "QueryPlanner",
    "QueryPlan",
    "QueryType",
    "SearchStrategy",
    "get_query_planner",
    # Multi-Document Agent (v2 Phase 2)
    "MultiDocumentAgent",
    "MultiAgentResponse",
    "get_multi_document_agent",
    # Phase 3 Optimization
    "AdaptiveChunkingService",
    "DocumentType",
    "get_adaptive_chunker",
    "EmbeddingOptimizer",
    "get_embedding_optimizer",
    "HybridSearchEngine",
    "HybridSearchResult",
    "get_hybrid_search",
    "OllamaManager",
    "get_ollama_manager",
]

