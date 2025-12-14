"""
Embedding Generation Tasks
Async tasks for generating embeddings for resource chunks
"""
import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.models.models import Resource, Chunk
from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)

# Create a separate engine for Celery workers
# (workers run in separate processes, can't share the main app's engine)
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Get database session for Celery tasks"""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_embeddings_for_resource(self, resource_id: str) -> dict:
    """
    Generate embeddings for all chunks of a resource.
    
    Args:
        resource_id: UUID of the resource
        
    Returns:
        Dict with status and statistics
    """
    from app.services.embeddings import EmbeddingsService
    
    db = get_db()
    
    try:
        logger.info(f"Starting embedding generation for resource {resource_id}")
        
        # Get the resource
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        
        if not resource:
            logger.error(f"Resource {resource_id} not found")
            return {"status": "error", "message": "Resource not found"}
        
        # Update status to processing
        resource.embedding_status = "processing"
        db.commit()
        
        # Get all chunks for this resource
        chunks = db.query(Chunk).filter(
            Chunk.resource_id == resource_id,
            Chunk.embedding.is_(None)  # Only chunks without embeddings
        ).order_by(Chunk.sequence).all()
        
        if not chunks:
            logger.info(f"No chunks need embeddings for resource {resource_id}")
            resource.embedding_status = "complete"
            db.commit()
            return {"status": "complete", "chunks_processed": 0}
        
        logger.info(f"Generating embeddings for {len(chunks)} chunks")
        
        # Initialize embeddings service
        embeddings_service = EmbeddingsService()
        
        # Process in batches
        batch_size = settings.BATCH_SIZE
        processed = 0
        failed = 0
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [chunk.content for chunk in batch]
            
            # Generate embeddings for batch (synchronous)
            embeddings = embeddings_service.embed_batch(texts, batch_size=batch_size)
            
            # Save embeddings to chunks
            for chunk, embedding in zip(batch, embeddings):
                if embedding is not None:
                    chunk.embedding = embedding
                    processed += 1
                else:
                    failed += 1
                    logger.warning(f"Failed to generate embedding for chunk {chunk.id}")
            
            db.commit()
            
            # Update task progress
            progress = (i + len(batch)) / len(chunks) * 100
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": i + len(batch),
                    "total": len(chunks),
                    "percent": progress
                }
            )
            
            logger.info(f"Processed {i + len(batch)}/{len(chunks)} chunks")
        
        # Update resource status
        if failed == 0:
            resource.embedding_status = "complete"
        elif processed > 0:
            resource.embedding_status = "partial"
        else:
            resource.embedding_status = "error"
        
        db.commit()
        
        result = {
            "status": resource.embedding_status,
            "chunks_total": len(chunks),
            "chunks_processed": processed,
            "chunks_failed": failed
        }
        
        logger.info(f"Embedding generation complete for resource {resource_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error generating embeddings for resource {resource_id}: {e}")
        
        # Update resource status
        try:
            resource = db.query(Resource).filter(Resource.id == resource_id).first()
            if resource:
                resource.embedding_status = "error"
                db.commit()
        except Exception:
            pass
        
        # Retry the task
        raise self.retry(exc=e)
        
    finally:
        db.close()


@celery_app.task(bind=True)
def generate_embeddings_batch(self, resource_ids: List[str]) -> dict:
    """
    Generate embeddings for multiple resources.
    
    Args:
        resource_ids: List of resource UUIDs
        
    Returns:
        Dict with results for each resource
    """
    results = {}
    
    for i, resource_id in enumerate(resource_ids):
        try:
            result = generate_embeddings_for_resource.delay(resource_id)
            results[resource_id] = {"task_id": result.id, "status": "queued"}
        except Exception as e:
            results[resource_id] = {"status": "error", "message": str(e)}
        
        # Update progress
        self.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": len(resource_ids)
            }
        )
    
    return results


@celery_app.task
def retry_failed_embeddings() -> dict:
    """
    Retry embedding generation for resources that failed.
    Called periodically by Celery Beat.
    """
    db = get_db()
    
    try:
        # Find resources with failed or pending embeddings
        resources = db.query(Resource).filter(
            Resource.embedding_status.in_(["error", "pending"])
        ).limit(10).all()
        
        if not resources:
            return {"status": "no_work", "message": "No failed embeddings to retry"}
        
        queued = 0
        for resource in resources:
            generate_embeddings_for_resource.delay(str(resource.id))
            queued += 1
        
        return {"status": "queued", "count": queued}
        
    finally:
        db.close()


@celery_app.task
def get_embedding_stats() -> dict:
    """Get statistics about embedding status across all resources."""
    db = get_db()
    
    try:
        from sqlalchemy import func
        
        stats = db.query(
            Resource.embedding_status,
            func.count(Resource.id).label('count')
        ).group_by(Resource.embedding_status).all()
        
        result = {status: count for status, count in stats}
        
        # Count chunks with/without embeddings
        total_chunks = db.query(func.count(Chunk.id)).scalar()
        embedded_chunks = db.query(func.count(Chunk.id)).filter(
            Chunk.embedding.isnot(None)
        ).scalar()
        
        result["chunks_total"] = total_chunks
        result["chunks_embedded"] = embedded_chunks
        result["chunks_pending"] = total_chunks - embedded_chunks
        
        return result
        
    finally:
        db.close()
