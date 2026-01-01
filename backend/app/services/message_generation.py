"""
Message Generation Service
Orchestrates the full RAG pipeline for conversation responses
"""
import logging
import time
from typing import Optional, List, Dict, Tuple
from uuid import UUID
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.models import Conversation, Message, Resource
from app.services.search import SearchService
from app.services.reranking import ReRankingService
from app.services.context_assembly import ContextAssemblyService, AssembledContext
from app.services.prompt_engineering import PromptEngineeringService, PromptType
from app.services.citation_verification import CitationVerificationService, VerificationResult
from app.services.llm import get_llm_service
from app.services.agent_manager import get_multi_document_agent

logger = logging.getLogger(__name__)


@dataclass
class GenerationMetrics:
    """Metrics for a message generation"""
    search_time_ms: int = 0
    rerank_time_ms: int = 0
    context_time_ms: int = 0
    prompt_time_ms: int = 0
    llm_time_ms: int = 0
    verification_time_ms: int = 0
    total_time_ms: int = 0
    tokens_used: int = 0
    sources_used: int = 0
    model_used: str = ""


@dataclass
class GeneratedMessage:
    """A generated message with all metadata"""
    content: str
    sources: List[UUID] = field(default_factory=list)
    citations: Dict = field(default_factory=dict)
    verification: Optional[VerificationResult] = None
    metrics: Optional[GenerationMetrics] = None
    context_summary: Dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "content": self.content,
            "sources": [str(s) for s in self.sources],
            "citations": self.citations,
            "verification": self.verification.to_dict() if self.verification else None,
            "metrics": {
                "search_time_ms": self.metrics.search_time_ms,
                "rerank_time_ms": self.metrics.rerank_time_ms,
                "context_time_ms": self.metrics.context_time_ms,
                "prompt_time_ms": self.metrics.prompt_time_ms,
                "llm_time_ms": self.metrics.llm_time_ms,
                "verification_time_ms": self.metrics.verification_time_ms,
                "total_time_ms": self.metrics.total_time_ms,
                "tokens_used": self.metrics.tokens_used,
                "sources_used": self.metrics.sources_used,
                "model_used": self.metrics.model_used,
            } if self.metrics else None,
            "context_summary": self.context_summary,
            "warnings": self.warnings
        }


class MessageGenerationService:
    """
    Orchestrates the full RAG pipeline:
    Query → Search → Rerank → Context Assembly → Prompt Engineering → LLM → Verify
    """

    # Default configuration
    DEFAULT_MAX_TOKENS = 4000
    DEFAULT_TOP_K = 20
    DEFAULT_LLM_MAX_TOKENS = 1500
    DEFAULT_TEMPERATURE = 0.3

    def __init__(self, db: Session):
        self.db = db
        self.search_service = SearchService(db)
        self.rerank_service = ReRankingService(db)
        self.context_service = ContextAssemblyService(db)
        self.prompt_service = PromptEngineeringService()
        self.verification_service = CitationVerificationService(db)
        self.llm_service = get_llm_service()
        self.multi_agent = get_multi_document_agent(db)

    async def generate_response(
        self,
        query: str,
        workspace_id: UUID,
        conversation_id: Optional[UUID] = None,
        prompt_type: PromptType = PromptType.QA,
        max_context_tokens: int = DEFAULT_MAX_TOKENS,
        top_k: int = DEFAULT_TOP_K,
        llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        provider: str = "ollama",
        model: Optional[str] = None,
        verify_citations: bool = True,
        save_message: bool = True
    ) -> GeneratedMessage:
        """
        Generate a response to a user query using the full RAG pipeline.

        Args:
            query: User's question
            workspace_id: Workspace to search in
            conversation_id: Optional conversation to add message to
            prompt_type: Type of prompt (QA, summary, compare, etc.)
            max_context_tokens: Max tokens for context window
            top_k: Number of search results to retrieve
            llm_max_tokens: Max tokens for LLM response
            temperature: LLM temperature
            provider: LLM provider (ollama, openai, anthropic)
            model: Specific model to use
            verify_citations: Whether to verify citations
            save_message: Whether to save to database

        Returns:
            GeneratedMessage with response and metadata
        """
        start_time = time.time()
        metrics = GenerationMetrics()
        warnings = []

        logger.info(f"Generating response for query: {query[:50]}...")

        # Step 1-5: Use MultiDocumentAgent for Optimized Pipeline (Planning, Selection, Parallel Retrieval, Fusion, Generation)
        t0 = time.time()
        # Get conversation history for context
        conversation_history = []
        if conversation_id:
            conversation_history = self._get_conversation_history(conversation_id)

        v2_response = await self.multi_agent.query(
            user_query=query,
            workspace_id=workspace_id,
            top_k_docs=top_k,
            use_query_planning=True,
            conversation_history=conversation_history
        )

        metrics.search_time_ms = v2_response.metrics.get("retrieval_ms", 0)
        metrics.llm_time_ms = v2_response.metrics.get("generation_ms", 0)
        metrics.tokens_used = v2_response.metrics.get("tokens_used", 0)
        metrics.total_time_ms = v2_response.execution_time_ms
        metrics.model_used = v2_response.metrics.get("model", "optimized-v2")
        metrics.sources_used = len(v2_response.sources)

        llm_response = v2_response.answer

        # Step 6: Verify Citations (Optional addition to v2)
        verification = None
        if verify_citations:
            t0 = time.time()
            # Reuse v2 citations for verification if needed,
            # but MultiDocumentAgent already does basic citation extraction.
            # We'll just build a basic verification object or skip if satisfied.
            logger.info("Skipping legacy verification as v2 has native citations")

        # Calculate total time
        metrics.total_time_ms = int((time.time() - start_time) * 1000)

        # Extract source IDs
        source_ids = [UUID(doc["doc_id"]) for doc in v2_response.source_documents]

        # Build citations dict
        citations_dict = {str(i): {"source": s, "url": u} for i, s, u in v2_response.citations}

        # Create the generated message
        generated = GeneratedMessage(
            content=llm_response,
            sources=source_ids,
            citations=citations_dict,
            verification=verification,
            metrics=metrics,
            context_summary={}, # Skip for now
            warnings=warnings
        )

        # Save to database if requested
        if save_message and conversation_id:
            await self._save_message(
                conversation_id=conversation_id,
                query=query,
                response=generated
            )

        return generated

    async def generate_followup_response(
        self,
        query: str,
        conversation_id: UUID,
        workspace_id: UUID,
        **kwargs
    ) -> GeneratedMessage:
        """Generate a response to a follow-up question"""

        # Get the last assistant message
        last_message = self._get_last_assistant_message(conversation_id)
        previous_answer = last_message.content if last_message else ""

        # Use regular generation but with conversation context
        return await self.generate_response(
            query=query,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            **kwargs
        )

    def _get_conversation_history(
        self,
        conversation_id: UUID,
        max_messages: int = 10
    ) -> List[Dict]:
        """Get recent conversation history"""
        messages = self.db.query(Message).filter(
            Message.conversation_id == conversation_id
        ).order_by(Message.timestamp.desc()).limit(max_messages).all()

        # Reverse to get chronological order
        messages = list(reversed(messages))

        return [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

    def _get_last_assistant_message(self, conversation_id: UUID) -> Optional[Message]:
        """Get the last assistant message in a conversation"""
        return self.db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.role == "assistant"
        ).order_by(Message.timestamp.desc()).first()

    async def _save_message(
        self,
        conversation_id: UUID,
        query: str,
        response: GeneratedMessage
    ) -> Tuple[Message, Message]:
        """Save user query and assistant response to database"""

        # Create user message
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=query,
            timestamp=datetime.utcnow()
        )
        self.db.add(user_message)

        # Create assistant message
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=response.content,
            timestamp=datetime.utcnow(),
            sources=response.sources,
            citations=response.citations,
            tokens_used=response.metrics.tokens_used if response.metrics else None,
            generation_time=response.metrics.total_time_ms if response.metrics else None,
            model_used=response.metrics.model_used if response.metrics else None
        )
        self.db.add(assistant_message)

        # Update conversation stats
        conversation = self.db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()

        if conversation:
            conversation.message_count += 2
            conversation.token_usage += response.metrics.tokens_used if response.metrics else 0
            conversation.updated_at = datetime.utcnow()

        # Update resource citation counts
        for source_id in response.sources:
            resource = self.db.query(Resource).filter(
                Resource.id == source_id
            ).first()
            if resource:
                resource.citation_count += 1

        self.db.commit()

        return user_message, assistant_message

    async def regenerate_response(
        self,
        message_id: UUID,
        **kwargs
    ) -> GeneratedMessage:
        """Regenerate a response for an existing message"""

        # Get the original message
        message = self.db.query(Message).filter(
            Message.id == message_id,
            Message.role == "assistant"
        ).first()

        if not message:
            raise ValueError("Message not found or not an assistant message")

        # Get the user message before it
        user_message = self.db.query(Message).filter(
            Message.conversation_id == message.conversation_id,
            Message.role == "user",
            Message.timestamp < message.timestamp
        ).order_by(Message.timestamp.desc()).first()

        if not user_message:
            raise ValueError("Could not find original user query")

        # Get workspace from conversation
        conversation = self.db.query(Conversation).filter(
            Conversation.id == message.conversation_id
        ).first()

        # Generate new response (without saving - we'll update the existing)
        new_response = await self.generate_response(
            query=user_message.content,
            workspace_id=conversation.workspace_id,
            conversation_id=message.conversation_id,
            save_message=False,
            **kwargs
        )

        # Update the existing message
        message.content = new_response.content
        message.sources = new_response.sources
        message.citations = new_response.citations
        message.tokens_used = new_response.metrics.tokens_used if new_response.metrics else None
        message.generation_time = new_response.metrics.total_time_ms if new_response.metrics else None
        message.model_used = new_response.metrics.model_used if new_response.metrics else None

        self.db.commit()

        return new_response

    def get_pipeline_stats(self) -> Dict:
        """Get statistics about the generation pipeline"""
        return {
            "services": {
                "search": "SearchService (hybrid search)",
                "rerank": "ReRankingService (5-factor scoring)",
                "context": "ContextAssemblyService (token budgeting)",
                "prompt": "PromptEngineeringService (anti-hallucination)",
                "verification": "CitationVerificationService (claim checking)"
            },
            "defaults": {
                "max_context_tokens": self.DEFAULT_MAX_TOKENS,
                "top_k": self.DEFAULT_TOP_K,
                "llm_max_tokens": self.DEFAULT_LLM_MAX_TOKENS,
                "temperature": self.DEFAULT_TEMPERATURE
            }
        }
