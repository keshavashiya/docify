"""
Docify - FastAPI Application Entry Point
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.router_config import include_routers
from app.core.model_loader import load_models_background

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    debug=settings.DEBUG,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
include_routers(app)

# Start background model loading on app startup
@app.on_event("startup")
async def startup_event():
    """Initialize models in background on app startup"""
    logger.info("[APP] Starting Docify")
    logger.info("[APP] Initializing background model loader...")
    load_models_background()
    logger.info("[APP] Background model loader started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
