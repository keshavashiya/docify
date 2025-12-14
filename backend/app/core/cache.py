"""
Redis cache client for real-time updates and message streaming
"""
import redis
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client() -> redis.Redis:
    """Get or create Redis client instance"""
    global _redis_client
    
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30
            )
            # Test connection
            _redis_client.ping()
            logger.info("Redis client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    return _redis_client


def close_redis_client():
    """Close Redis connection"""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
            _redis_client = None
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


class MessageStreamCache:
    """Cache manager for message streaming"""
    
    def __init__(self):
        self.redis = get_redis_client()
        self.ttl = 3600  # 1 hour
    
    def set_status(self, message_id: str, status: str) -> None:
        """Set message status in cache"""
        key = f"msg:{message_id}:status"
        self.redis.setex(key, self.ttl, status)
    
    def get_status(self, message_id: str) -> str:
        """Get message status from cache"""
        key = f"msg:{message_id}:status"
        return self.redis.get(key) or "pending"
    
    def push_token(self, message_id: str, token: str) -> int:
        """Push token to message stream (returns stream length)"""
        key = f"msg:{message_id}:tokens"
        length = self.redis.rpush(key, token)
        self.redis.expire(key, self.ttl)
        return length
    
    def get_tokens(self, message_id: str, start: int = 0, end: int = -1) -> list:
        """Get tokens from message stream"""
        key = f"msg:{message_id}:tokens"
        return self.redis.lrange(key, start, end)
    
    def clear_stream(self, message_id: str) -> None:
        """Clear message stream"""
        key = f"msg:{message_id}:tokens"
        self.redis.delete(key)
    
    def publish_event(self, message_id: str, event_type: str, data: dict) -> int:
        """Publish event to subscribers"""
        channel = f"msg:{message_id}:events"
        import json
        return self.redis.publish(channel, json.dumps({"type": event_type, **data}))
