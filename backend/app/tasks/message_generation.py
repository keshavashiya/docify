"""
Celery task for async message generation with streaming support
"""
import logging
import json
from typing import Dict, Optional
from uuid import UUID
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Message, Conversation
from app.services.message_generation import MessageGenerationService
from app.services.prompt_engineering import PromptType
from app.core.cache import get_redis_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def generate_response_async(
    self,
    message_id: str,
    query: str,
    workspace_id: str,
    conversation_id: str,
    prompt_type: str = "qa",
    max_context_tokens: int = 4000,
    top_k: int = 20,
    llm_max_tokens: int = 1500,
    temperature: float = 0.3,
    provider: str = "ollama",
    model: Optional[str] = None,
    verify_citations: bool = True,
) -> Dict:
    """
    Async task to generate LLM response and stream updates to client.
    
    This runs in Celery worker and updates the message in real-time.
    Clients can poll or use WebSocket to see updates.
    
    Args:
        message_id: ID of message to update
        query: User's question
        workspace_id: Workspace UUID
        conversation_id: Conversation UUID
        prompt_type: Type of prompt (qa, summary, compare, etc)
        max_context_tokens: Max tokens for context
        top_k: Number of search results
        llm_max_tokens: Max tokens for LLM response
        temperature: LLM temperature
        provider: LLM provider (ollama, openai, anthropic)
        model: Specific model to use
        verify_citations: Whether to verify citations
    
    Returns:
        Dict with result status and summary
    """
    db = SessionLocal()
    redis_client = get_redis_client()
    
    try:
        # Update message status to streaming
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            logger.error(f"Message {message_id} not found")
            return {"status": "error", "error": "Message not found"}
        
        message.status = "streaming"
        message.generation_task_id = self.request.id
        db.commit()
        
        logger.info(f"Starting generation for message {message_id}")
        
        # Initialize message generation service
        generation_service = MessageGenerationService(db)
        
        # Generate response
        result = None
        try:
            import asyncio
            
            # Handle async call in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            result = loop.run_until_complete(
                generation_service.generate_response(
                    query=query,
                    workspace_id=UUID(workspace_id),
                    conversation_id=UUID(conversation_id),
                    prompt_type=PromptType(prompt_type),
                    max_context_tokens=max_context_tokens,
                    top_k=top_k,
                    llm_max_tokens=llm_max_tokens,
                    temperature=temperature,
                    provider=provider,
                    model=model,
                    verify_citations=verify_citations,
                    save_message=False  # We'll save manually
                )
            )
            
            loop.close()
            
        except Exception as e:
            logger.error(f"Error in message generation: {e}")
            raise
        
        # Update message with result
        message.content = result.content
        message.sources = result.sources
        message.citations = result.citations
        message.tokens_used = result.metrics.tokens_used if result.metrics else None
        message.generation_time = result.metrics.total_time_ms if result.metrics else None
        message.model_used = result.metrics.model_used if result.metrics else None
        message.status = "complete"
        message.error_message = None
        
        # Update conversation stats
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if conversation:
            conversation.message_count += 1
            conversation.token_usage += (result.metrics.tokens_used if result.metrics else 0)
        
        db.commit()
        
        # Cache result for WebSocket clients
        cache_key = f"message:{message_id}:result"
        redis_client.setex(
            cache_key,
            3600,  # 1 hour TTL
            json.dumps({
                "status": "complete",
                "content": result.content,
                "sources": [str(s) for s in result.sources],
                "citations": result.citations,
                "metrics": {
                    "tokens_used": result.metrics.tokens_used,
                    "generation_time": result.metrics.total_time_ms,
                    "model_used": result.metrics.model_used,
                } if result.metrics else None
            })
        )
        
        logger.info(f"Successfully generated message {message_id}")
        
        return {
            "status": "success",
            "message_id": message_id,
            "tokens_used": result.metrics.tokens_used if result.metrics else None,
            "generation_time_ms": result.metrics.total_time_ms if result.metrics else None,
        }
        
    except Exception as exc:
        logger.error(f"Task failed for message {message_id}: {exc}")
        
        # Update message with error status
        try:
            message = db.query(Message).filter(Message.id == message_id).first()
            if message:
                message.status = "error"
                message.error_message = str(exc)
                db.commit()
        except:
            pass
        
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        
    finally:
        db.close()


@shared_task
def stream_message_token(
    message_id: str,
    token: str,
    is_final: bool = False
) -> None:
    """
    Stream a single token to WebSocket clients (called during LLM generation).
    
    This stores the token in Redis for subscribers to retrieve.
    
    Args:
        message_id: ID of message being generated
        token: The token to stream
        is_final: Whether this is the final token
    """
    redis_client = get_redis_client()
    
    try:
        # Publish to Redis pub/sub channel
        channel = f"message:{message_id}:stream"
        redis_client.publish(
            channel,
            json.dumps({
                "token": token,
                "is_final": is_final
            })
        )
        
        # Also append to list for polling clients
        stream_key = f"message:{message_id}:tokens"
        redis_client.rpush(stream_key, token)
        redis_client.expire(stream_key, 3600)  # 1 hour TTL
        
    except Exception as e:
        logger.error(f"Error streaming token: {e}")


@shared_task
def update_message_status(
    message_id: str,
    status: str,
    partial_content: Optional[str] = None
) -> None:
    """
    Update message status in database and cache.
    
    Args:
        message_id: ID of message
        status: New status (pending, streaming, complete, error)
        partial_content: Partial response content (for streaming)
    """
    db = SessionLocal()
    redis_client = get_redis_client()
    
    try:
        message = db.query(Message).filter(Message.id == message_id).first()
        if message:
            message.status = status
            if partial_content:
                message.content = partial_content
            db.commit()
        
        # Update cache
        cache_key = f"message:{message_id}:status"
        redis_client.set(
            cache_key,
            json.dumps({"status": status}),
            ex=3600
        )
        
    except Exception as e:
        logger.error(f"Error updating message status: {e}")
    finally:
        db.close()
