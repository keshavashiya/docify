"""
Document Agent Service
Per-document intelligent agents for multi-document RAG (v2)

Each document gets its own agent with:
- Vector index for semantic search
- Keyword index for BM25-style search
- Summary index for quick summarization
- Relevance scoring for query routing
"""
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from uuid import UUID
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.models.models import Resource, Chunk, DocumentAgentMetadata
from app.core.config import settings
from app.services.embeddings import EmbeddingsService, get_embeddings_service

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class DocumentMetadata:
    """Metadata for document relevance scoring"""
    title: str
    content_type: str  # pdf, url, code, text, image
    size: int
    keywords: List[str]
    language: str = "en"
    source_url: Optional[str] = None
    upload_date: Optional[datetime] = None
    access_score: int = 0
    last_accessed: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content_type": self.content_type,
            "size": self.size,
            "keywords": self.keywords[:10] if self.keywords else [],
            "language": self.language,
            "source_url": self.source_url,
            "upload_date": self.upload_date.isoformat() if self.upload_date else None,
            "access_score": self.access_score,
        }


# ============================================================================
# Keyword Extraction
# ============================================================================

def extract_keywords(text: str, max_keywords: int = 20) -> List[str]:
    """
    Extract keywords from text using simple frequency analysis.

    Args:
        text: Document text content
        max_keywords: Maximum number of keywords to extract

    Returns:
        List of keywords sorted by frequency
    """
    if not text:
        return []

    # Normalize text
    text_lower = text.lower()

    # Remove common punctuation but keep word boundaries
    text_cleaned = re.sub(r'[^\w\s]', ' ', text_lower)

    # Split into words
    words = text_cleaned.split()

    # Common English stopwords
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought',
        'used', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
        'we', 'they', 'what', 'which', 'who', 'whom', 'whose', 'where', 'when',
        'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
        'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 'just', 'also', 'now', 'here', 'there', 'then',
        'once', 'if', 'any', 'about', 'into', 'through', 'during', 'before',
        'after', 'above', 'below', 'between', 'under', 'again', 'further',
    }

    # Filter: remove stopwords and short words
    filtered_words = [
        word for word in words
        if word not in stopwords
        and len(word) >= 3
        and not word.isdigit()
    ]

    # Count frequencies
    word_counts = Counter(filtered_words)

    # Get top keywords
    top_keywords = [word for word, _ in word_counts.most_common(max_keywords)]

    return top_keywords


def detect_language(text: str) -> str:
    """Simple language detection (defaults to English)"""
    # Could be enhanced with langdetect library if needed
    return "en"


# ============================================================================
# Document Agent
# ============================================================================

class DocumentAgent:
    """
    Intelligent per-document agent with:
    - Relevance scoring for query routing
    - Keyword extraction for fast filtering
    - Access tracking for popularity ranking

    Note: Vector/summary indices are managed by existing Chunk embeddings.
    This agent layer adds document-level intelligence on top.
    """

    def __init__(
        self,
        doc_id: UUID,
        metadata: DocumentMetadata,
        chunks: Optional[List[Chunk]] = None
    ):
        self.doc_id = doc_id
        self.metadata = metadata
        self.chunks = chunks or []

        # Agent state
        self.initialized = len(self.chunks) > 0
        self.last_used = datetime.utcnow()

        # Cached keyword set for fast lookup
        self._keyword_set: Optional[Set[str]] = None

    @property
    def keyword_set(self) -> Set[str]:
        """Lazy-load keyword set for fast matching"""
        if self._keyword_set is None:
            self._keyword_set = set(k.lower() for k in (self.metadata.keywords or []))
        return self._keyword_set

    def get_relevance_score(self, query: str) -> float:
        """
        Calculate relevance score for document to query.

        Uses 4-factor scoring:
        1. Keyword overlap (0-0.4) - most important
        2. Content type match (0-0.2) - query mentions doc type
        3. Recency boost (0-0.2) - newer docs slightly preferred
        4. Popularity (0-0.2) - frequently accessed docs

        Returns:
            Score from 0.0 to 1.0
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # 1. Keyword overlap (0-0.4)
        if self.metadata.keywords:
            overlap = len(query_words & self.keyword_set)
            max_possible = min(len(query_words), len(self.keyword_set))
            keyword_score = 0.4 * (overlap / max(max_possible, 1))
        else:
            # Baseline for docs without keywords yet
            keyword_score = 0.1

        # 2. Content type match (0-0.2)
        type_boost = 0.0
        content_type = (self.metadata.content_type or "").lower()
        if content_type in query_lower:
            type_boost = 0.2
        elif content_type == 'pdf' and any(w in query_lower for w in ['paper', 'document', 'report']):
            type_boost = 0.15
        elif content_type == 'url' and any(w in query_lower for w in ['article', 'page', 'website']):
            type_boost = 0.15
        elif content_type == 'code' and any(w in query_lower for w in ['function', 'class', 'code', 'implementation']):
            type_boost = 0.15

        # 3. Recency boost (0-0.2)
        recency_score = 0.1 # Baseline
        if self.metadata.upload_date:
            days_old = (datetime.utcnow() - self.metadata.upload_date).days
            recency_score = 0.2 * max(0.2, 1 - (days_old / 365))

        # 4. Popularity (0-0.2)
        popularity_score = min(0.2, (self.metadata.access_score or 0) / 100)

        total = keyword_score + type_boost + recency_score + popularity_score
        # Ensure a minimum score of 0.15 if the document belongs to the workspace
        return max(0.15, min(1.0, total))

    def update_access_score(self):
        """Track document usage for ranking"""
        self.metadata.access_score += 1
        self.last_used = datetime.utcnow()
        self.metadata.last_accessed = self.last_used

    def get_chunk_ids(self) -> List[UUID]:
        """Get IDs of chunks for this document"""
        return [chunk.id for chunk in self.chunks]

    def to_dict(self) -> dict:
        """Serialize agent state for caching"""
        return {
            "doc_id": str(self.doc_id),
            "metadata": self.metadata.to_dict(),
            "initialized": self.initialized,
            "last_used": self.last_used.isoformat(),
            "chunk_count": len(self.chunks),
        }


# ============================================================================
# Document Agent Pool
# ============================================================================

class DocumentAgentPool:
    """
    LRU pool of active document agents.
    Prevents memory overload on large document collections.

    Features:
    - Lazy loading: agents created on-demand
    - LRU eviction: oldest agents removed when pool is full
    - Memory efficient: only keeps max_active agents in memory
    """

    def __init__(
        self,
        max_active: int = 20,
        embeddings_service: Optional[EmbeddingsService] = None
    ):
        """
        Initialize agent pool.

        Args:
            max_active: Maximum number of agents to keep in memory
            embeddings_service: Optional embeddings service (uses singleton if not provided)
        """
        self.max_active = max_active
        self.agents: Dict[UUID, DocumentAgent] = {}
        self.access_times: Dict[UUID, datetime] = {}
        self.embeddings_service = embeddings_service or get_embeddings_service()

        logger.info(f"DocumentAgentPool initialized with max_active={max_active}")

    async def get_or_create(
        self,
        doc_id: UUID,
        db: Session
    ) -> DocumentAgent:
        """
        Get agent from pool or create new one.

        Args:
            doc_id: Resource ID to get agent for
            db: Database session

        Returns:
            DocumentAgent for the resource
        """
        # Return if already in pool
        if doc_id in self.agents:
            self.access_times[doc_id] = datetime.utcnow()
            return self.agents[doc_id]

        # Load resource from DB
        resource = db.query(Resource).filter(Resource.id == doc_id).first()
        if not resource:
            raise ValueError(f"Resource {doc_id} not found")

        # Get or create agent metadata
        agent_meta = resource.doc_agent_metadata
        keywords = agent_meta.keywords if agent_meta else []

        # If no keywords cached, extract them
        if not keywords:
            chunks = db.query(Chunk).filter(Chunk.resource_id == doc_id).limit(10).all()
            if chunks:
                content = " ".join(chunk.content for chunk in chunks)
                keywords = extract_keywords(content)

                # Cache keywords in DB
                if agent_meta:
                    agent_meta.keywords = keywords
                    db.commit()

        # Create document metadata
        metadata = DocumentMetadata(
            title=resource.title,
            content_type=resource.resource_type,
            size=resource.file_size or 0,
            keywords=keywords or [],
            language="en",
            source_url=resource.source_url,
            upload_date=resource.created_at,
            access_score=resource.access_count or 0,
            last_accessed=resource.last_accessed_at,
        )

        # Create agent
        agent = DocumentAgent(
            doc_id=doc_id,
            metadata=metadata,
            chunks=[] # Don't load chunks anymore, we use SQL-based retrieval
        )

        # Enforce pool size limit
        if len(self.agents) >= self.max_active:
            self._evict_lru()

        # Add to pool
        self.agents[doc_id] = agent
        self.access_times[doc_id] = datetime.utcnow()

        logger.debug(f"Created agent for document {doc_id}, pool size: {len(self.agents)}")

        return agent

    def get_if_cached(self, doc_id: UUID) -> Optional[DocumentAgent]:
        """Get agent only if already in pool (no DB load)"""
        if doc_id in self.agents:
            self.access_times[doc_id] = datetime.utcnow()
            return self.agents[doc_id]
        return None

    def _evict_lru(self):
        """Remove least recently used agent"""
        if not self.access_times:
            return

        # Find oldest agent
        lru_doc_id = min(self.access_times, key=self.access_times.get)

        # Remove from pool
        del self.agents[lru_doc_id]
        del self.access_times[lru_doc_id]

        logger.debug(f"Evicted agent {lru_doc_id} from pool")

    def clear(self):
        """Clear all agents from pool"""
        self.agents.clear()
        self.access_times.clear()
        logger.info("Agent pool cleared")

    def get_stats(self) -> dict:
        """Get pool statistics"""
        return {
            "active_agents": len(self.agents),
            "max_active": self.max_active,
            "utilization": len(self.agents) / self.max_active if self.max_active > 0 else 0,
            "agents": [
                {
                    "doc_id": str(doc_id),
                    "title": agent.metadata.title,
                    "last_used": self.access_times[doc_id].isoformat(),
                }
                for doc_id, agent in self.agents.items()
            ]
        }


# ============================================================================
# Singleton Pool
# ============================================================================

_agent_pool: Optional[DocumentAgentPool] = None


def get_agent_pool() -> DocumentAgentPool:
    """Get or create the global agent pool singleton"""
    global _agent_pool
    if _agent_pool is None:
        pool_size = getattr(settings, 'DOCUMENT_AGENT_POOL_SIZE', 20)
        _agent_pool = DocumentAgentPool(max_active=pool_size)
    return _agent_pool
