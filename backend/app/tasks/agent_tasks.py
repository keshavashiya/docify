"""
Document Agent Celery Tasks
Async tasks for creating and managing document agent metadata
"""
import logging
from typing import Optional
from celery import shared_task

from app.core.database import SessionLocal
from app.models.models import Resource, Chunk, DocumentAgentMetadata
from app.services.document_agent import extract_keywords

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def create_document_agent_metadata(self, resource_id: str) -> dict:
    """
    Async task: Extract keywords and create agent metadata for a resource.

    This task is triggered after a resource is uploaded and chunks are created.
    It extracts keywords from the content for fast relevance scoring.

    Args:
        resource_id: UUID string of the resource

    Returns:
        Dict with status and metadata info
    """
    logger.info(f"Creating document agent metadata for resource {resource_id}")

    db = SessionLocal()
    try:
        # Load resource
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            logger.error(f"Resource {resource_id} not found")
            return {"status": "error", "message": "Resource not found"}

        # Check if metadata already exists
        existing_meta = db.query(DocumentAgentMetadata).filter(
            DocumentAgentMetadata.resource_id == resource_id
        ).first()

        if existing_meta and existing_meta.vector_index_status == "ready":
            logger.info(f"Agent metadata already exists for {resource_id}")
            return {"status": "exists", "resource_id": resource_id}

        # Load chunks for keyword extraction
        chunks = db.query(Chunk).filter(Chunk.resource_id == resource_id).all()
        if not chunks:
            logger.warning(f"No chunks found for resource {resource_id}")
            return {"status": "error", "message": "No chunks found"}

        # Extract keywords from content
        # Use first 10 chunks to keep extraction fast
        sample_content = " ".join(chunk.content for chunk in chunks[:10])
        keywords = extract_keywords(sample_content, max_keywords=20)

        # Calculate stats
        total_chunks = len(chunks)
        avg_chunk_size = sum(len(c.content) for c in chunks) // total_chunks if total_chunks > 0 else 0

        # Create or update metadata
        if existing_meta:
            existing_meta.keywords = keywords
            existing_meta.total_chunks = total_chunks
            existing_meta.avg_chunk_size = avg_chunk_size
            existing_meta.doc_type = resource.resource_type
            existing_meta.vector_index_status = "ready"
            existing_meta.keyword_index_status = "ready"
        else:
            agent_meta = DocumentAgentMetadata(
                resource_id=resource.id,
                content_hash=resource.content_hash,
                keywords=keywords,
                total_chunks=total_chunks,
                avg_chunk_size=avg_chunk_size,
                doc_type=resource.resource_type,
                vector_index_status="ready",
                keyword_index_status="ready",
                summary_index_status="pending",  # Summary generation is optional
            )
            db.add(agent_meta)

        # Also cache keywords in resource for quick access
        resource.relevance_keywords = keywords

        db.commit()

        logger.info(f"Created agent metadata for {resource_id}: {len(keywords)} keywords extracted")

        return {
            "status": "success",
            "resource_id": resource_id,
            "keywords_count": len(keywords),
            "chunks_count": total_chunks,
        }

    except Exception as e:
        logger.error(f"Error creating agent metadata for {resource_id}: {e}")
        db.rollback()

        # Retry on transient errors
        try:
            self.retry(countdown=30)
        except self.MaxRetriesExceededError:
            return {"status": "error", "message": str(e)}

    finally:
        db.close()


@shared_task
def update_access_stats(resource_id: str) -> dict:
    """
    Update document access statistics.
    Called when a document is used in a query response.

    Args:
        resource_id: UUID string of the resource

    Returns:
        Dict with updated stats
    """
    from datetime import datetime

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if resource:
            resource.access_count = (resource.access_count or 0) + 1
            resource.last_accessed_at = datetime.utcnow()
            db.commit()

            return {
                "status": "success",
                "resource_id": resource_id,
                "access_count": resource.access_count,
            }

        return {"status": "error", "message": "Resource not found"}

    except Exception as e:
        logger.error(f"Error updating access stats for {resource_id}: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        db.close()
