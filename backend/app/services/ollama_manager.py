"""
Ollama Manager Service
Hardware-aware LLM configuration and optimization (v2 Phase 3)

Features:
- Automatic hardware detection (GPU/CPU/RAM)
- Optimal model selection based on resources
- Dynamic parameter tuning
- Health monitoring
"""
import logging
import asyncio
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

import httpx

from app.core.config import settings
from app.services.hardware import HardwareDetector

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """Model performance tiers"""
    MINIMAL = "minimal"      # <8GB RAM, CPU only
    STANDARD = "standard"    # 8-16GB RAM, optional GPU
    PERFORMANCE = "performance"  # 16GB+ RAM, GPU


@dataclass
class ModelConfig:
    """Configuration for an Ollama model"""
    name: str
    context_length: int
    num_predict: int
    temperature: float
    top_p: float
    num_thread: Optional[int] = None
    num_gpu: Optional[int] = None

    def to_options(self) -> dict:
        """Convert to Ollama options dict"""
        options = {
            "num_ctx": self.context_length,
            "num_predict": self.num_predict,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if self.num_thread:
            options["num_thread"] = self.num_thread
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        return options


# Model configurations by tier
MODEL_CONFIGS: Dict[ModelTier, ModelConfig] = {
    ModelTier.MINIMAL: ModelConfig(
        name="mistral:7b-instruct-q4_0",  # Quantized for low memory
        context_length=2048,
        num_predict=512,
        temperature=0.3,
        top_p=0.9,
        num_thread=4,
        num_gpu=0  # CPU only
    ),
    ModelTier.STANDARD: ModelConfig(
        name="mistral:7b-instruct-q4_K_M",
        context_length=4096,
        num_predict=1000,
        temperature=0.3,
        top_p=0.9,
        num_thread=None,  # Auto
        num_gpu=None  # Auto
    ),
    ModelTier.PERFORMANCE: ModelConfig(
        name="mistral:7b-instruct",  # Full precision
        context_length=8192,
        num_predict=2000,
        temperature=0.3,
        top_p=0.9,
        num_thread=None,
        num_gpu=None  # Use all available
    ),
}


@dataclass
class OllamaStatus:
    """Status of Ollama service"""
    available: bool
    version: Optional[str] = None
    models: List[str] = None
    active_model: Optional[str] = None
    gpu_available: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "version": self.version,
            "models": self.models or [],
            "active_model": self.active_model,
            "gpu_available": self.gpu_available,
            "error": self.error,
        }


class OllamaManager:
    """
    Manages Ollama LLM with hardware-aware optimization.

    Features:
    - Auto-selects optimal model based on system resources
    - Monitors Ollama health and availability
    - Provides hardware-tuned parameters
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        hardware_detector: Optional[HardwareDetector] = None
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.hardware = hardware_detector or HardwareDetector()
        self._tier: Optional[ModelTier] = None
        self._config: Optional[ModelConfig] = None
        self._status_cache: Optional[OllamaStatus] = None
        self._status_cache_time: float = 0

    def detect_tier(self) -> ModelTier:
        """Detect optimal model tier based on hardware"""
        if self._tier:
            return self._tier

        info = self.hardware.get_system_info()
        ram_gb = info.get("ram_total_gb", 8)
        has_gpu = info.get("has_gpu", False)

        if ram_gb >= 16 and has_gpu:
            self._tier = ModelTier.PERFORMANCE
        elif ram_gb >= 8:
            self._tier = ModelTier.STANDARD
        else:
            self._tier = ModelTier.MINIMAL

        logger.info(f"Detected model tier: {self._tier.value} "
                   f"(RAM: {ram_gb}GB, GPU: {has_gpu})")

        return self._tier

    def get_config(self) -> ModelConfig:
        """Get optimal model configuration for this system"""
        if self._config:
            return self._config

        tier = self.detect_tier()
        self._config = MODEL_CONFIGS[tier]

        # Override with hardware-specific settings
        info = self.hardware.get_system_info()

        if tier == ModelTier.MINIMAL:
            # Use fewer threads on low-end systems
            self._config.num_thread = min(4, info.get("cpu_cores", 4))

        logger.info(f"Model config: {self._config.name}, "
                   f"context: {self._config.context_length}")

        return self._config

    def get_generation_params(
        self,
        task_type: str = "chat"
    ) -> dict:
        """
        Get optimal generation parameters for a task type.

        Args:
            task_type: Type of task (chat, summary, analysis, code)

        Returns:
            Dict of Ollama generation parameters
        """
        config = self.get_config()
        params = config.to_options()

        # Task-specific overrides
        if task_type == "summary":
            params["temperature"] = 0.2
            params["num_predict"] = min(params["num_predict"], 500)
        elif task_type == "analysis":
            params["temperature"] = 0.1
            params["num_predict"] = min(params["num_predict"], 1500)
        elif task_type == "code":
            params["temperature"] = 0.1
            params["top_p"] = 0.95

        return params

    async def get_status(self, use_cache: bool = True) -> OllamaStatus:
        """
        Get Ollama service status.

        Args:
            use_cache: Use cached status if recent (< 30s)

        Returns:
            OllamaStatus with availability and model info
        """
        import time

        # Check cache
        if use_cache and self._status_cache:
            if time.time() - self._status_cache_time < 30:
                return self._status_cache

        status = OllamaStatus(available=False)

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                # Check version
                response = await client.get(f"{self.base_url}/api/version")
                if response.status_code == 200:
                    status.available = True
                    status.version = response.json().get("version")

                # List models
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    status.models = [m["name"] for m in models]

                    # Check for our preferred model
                    config = self.get_config()
                    if any(config.name in m for m in status.models):
                        status.active_model = config.name
                    elif status.models:
                        status.active_model = status.models[0]

                # Check GPU
                status.gpu_available = self.hardware.has_gpu()

        except httpx.ConnectError:
            status.error = "Cannot connect to Ollama. Is it running?"
        except Exception as e:
            status.error = str(e)

        # Cache result
        self._status_cache = status
        self._status_cache_time = time.time()

        return status

    async def ensure_model(self, model_name: Optional[str] = None) -> bool:
        """
        Ensure the required model is available in Ollama.

        Args:
            model_name: Model to check/pull, or use optimal config

        Returns:
            True if model is available
        """
        model = model_name or self.get_config().name

        status = await self.get_status(use_cache=False)
        if not status.available:
            logger.error("Ollama not available")
            return False

        # Check if model exists
        if status.models and any(model in m for m in status.models):
            logger.info(f"Model {model} is available")
            return True

        # Pull model
        logger.info(f"Pulling model {model}...")
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": model},
                    timeout=None  # No timeout for pull
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to pull model: {e}")
            return False

    async def warmup(self) -> bool:
        """
        Warmup the model by sending a simple prompt.

        This loads the model into memory for faster first response.
        """
        config = self.get_config()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": config.name,
                        "prompt": "Hello",
                        "options": {"num_predict": 1},
                    }
                )
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Model warmup failed: {e}")
            return False

    def get_embedding_model(self) -> str:
        """Get recommended embedding model"""
        tier = self.detect_tier()

        if tier == ModelTier.MINIMAL:
            return "all-minilm:22m"  # Smallest, fast
        elif tier == ModelTier.STANDARD:
            return "nomic-embed-text"  # Good balance
        else:
            return "nomic-embed-text"  # Best quality


# Singleton instance
_ollama_manager: Optional[OllamaManager] = None


def get_ollama_manager() -> OllamaManager:
    """Get or create Ollama manager singleton"""
    global _ollama_manager
    if _ollama_manager is None:
        _ollama_manager = OllamaManager()
    return _ollama_manager
