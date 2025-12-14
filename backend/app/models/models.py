"""
SQLAlchemy models for Docify v2.0
"""
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Boolean, Text, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime
from app.core.database import Base


class Workspace(Base):
    """Workspace model for organizing resources"""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    workspace_type = Column(String(20), default="personal")  # personal, team, hybrid
    created_at = Column(DateTime, default=datetime.utcnow)
    settings = Column(JSONB, default={})

    # Relationships
    resources = relationship("Resource", back_populates="workspace", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="workspace", cascade="all, delete-orphan")


class Resource(Base):
    """Resource model with deduplication support"""
    __tablename__ = "resources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_hash = Column(String(64), unique=True, nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)  # pdf, url, text, etc.
    title = Column(String(500), nullable=False)
    source_url = Column(Text, nullable=True)
    source_path = Column(Text, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed = Column(DateTime, default=datetime.utcnow)

    # Deduplication
    is_duplicate_of = Column(UUID(as_uuid=True), ForeignKey("resources.id"), nullable=True)

    # Metadata
    resource_metadata = Column(JSONB, default={})
    chunks_count = Column(Integer, default=0)
    embedding_status = Column(String(20), default="pending")  # pending, processing, complete, error

    # Workspace
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    tags = Column(ARRAY(Text), default=[])
    notes = Column(Text, nullable=True)

    # Statistics
    query_count = Column(Integer, default=0)
    citation_count = Column(Integer, default=0)

    # Relationships
    workspace = relationship("Workspace", back_populates="resources")
    chunks = relationship("Chunk", back_populates="resource", cascade="all, delete-orphan")
    duplicates = relationship("Resource", remote_side=[id])


class Chunk(Base):
    """Chunk model with embeddings"""
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id = Column(UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)

    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)

    # Structure
    section_title = Column(String(500), nullable=True)
    section_level = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)

    # Context tracking
    previous_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=True)
    next_chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=True)

    # Metadata
    chunk_metadata = Column(JSONB, default={})

    # Embeddings (384 dimensions for all-minilm:22m)
    embedding = Column(Vector(384), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    resource = relationship("Resource", back_populates="chunks")


class Conversation(Base):
    """Conversation model"""
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    title = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topic = Column(String(200), nullable=True)
    entities = Column(ARRAY(Text), default=[])
    message_count = Column(Integer, default=0)
    token_usage = Column(Integer, default=0)

    # Relationships
    workspace = relationship("Workspace", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Message model"""
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user or assistant
    content = Column(Text, nullable=False, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Citations for assistant messages
    sources = Column(ARRAY(UUID(as_uuid=True)), default=[])
    citations = Column(JSONB, default={})
    tokens_used = Column(Integer, nullable=True)
    generation_time = Column(Integer, nullable=True)  # in milliseconds
    model_used = Column(String(50), nullable=True)

    # Async generation tracking (for assistant messages)
    status = Column(String(20), default="pending")  # pending, streaming, complete, error
    generation_task_id = Column(String(200), nullable=True, index=True)  # Celery task ID
    error_message = Column(Text, nullable=True)
    
    # Generation parameters (for async tasks)
    generation_params = Column(JSONB, default={})  # {provider, model, temperature, max_tokens, etc}

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
