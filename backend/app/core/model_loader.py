"""
Background model loader for Ollama
Downloads models asynchronously on application startup
"""
import logging
import threading
import requests
from typing import List
from app.core.config import settings

logger = logging.getLogger(__name__)

# Track which models are loading
_loading_models = set()
_loaded_models = set()


def load_models_background():
    """Load Ollama models in background thread (non-blocking)"""
    thread = threading.Thread(target=_load_models, daemon=True)
    thread.start()


def _load_models():
    """Download models from Ollama"""
    # nomic-embed-text is required (small, fast)
    # mistral is optional for LLM (large, can be skipped)
    models_to_load = [
        ("nomic-embed-text", True),   # (model_name, is_required)
        ("mistral", False),
    ]
    
    logger.info(f"[MODELS] Starting background download of models")
    
    for model, required in models_to_load:
        if model in _loaded_models:
            logger.info(f"[MODELS] {model} already loaded, skipping")
            continue
        
        _loading_models.add(model)
        requirement = "REQUIRED" if required else "OPTIONAL"
        logger.info(f"[MODELS] Pulling {model} ({requirement})...")
        
        try:
            response = requests.post(
                f"{settings.OLLAMA_BASE_URL}/api/pull",
                json={"name": model, "stream": False},
                timeout=300 if required else 600  # 5 min for embeddings, 10 min for LLM
            )
            
            if response.status_code == 200:
                logger.info(f"[MODELS] ✓ {model} downloaded successfully")
                _loaded_models.add(model)
            else:
                logger.warning(f"[MODELS] ⚠ {model} download returned status {response.status_code}")
                if required:
                    logger.error(f"[MODELS] CRITICAL: Required model {model} failed to download")
                
        except requests.exceptions.Timeout:
            msg = f"[MODELS] ⚠ {model} download timed out"
            if required:
                logger.error(f"{msg} (REQUIRED MODEL)")
            else:
                logger.warning(f"{msg} (optional, will retry later)")
        except Exception as e:
            msg = f"[MODELS] ⚠ {model} download failed: {e}"
            if required:
                logger.error(f"{msg} (REQUIRED MODEL)")
            else:
                logger.warning(msg)
        finally:
            _loading_models.discard(model)
    
    logger.info("[MODELS] Background model loading complete")


def is_model_ready(model_name: str) -> bool:
    """Check if a model is ready to use"""
    return model_name in _loaded_models


def is_model_loading(model_name: str) -> bool:
    """Check if a model is currently downloading"""
    return model_name in _loading_models
