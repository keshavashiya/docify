"""
Health and system status endpoints
"""
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to Docify API",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }
