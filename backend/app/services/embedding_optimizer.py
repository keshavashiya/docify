"""
Embedding Optimizer Service
Redis-based embedding caching and batch optimization (v2 Phase 3)

Features:
- Cache embeddings in Redis with 24h TTL
- Batch embedding generation for efficiency
- Content-hash based cache keys for deduplication
"""
import hashlib
import json
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import settings
from app.services.embeddings import EmbeddingsService, get_embeddings_service

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Statistics about embedding cache usage"""
    hits: int = 0
    misses: int = 0
    total_cached: int = 0
    memory_usage_mb: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class EmbeddingOptimizer:
    """
    Optimizes embedding generation with caching and batching.

    Key optimizations:
    1. Redis caching - avoid recomputing embeddings
    2. Content hashing - detect duplicate content
    3. Batch processing - efficient GPU utilization
    """

    CACHE_PREFIX = "docify:embedding:"
    DEFAULT_TTL = 86400  # 24 hours
    BATCH_SIZE = 8  # Optimal for most hardware

    def __init__(
        self,
        embeddings_service: Optional[EmbeddingsService] = None,
        redis_url: Optional[str] = None
    ):
        self.embeddings = embeddings_service or get_embeddings_service()
        self.redis_url = redis_url or settings.REDIS_URL
        self._redis: Optional[Redis] = None
        self._stats = CacheStats()

    async def get_redis(self) -> Redis:
        """Get or create Redis connection"""
        if self._redis is None:
            try:
                self._redis = await redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                # Test connection
                await self._redis.ping()
                logger.info("Redis connection established for embedding cache")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Caching disabled.")
                self._redis = None
        return self._redis

    def _content_hash(self, text: str) -> str:
        """Generate hash for content-based caching"""
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def _cache_key(self, content_hash: str) -> str:
        """Generate Redis cache key"""
        return f"{self.CACHE_PREFIX}{content_hash}"

    async def get_embedding(
        self,
        text: str,
        use_cache: bool = True
    ) -> Optional[List[float]]:
        """
        Get embedding for text, using cache if available.

        Args:
            text: Text to embed
            use_cache: Whether to use Redis cache

        Returns:
            Embedding vector
        """
        if not text or not text.strip():
            return None

        content_hash = self._content_hash(text)

        # Try cache first
        if use_cache:
            cached = await self._get_cached(content_hash)
            if cached is not None:
                self._stats.hits += 1
                return cached
            self._stats.misses += 1

        # Generate embedding
        embedding = self.embeddings.embed(text)

        # Cache result
        if use_cache and embedding:
            await self._cache_embedding(content_hash, embedding)

        return embedding

    async def get_embeddings_batch(
        self,
        texts: List[str],
        use_cache: bool = True
    ) -> List[Optional[List[float]]]:
        """
        Get embeddings for multiple texts with batch optimization.

        Args:
            texts: List of texts to embed
            use_cache: Whether to use Redis cache

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        texts_to_embed: List[tuple] = []  # (index, text, hash)

        # Check cache for each text
        for i, text in enumerate(texts):
            if not text or not text.strip():
                continue

            content_hash = self._content_hash(text)

            if use_cache:
                cached = await self._get_cached(content_hash)
                if cached is not None:
                    results[i] = cached
                    self._stats.hits += 1
                    continue
                self._stats.misses += 1

            texts_to_embed.append((i, text, content_hash))

        # Batch embed remaining texts
        if texts_to_embed:
            # Process in batches
            for batch_start in range(0, len(texts_to_embed), self.BATCH_SIZE):
                batch = texts_to_embed[batch_start:batch_start + self.BATCH_SIZE]
                batch_texts = [t[1] for t in batch]

                # Generate embeddings
                embeddings = self.embeddings.embed_batch(batch_texts)

                # Store results and cache
                for (idx, text, content_hash), embedding in zip(batch, embeddings):
                    results[idx] = embedding
                    if use_cache and embedding:
                        await self._cache_embedding(content_hash, embedding)

        return results

    async def _get_cached(self, content_hash: str) -> Optional[List[float]]:
        """Get embedding from cache"""
        try:
            redis_client = await self.get_redis()
            if redis_client is None:
                return None

            cached = await redis_client.get(self._cache_key(content_hash))
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache read error: {e}")

        return None

    async def _cache_embedding(
        self,
        content_hash: str,
        embedding: List[float],
        ttl: int = DEFAULT_TTL
    ) -> bool:
        """Store embedding in cache"""
        try:
            redis_client = await self.get_redis()
            if redis_client is None:
                return False

            await redis_client.setex(
                self._cache_key(content_hash),
                ttl,
                json.dumps(embedding)
            )
            return True
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
            return False

    async def get_stats(self) -> CacheStats:
        """Get cache statistics"""
        try:
            redis_client = await self.get_redis()
            if redis_client:
                # Count cached embeddings
                cursor = 0
                total = 0
                while True:
                    cursor, keys = await redis_client.scan(
                        cursor,
                        match=f"{self.CACHE_PREFIX}*",
                        count=100
                    )
                    total += len(keys)
                    if cursor == 0:
                        break

                self._stats.total_cached = total

                # Estimate memory usage (384 dims * 4 bytes * count)
                self._stats.memory_usage_mb = (total * 384 * 4) / (1024 * 1024)

        except Exception as e:
            logger.warning(f"Error getting stats: {e}")

        return self._stats

    async def clear_cache(self) -> int:
        """Clear all cached embeddings"""
        try:
            redis_client = await self.get_redis()
            if redis_client is None:
                return 0

            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor,
                    match=f"{self.CACHE_PREFIX}*",
                    count=100
                )
                if keys:
                    deleted += await redis_client.delete(*keys)
                if cursor == 0:
                    break

            logger.info(f"Cleared {deleted} cached embeddings")
            return deleted

        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return 0

    async def warm_cache(
        self,
        texts: List[str]
    ) -> int:
        """
        Pre-populate cache with common embeddings.

        Args:
            texts: List of texts to pre-embed and cache

        Returns:
            Number of embeddings cached
        """
        embeddings = await self.get_embeddings_batch(texts, use_cache=True)
        return sum(1 for e in embeddings if e is not None)

    async def close(self):
        """Close Redis connection"""
        if self._redis:
            await self._redis.close()
            self._redis = None


# Singleton instance
_embedding_optimizer: Optional[EmbeddingOptimizer] = None


async def get_embedding_optimizer() -> EmbeddingOptimizer:
    """Get or create embedding optimizer singleton"""
    global _embedding_optimizer
    if _embedding_optimizer is None:
        _embedding_optimizer = EmbeddingOptimizer()
    return _embedding_optimizer
