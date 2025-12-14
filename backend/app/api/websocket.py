"""
WebSocket endpoints for real-time message streaming
"""
import json
import logging
import asyncio
from typing import Set
from uuid import UUID
from fastapi import APIRouter, WebSocketDisconnect, WebSocket, Query
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Message, Conversation
from app.core.cache import MessageStreamCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Track active WebSocket connections for each message
active_connections: dict[str, Set[WebSocket]] = {}
stream_cache = MessageStreamCache()


class ConnectionManager:
    """Manage WebSocket connections for a message"""
    
    def __init__(self):
        self.active_connections: dict[str, Set[WebSocket]] = {}
    
    async def connect(self, message_id: str, websocket: WebSocket):
        """Accept WebSocket connection"""
        await websocket.accept()
        if message_id not in self.active_connections:
            self.active_connections[message_id] = set()
        self.active_connections[message_id].add(websocket)
        logger.info(f"Client connected to message {message_id}")
    
    def disconnect(self, message_id: str, websocket: WebSocket):
        """Remove WebSocket connection"""
        if message_id in self.active_connections:
            self.active_connections[message_id].discard(websocket)
            if not self.active_connections[message_id]:
                del self.active_connections[message_id]
        logger.info(f"Client disconnected from message {message_id}")
    
    async def broadcast(self, message_id: str, data: dict):
        """Broadcast to all clients listening to a message"""
        if message_id not in self.active_connections:
            return
        
        disconnected = set()
        for websocket in self.active_connections[message_id]:
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.add(websocket)
        
        # Remove disconnected clients
        for websocket in disconnected:
            self.active_connections[message_id].discard(websocket)


manager = ConnectionManager()


@router.websocket("/messages/{message_id}/stream")
async def websocket_stream_message(
    websocket: WebSocket,
    message_id: str,
    conversation_id: str = Query(...)
):
    """
    WebSocket endpoint to stream message generation updates in real-time.
    
    Client sends nothing, server pushes updates:
    - status updates (pending -> streaming -> complete)
    - tokens as they're generated
    - final response with metrics
    
    Example client usage:
    ```javascript
    const ws = new WebSocket(
        'ws://localhost:8000/ws/messages/{message_id}/stream?conversation_id={conv_id}'
    );
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'token') {
            console.log('Token:', data.token);
        } else if (data.type === 'status') {
            console.log('Status:', data.status);
        }
    };
    ```
    """
    db = SessionLocal()
    
    try:
        # Verify message and conversation exist
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.conversation_id == conversation_id
        ).first()
        
        if not message:
            await websocket.close(code=4004, reason="Message not found")
            return
        
        # Accept connection
        await manager.connect(message_id, websocket)
        
        # Send initial status
        await websocket.send_json({
            "type": "status",
            "status": message.status,
            "content": message.content,
            "timestamp": message.timestamp.isoformat()
        })
        
        # Stream tokens as they arrive
        previous_token_count = 0
        poll_interval = 0.5  # Check every 500ms
        max_wait = 600  # 10 minutes max wait
        elapsed = 0
        
        while elapsed < max_wait:
            # Check current status
            db.refresh(message)
            
            # Get new tokens from cache
            tokens = stream_cache.get_tokens(message_id, previous_token_count)
            for token in tokens:
                await websocket.send_json({
                    "type": "token",
                    "token": token,
                    "token_count": previous_token_count + 1
                })
                previous_token_count += 1
            
            # If complete, send final response and break
            if message.status == "complete":
                await websocket.send_json({
                    "type": "complete",
                    "content": message.content,
                    "sources": [str(s) for s in message.sources] if message.sources else [],
                    "citations": message.citations or {},
                    "tokens_used": message.tokens_used,
                    "generation_time": message.generation_time,
                    "model_used": message.model_used
                })
                break
            
            # If error, send error and break
            if message.status == "error":
                await websocket.send_json({
                    "type": "error",
                    "error": message.error_message or "Unknown error occurred"
                })
                break
            
            # Wait before polling again
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        
        # Send final connection close message
        await websocket.send_json({"type": "close"})
        
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from {message_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except:
            pass
    finally:
        manager.disconnect(message_id, websocket)
        db.close()


@router.websocket("/conversations/{conversation_id}/live")
async def websocket_conversation(
    websocket: WebSocket,
    conversation_id: str
):
    """
    WebSocket endpoint for live conversation updates.
    
    Receives: User messages (auto-queued for generation)
    Sends: New messages, status updates, typing indicators
    
    Example:
    ```javascript
    ws.send(JSON.stringify({
        type: 'message',
        content: 'What is quantum computing?'
    }));
    ```
    """
    db = SessionLocal()
    
    try:
        # Verify conversation exists
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        
        if not conversation:
            await websocket.close(code=4004, reason="Conversation not found")
            return
        
        await websocket.accept()
        logger.info(f"Client connected to conversation {conversation_id}")
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "ready",
            "conversation_id": str(conversation_id)
        })
        
        # Listen for client messages
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "message":
                # This would queue generation like the HTTP endpoint
                logger.info(f"Received message in conversation: {message_data.get('content')}")
                # TODO: Queue message generation like HTTP endpoint
                await websocket.send_json({
                    "type": "ack",
                    "received": True
                })
            
            elif message_data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from conversation {conversation_id}")
    except Exception as e:
        logger.error(f"WebSocket error in conversation: {e}")
    finally:
        db.close()
