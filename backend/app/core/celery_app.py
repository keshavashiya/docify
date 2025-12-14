"""
Celery Configuration
Async task queue for background jobs (embeddings, processing, etc.)
"""
import sys
import os
from celery import Celery

# Get Redis URL from environment, with fallback
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

print(f"[CELERY] Initializing with REDIS_URL: {redis_url}", file=sys.stderr)

# Create Celery app with explicit Redis URL
celery_app = Celery(
    "docify",
    broker=redis_url,
    backend=redis_url,
    include=["app.tasks.embeddings", "app.tasks.message_generation"]
)

print(f"[CELERY] App created successfully", file=sys.stderr)

# Note: Embedding model is loaded via Ollama (see embeddings.py)
# No local preload needed - embeddings use HTTP calls to Ollama

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completes (safer)
    task_reject_on_worker_lost=True,
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # Soft limit 9 minutes

    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time (for memory-heavy embedding)
    worker_concurrency=1,  # 1 concurrent worker

    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours

    # Task routes (optional - for scaling)
    task_routes={
        "app.tasks.embeddings.*": {"queue": "embeddings"},
    },

    # Default queue
    task_default_queue="default",
)

# Optional: Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    # Example: Re-embed failed resources every hour
    # "retry-failed-embeddings": {
    #     "task": "app.tasks.embeddings.retry_failed_embeddings",
    #     "schedule": 3600.0,  # Every hour
    # },
}
