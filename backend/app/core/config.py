"""
Configuration management using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings"""

    # Application
    APP_NAME: str = "Docify"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = True

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Database (use env var if available)
    DATABASE_URL: str = "postgresql://docify:docify@postgres:5432/docify"

    # Redis (use env var if available)
    REDIS_URL: str = "redis://redis:6379/0"

    # Embeddings (via Ollama - nomic-embed-text for M-series Macs)
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSION: int = 768
    BATCH_SIZE: int = 4

    # LLM
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    DEFAULT_MODEL: str = "mistral"

    # Hardware Detection
    ENABLE_GPU: str = "auto"  # auto, true, false
    FORCE_CPU: bool = False   # Force CPU-only mode

    # Optional Cloud LLM
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # File Upload
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    UPLOAD_DIR: str = "./uploads"

    # Chunking
    DEFAULT_CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    class Config:
        env_file = ".env"
        case_sensitive = True

    def __init__(self, **data):
        """Override init to ensure env vars are respected"""
        super().__init__(**data)
        # Debug: log the Redis URL being used
        import sys
        print(f"[CONFIG] Using REDIS_URL: {self.REDIS_URL}", file=sys.stderr)
        print(f"[CONFIG] Using DATABASE_URL: {self.DATABASE_URL}", file=sys.stderr)


settings = Settings()
