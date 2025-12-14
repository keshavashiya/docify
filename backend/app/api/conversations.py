"""
Conversation API Endpoints
Full chat functionality with RAG pipeline integration
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.models import Conversation, Message, Workspace
from app.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    ConversationWithMessages,
    MessageResponse
)
from app.schemas.generation import (
    GenerateMessageRequest,
    GeneratedMessageResponse,
    RegenerateRequest,
    PipelineStats,
    MessageStatusResponse
)
from app.services.message_generation import MessageGenerationService
from app.services.prompt_engineering import PromptType
from app.tasks.message_generation import generate_response_async
from app.core.cache import MessageStreamCache

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ============================================================================
# Conversation CRUD Endpoints
# ============================================================================

@router.post("/", response_model=ConversationResponse)
def create_conversation(
    conversation: ConversationCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new conversation.
    
    A conversation belongs to a workspace and contains messages between
    the user and the AI assistant.
    """
    # Verify workspace exists
    workspace = db.query(Workspace).filter(
        Workspace.id == conversation.workspace_id
    ).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    db_conversation = Conversation(
        workspace_id=conversation.workspace_id,
        title=conversation.title,
        topic=conversation.topic
    )
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation


@router.get("/", response_model=List[ConversationResponse])
def list_conversations(
    workspace_id: Optional[UUID] = Query(None, description="Filter by workspace"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List conversations, optionally filtered by workspace.
    
    Returns conversations ordered by most recently updated first.
    """
    query = db.query(Conversation)
    
    if workspace_id:
        query = query.filter(Conversation.workspace_id == workspace_id)
    
    conversations = query.order_by(
        Conversation.updated_at.desc()
    ).offset(skip).limit(limit).all()
    
    return conversations


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
def get_conversation(
    conversation_id: UUID,
    include_messages: bool = Query(True, description="Include message history"),
    db: Session = Depends(get_db)
):
    """
    Get a conversation by ID, optionally with all messages.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return conversation


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: UUID,
    conversation_update: ConversationUpdate,
    db: Session = Depends(get_db)
):
    """
    Update conversation title or topic.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    update_data = conversation_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conversation, field, value)
    
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Delete a conversation and all its messages.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    db.delete(conversation)
    db.commit()
    return {"message": "Conversation deleted successfully"}


# ============================================================================
# Message Endpoints
# ============================================================================

@router.get("/{conversation_id}/messages/{message_id}/status", response_model=MessageStatusResponse)
def get_message_status(
    conversation_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get status of an async message generation.
    
    Use this to poll for updates instead of WebSocket.
    
    Response statuses:
    - pending: Waiting to be processed
    - streaming: Currently generating response
    - complete: Response ready
    - error: Generation failed
    """
    # Verify message exists
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id
    ).first()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    return MessageStatusResponse(
        message_id=message.id,
        status=message.status,
        content=message.content,
        generation_task_id=message.generation_task_id,
        sources=message.sources or [],
        citations=message.citations or {},
        tokens_used=message.tokens_used,
        generation_time=message.generation_time,
        model_used=message.model_used,
        error_message=message.error_message
    )


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
def get_messages(
    conversation_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get messages for a conversation.
    
    Returns messages in chronological order (oldest first).
    """
    # Verify conversation exists
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.timestamp.asc()).offset(skip).limit(limit).all()
    
    return messages


@router.post("/{conversation_id}/messages", response_model=GeneratedMessageResponse, status_code=202)
async def send_message(
    conversation_id: UUID,
    request: GenerateMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Send a message and queue async AI response generation.
    
    Returns immediately with message_id and status=pending.
    The LLM response is generated asynchronously in background.
    
    Client can:
    1. Poll GET /conversations/{id}/messages/{message_id}/status
    2. Use WebSocket for real-time updates
    
    This prevents timeout errors on slow models (CPU-based).
    """
    # Verify conversation exists
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Create user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=request.query,
        timestamp=datetime.utcnow(),
        status="complete"
    )
    db.add(user_message)
    db.flush()
    
    # Create assistant message with pending status
    assistant_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content="",  # Will be filled by async task
        timestamp=datetime.utcnow(),
        status="pending",
        generation_params={
            "provider": request.provider,
            "model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.llm_max_tokens,
            "prompt_type": request.prompt_type,
        }
    )
    db.add(assistant_message)
    db.commit()
    
    conversation.message_count += 1
    db.commit()
    
    # Queue async generation task
    task = generate_response_async.delay(
        message_id=str(assistant_message.id),
        query=request.query,
        workspace_id=str(conversation.workspace_id),
        conversation_id=str(conversation_id),
        prompt_type=request.prompt_type,
        max_context_tokens=request.max_context_tokens,
        top_k=request.top_k,
        llm_max_tokens=request.llm_max_tokens,
        temperature=request.temperature,
        provider=request.provider,
        model=request.model,
        verify_citations=request.verify_citations,
    )
    
    # Store task ID in message
    assistant_message.generation_task_id = task.id
    db.commit()
    
    # Return immediately with pending status
    return GeneratedMessageResponse(
        message_id=assistant_message.id,
        content="",
        sources=[],
        citations={},
        status="pending",
        warnings=["Response is being generated. Poll or use WebSocket to get updates."]
    )


@router.post("/generate", response_model=GeneratedMessageResponse)
async def generate_message(
    request: GenerateMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Generate a response without a specific conversation.
    
    Use this for one-off queries. If conversation_id is provided,
    messages will be saved to that conversation.
    
    If workspace_id is provided without conversation_id, a new
    conversation will NOT be created - messages won't be persisted.
    """
    # Verify workspace exists
    workspace = db.query(Workspace).filter(
        Workspace.id == request.workspace_id
    ).first()
    
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Get prompt type enum
    try:
        prompt_type = PromptType(request.prompt_type)
    except ValueError:
        prompt_type = PromptType.QA
    
    generation_service = MessageGenerationService(db)
    
    try:
        result = await generation_service.generate_response(
            query=request.query,
            workspace_id=request.workspace_id,
            conversation_id=request.conversation_id,
            prompt_type=prompt_type,
            max_context_tokens=request.max_context_tokens,
            top_k=request.top_k,
            llm_max_tokens=request.llm_max_tokens,
            temperature=request.temperature,
            provider=request.provider,
            model=request.model,
            verify_citations=request.verify_citations,
            save_message=request.save_message and request.conversation_id is not None
        )
        
        return GeneratedMessageResponse(
            content=result.content,
            sources=result.sources,
            citations=result.citations,
            metrics={
                "search_time_ms": result.metrics.search_time_ms,
                "rerank_time_ms": result.metrics.rerank_time_ms,
                "context_time_ms": result.metrics.context_time_ms,
                "prompt_time_ms": result.metrics.prompt_time_ms,
                "llm_time_ms": result.metrics.llm_time_ms,
                "verification_time_ms": result.metrics.verification_time_ms,
                "total_time_ms": result.metrics.total_time_ms,
                "tokens_used": result.metrics.tokens_used,
                "sources_used": result.metrics.sources_used,
                "model_used": result.metrics.model_used,
            } if result.metrics else None,
            context_summary=result.context_summary,
            warnings=result.warnings
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating response: {str(e)}"
        )


@router.post("/messages/{message_id}/regenerate", response_model=GeneratedMessageResponse)
async def regenerate_message(
    message_id: UUID,
    request: RegenerateRequest,
    db: Session = Depends(get_db)
):
    """
    Regenerate a response for an existing message.
    
    Useful when the user wants a different response or wants to
    try with different parameters (temperature, model, etc.)
    """
    generation_service = MessageGenerationService(db)
    
    try:
        kwargs = {}
        if request.temperature is not None:
            kwargs['temperature'] = request.temperature
        if request.model is not None:
            kwargs['model'] = request.model
        if request.provider is not None:
            kwargs['provider'] = request.provider
        
        result = await generation_service.regenerate_response(
            message_id=message_id,
            **kwargs
        )
        
        return GeneratedMessageResponse(
            content=result.content,
            sources=result.sources,
            citations=result.citations,
            metrics={
                "search_time_ms": result.metrics.search_time_ms,
                "rerank_time_ms": result.metrics.rerank_time_ms,
                "context_time_ms": result.metrics.context_time_ms,
                "prompt_time_ms": result.metrics.prompt_time_ms,
                "llm_time_ms": result.metrics.llm_time_ms,
                "verification_time_ms": result.metrics.verification_time_ms,
                "total_time_ms": result.metrics.total_time_ms,
                "tokens_used": result.metrics.tokens_used,
                "sources_used": result.metrics.sources_used,
                "model_used": result.metrics.model_used,
            } if result.metrics else None,
            context_summary=result.context_summary,
            warnings=result.warnings
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error regenerating response: {str(e)}"
        )


@router.delete("/{conversation_id}/messages/{message_id}")
def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Delete a specific message from a conversation.
    """
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id
    ).first()
    
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Update conversation message count
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    if conversation:
        conversation.message_count = max(0, conversation.message_count - 1)
    
    db.delete(message)
    db.commit()
    return {"message": "Message deleted successfully"}


# ============================================================================
# Utility Endpoints
# ============================================================================

@router.get("/pipeline/stats", response_model=PipelineStats)
def get_pipeline_stats(db: Session = Depends(get_db)):
    """
    Get information about the RAG pipeline configuration.
    """
    service = MessageGenerationService(db)
    return service.get_pipeline_stats()


@router.get("/{conversation_id}/export")
def export_conversation(
    conversation_id: UUID,
    format: str = Query("json", description="Export format: json or markdown"),
    db: Session = Depends(get_db)
):
    """
    Export a conversation with all messages and citations.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.timestamp.asc()).all()
    
    if format == "markdown":
        # Export as markdown
        md_lines = [
            f"# {conversation.title or 'Conversation'}",
            f"**Topic:** {conversation.topic or 'N/A'}",
            f"**Created:** {conversation.created_at.isoformat()}",
            f"**Messages:** {len(messages)}",
            "",
            "---",
            ""
        ]
        
        for msg in messages:
            role = "**User:**" if msg.role == "user" else "**Assistant:**"
            md_lines.append(role)
            md_lines.append(msg.content)
            
            if msg.role == "assistant" and msg.sources:
                md_lines.append("")
                md_lines.append(f"*Sources: {len(msg.sources)} documents*")
            
            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")
        
        return {"format": "markdown", "content": "\n".join(md_lines)}
    
    else:
        # Export as JSON
        return {
            "format": "json",
            "conversation": {
                "id": str(conversation.id),
                "title": conversation.title,
                "topic": conversation.topic,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "message_count": len(messages)
            },
            "messages": [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "sources": [str(s) for s in msg.sources] if msg.sources else [],
                    "citations": msg.citations,
                    "tokens_used": msg.tokens_used,
                    "model_used": msg.model_used
                }
                for msg in messages
            ]
        }
