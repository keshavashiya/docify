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
        
        # Step 1: Search
        t0 = time.time()
        search_results = await self.search_service.hybrid_search(
            query=query,
            workspace_id=workspace_id,
            top_k=top_k
        )
        metrics.search_time_ms = int((time.time() - t0) * 1000)
        logger.info(f"Search returned {len(search_results)} results in {metrics.search_time_ms}ms")
        
        # Handle no results
        if not search_results:
            no_context_response = self.prompt_service.get_no_context_response(query)
            return GeneratedMessage(
                content=no_context_response,
                warnings=["No relevant documents found for this query"],
                metrics=metrics
            )
        
        # Step 2: Rerank
        t0 = time.time()
        reranked_results = self.rerank_service.rerank(
            results=search_results,
            query=query,
            workspace_id=workspace_id,
            detect_conflicts=True
        )
        metrics.rerank_time_ms = int((time.time() - t0) * 1000)
        logger.info(f"Reranked {len(reranked_results)} results in {metrics.rerank_time_ms}ms")
        
        # Step 3: Assemble Context
        t0 = time.time()
        context = self.context_service.assemble_context(
            results=reranked_results,
            query=query,
            workspace_id=workspace_id,
            max_tokens=max_context_tokens,
            include_related=True,
            deduplicate=True
        )
        metrics.context_time_ms = int((time.time() - t0) * 1000)
        metrics.sources_used = context.source_count
        logger.info(f"Assembled context with {context.source_count} sources in {metrics.context_time_ms}ms")
        
        # Get conversation history if available
        conversation_history = []
        if conversation_id:
            conversation_history = self._get_conversation_history(conversation_id)
        
        # Step 4: Build Prompt
        t0 = time.time()
        prompt = self.prompt_service.build_prompt(
            query=query,
            context=context,
            prompt_type=prompt_type,
            conversation_history=conversation_history
        )
        metrics.prompt_time_ms = int((time.time() - t0) * 1000)
        
        # Add low confidence prefix if needed
        if context.source_count < 3:
            warnings.append("Limited sources available - answer may be incomplete")
        
        # Step 5: Call LLM
        t0 = time.time()
        full_prompt = f"{prompt['system']}\n\n{prompt['user']}"
        
        try:
            llm_response = await self.llm_service.call(
                prompt=full_prompt,
                provider=provider,
                model=model,
                max_tokens=llm_max_tokens,
                temperature=temperature
            )
            metrics.llm_time_ms = int((time.time() - t0) * 1000)
            metrics.model_used = model or self.llm_service.default_model
            metrics.tokens_used = len(full_prompt) // 4 + len(llm_response) // 4  # Estimate
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return GeneratedMessage(
                content=f"I encountered an error generating a response: {str(e)}",
                warnings=["LLM call failed"],
                metrics=metrics
            )
        
        logger.info(f"LLM responded in {metrics.llm_time_ms}ms ({len(llm_response)} chars)")
        
        # Step 6: Verify Citations
        verification = None
        if verify_citations:
            t0 = time.time()
            verification = self.verification_service.verify_response(
                response_text=llm_response,
                context=context,
                strict_mode=True
            )
            metrics.verification_time_ms = int((time.time() - t0) * 1000)
            
            # Add warnings from verification
            if verification.has_hallucinations:
                warnings.extend(verification.hallucination_details[:3])
            if verification.warnings:
                warnings.extend(verification.warnings)
            
            logger.info(
                f"Verification: {verification.verified_count}/{verification.total_claims} verified "
                f"in {metrics.verification_time_ms}ms"
            )
        
        # Calculate total time
        metrics.total_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract source IDs
        source_ids = list(set(
            UUID(c['resource_id']) 
            for c in context.primary_chunks + context.supporting_chunks
            if c.get('resource_id')
        ))
        
        # Build citations dict
        citations_dict = {}
        if verification:
            citations_dict = verification.to_dict()
        
        # Get context summary
        context_summary = self.context_service.get_context_summary(context)
        
        # Create the generated message
        generated = GeneratedMessage(
            content=llm_response,
            sources=source_ids,
            citations=citations_dict,
            verification=verification,
            metrics=metrics,
            context_summary=context_summary,
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
