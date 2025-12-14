"""
Router configuration
Centralized router registration
"""
from fastapi import FastAPI
from app.api import health, resources, workspaces, conversations, websocket


def include_routers(app: FastAPI) -> None:
    """
    Include all API routers with /api prefix

    Args:
        app: FastAPI application instance
    """
    # Core routers
    app.include_router(health.router, prefix="/api")
    app.include_router(resources.router, prefix="/api")
    app.include_router(workspaces.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    
    # WebSocket routers (no /api prefix for WebSocket)
    app.include_router(websocket.router)
