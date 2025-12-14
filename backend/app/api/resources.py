"""
Resource API Endpoints
Handles resource upload, retrieval, and management
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form, Query
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import os
import shutil
from pathlib import Path

from app.core.database import get_db
from app.core.config import settings
from app.schemas.resource import ResourceResponse, ResourceListResponse
from app.models.models import Resource, Chunk, Workspace
from app.services.parsers import PDFParser, URLParser, DocumentParser
from app.services.deduplication import DeduplicationService
from app.services.chunking import ChunkingService
from app.tasks.embeddings import generate_embeddings_for_resource, get_embedding_stats

router = APIRouter(prefix="/resources", tags=["resources"])


@router.post("/upload", response_model=ResourceResponse)
async def upload_resource(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # Comma-separated
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload and process a resource file

    Supports: PDF, Word (.docx), Excel (.xlsx), Markdown (.md), Text (.txt)
    """

    # Validate file type
    allowed_extensions = {'.pdf', '.docx', '.xlsx', '.md', '.txt'}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )

    # Get or create default workspace
    if workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
    else:
        # Get or create default workspace
        workspace = db.query(Workspace).filter(Workspace.name == "Default").first()
        if not workspace:
            workspace = Workspace(
                id=uuid.uuid4(),
                name="Default",
                workspace_type="personal"
            )
            db.add(workspace)
            db.commit()
            db.refresh(workspace)

    # Save file temporarily
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    temp_file_path = upload_dir / f"{uuid.uuid4()}_{file.filename}"

    try:
        # Save uploaded file
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = temp_file_path.stat().st_size

        # Validate file size
        if file_size > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE / (1024*1024)}MB"
            )

        # Parse based on file type
        if file_ext == '.pdf':
            text = PDFParser.extract_text(str(temp_file_path))
            metadata = PDFParser.extract_metadata(str(temp_file_path))
            resource_type = "pdf"
        elif file_ext == '.docx':
            result = DocumentParser.parse_word(str(temp_file_path))
            text = result["text"]
            metadata = result["metadata"]
            resource_type = "word"
        elif file_ext == '.xlsx':
            result = DocumentParser.parse_excel(str(temp_file_path))
            text = result["text"]
            metadata = result["metadata"]
            resource_type = "excel"
        elif file_ext == '.md':
            result = DocumentParser.parse_markdown(str(temp_file_path))
            text = result["text"]
            metadata = result["metadata"]
            resource_type = "markdown"
        else:  # .txt
            result = DocumentParser.parse_text(str(temp_file_path))
            text = result["text"]
            metadata = result["metadata"]
            resource_type = "text"

        if not text.strip():
            raise HTTPException(status_code=400, detail="No text content found in file")

        # Generate content hash for deduplication
        content_hash = DeduplicationService.generate_content_hash(text)

        # Check for duplicates
        existing = DeduplicationService.check_duplicate(content_hash, db)

        if existing:
            # Duplicate detected - return existing resource (content and embeddings are identical)
            # Ensure title is not empty
            if not existing.title or not existing.title.strip():
                existing.title = metadata.get("title", "").strip() or Path(file.filename).stem or "Untitled"
                db.commit()
            return existing

        # Create new resource with valid title
        title = (metadata.get("title", "").strip() or 
                Path(file.filename).stem or 
                "Untitled")
        # Validate title is not empty
        if not title or not title.strip():
            title = "Untitled"
        
        resource = Resource(
            id=uuid.uuid4(),
            content_hash=content_hash,
            resource_type=resource_type,
            title=title,
            source_path=str(temp_file_path),
            file_size=file_size,
            workspace_id=workspace.id,
            resource_metadata=metadata,
            tags=tags.split(',') if tags else [],
            notes=notes
        )
        db.add(resource)
        db.commit()
        db.refresh(resource)

        # Chunk the content
        chunker = ChunkingService(
            chunk_size=settings.DEFAULT_CHUNK_SIZE,
            overlap=settings.CHUNK_OVERLAP
        )
        chunks = chunker.chunk_text(text, str(resource.id))

        # Save chunks
        for chunk_data in chunks:
            chunk = Chunk(**chunk_data.dict())
            db.add(chunk)

        resource.chunks_count = len(chunks)
        resource.embedding_status = "pending"
        db.commit()
        db.refresh(resource)

        # Trigger async embedding generation
        try:
            task = generate_embeddings_for_resource.delay(str(resource.id))
            resource.resource_metadata = {
                **resource.resource_metadata,
                "embedding_task_id": task.id
            }
            db.commit()
        except Exception as e:
            # Log but don't fail - embeddings can be generated later
            import logging
            logging.warning(f"Failed to queue embedding task: {e}")

        return resource

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
    finally:
        pass
        # Note: We keep the file for now, but in production you might want to
        # move it to permanent storage or delete it after processing

@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(resource_id: str, db: Session = Depends(get_db)):
    """Get a specific resource by ID"""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/", response_model=ResourceListResponse)
def list_resources(
    workspace_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List resources with optional workspace filter"""
    query = db.query(Resource)

    if workspace_id:
        query = query.filter(Resource.workspace_id == workspace_id)

    total = query.count()
    resources = query.offset(skip).limit(limit).all()

    return ResourceListResponse(
        resources=resources,
        total=total,
        page=skip // limit + 1,
        page_size=limit
    )


@router.delete("/{resource_id}")
def delete_resource(resource_id: str, db: Session = Depends(get_db)):
    """Delete a resource and its chunks"""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Delete file if it exists
    if resource.source_path and os.path.exists(resource.source_path):
        try:
            os.remove(resource.source_path)
        except Exception:
            pass  # File deletion is not critical

    db.delete(resource)
    db.commit()

    return {"message": "Resource deleted successfully"}


@router.get("/stats/deduplication")
def get_deduplication_stats(db: Session = Depends(get_db)):
    """Get deduplication statistics"""
    return DeduplicationService.get_deduplication_stats(db)


# ============================================================================
# Embedding Management Endpoints
# ============================================================================

@router.get("/stats/embeddings")
def get_embeddings_stats():
    """
    Get statistics about embedding generation status.
    
    Returns counts of resources by embedding status and chunk statistics.
    """
    try:
        result = get_embedding_stats.delay()
        stats = result.get(timeout=10)
        return stats
    except Exception as e:
        # Fallback to direct query if Celery not available
        from sqlalchemy import func
        from app.core.database import SessionLocal
        
        db = SessionLocal()
        try:
            stats = db.query(
                Resource.embedding_status,
                func.count(Resource.id).label('count')
            ).group_by(Resource.embedding_status).all()
            
            result = {status: count for status, count in stats}
            
            total_chunks = db.query(func.count(Chunk.id)).scalar() or 0
            embedded_chunks = db.query(func.count(Chunk.id)).filter(
                Chunk.embedding.isnot(None)
            ).scalar() or 0
            
            result["chunks_total"] = total_chunks
            result["chunks_embedded"] = embedded_chunks
            result["chunks_pending"] = total_chunks - embedded_chunks
            
            return result
        finally:
            db.close()


@router.get("/{resource_id}/embedding-status")
def get_resource_embedding_status(
    resource_id: str,
    db: Session = Depends(get_db)
):
    """
    Get embedding status for a specific resource.
    
    Returns status, progress, and chunk statistics.
    """
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    # Count chunks
    total_chunks = db.query(Chunk).filter(
        Chunk.resource_id == resource_id
    ).count()
    
    embedded_chunks = db.query(Chunk).filter(
        Chunk.resource_id == resource_id,
        Chunk.embedding.isnot(None)
    ).count()
    
    # Get task ID if available
    task_id = resource.resource_metadata.get("embedding_task_id") if resource.resource_metadata else None
    
    # Check task status if we have a task ID
    task_status = None
    if task_id:
        try:
            from app.core.celery_app import celery_app
            result = celery_app.AsyncResult(task_id)
            task_status = {
                "task_id": task_id,
                "state": result.state,
                "info": result.info if result.state == "PROGRESS" else None
            }
        except Exception:
            pass
    
    return {
        "resource_id": str(resource.id),
        "embedding_status": resource.embedding_status,
        "chunks_total": total_chunks,
        "chunks_embedded": embedded_chunks,
        "chunks_pending": total_chunks - embedded_chunks,
        "progress_percent": (embedded_chunks / total_chunks * 100) if total_chunks > 0 else 0,
        "task": task_status
    }


@router.post("/{resource_id}/generate-embeddings")
def trigger_embedding_generation(
    resource_id: str,
    db: Session = Depends(get_db)
):
    """
    Manually trigger embedding generation for a resource.
    
    Useful for retrying failed embeddings or processing resources
    that were uploaded before Celery was available.
    """
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    # Check if already processing
    if resource.embedding_status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Embedding generation already in progress"
        )
    
    # Queue the task
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Attempting to queue embedding task for resource {resource_id}")
        
        task = generate_embeddings_for_resource.delay(resource_id)
        logger.info(f"Successfully queued task {task.id}")
        
        # Update metadata with task ID
        resource.resource_metadata = {
            **(resource.resource_metadata or {}),
            "embedding_task_id": task.id
        }
        resource.embedding_status = "pending"
        db.commit()
        
        return {
            "message": "Embedding generation queued",
            "task_id": task.id,
            "resource_id": resource_id
        }
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to queue embedding task: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=503,
            detail=f"Failed to queue embedding task: {str(e)}"
        )


@router.post("/generate-embeddings/batch")
def trigger_batch_embedding_generation(
    resource_ids: List[str] = Query(..., description="List of resource IDs"),
    db: Session = Depends(get_db)
):
    """
    Trigger embedding generation for multiple resources.
    """
    results = {}
    
    for resource_id in resource_ids:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            results[resource_id] = {"status": "error", "message": "Resource not found"}
            continue
        
        if resource.embedding_status == "processing":
            results[resource_id] = {"status": "skipped", "message": "Already processing"}
            continue
        
        try:
            task = generate_embeddings_for_resource.delay(resource_id)
            resource.resource_metadata = {
                **(resource.resource_metadata or {}),
                "embedding_task_id": task.id
            }
            resource.embedding_status = "pending"
            results[resource_id] = {"status": "queued", "task_id": task.id}
        except Exception as e:
            results[resource_id] = {"status": "error", "message": str(e)}
    
    db.commit()
    
    return {
        "queued": sum(1 for r in results.values() if r.get("status") == "queued"),
        "skipped": sum(1 for r in results.values() if r.get("status") == "skipped"),
        "errors": sum(1 for r in results.values() if r.get("status") == "error"),
        "details": results
    }


@router.get("/pending-embeddings")
def list_pending_embeddings(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List resources that need embedding generation.
    """
    resources = db.query(Resource).filter(
        Resource.embedding_status.in_(["pending", "error"])
    ).limit(limit).all()
    
    return {
        "count": len(resources),
        "resources": [
            {
                "id": str(r.id),
                "title": r.title,
                "status": r.embedding_status,
                "chunks_count": r.chunks_count
            }
            for r in resources
        ]
    }
