"""
Hardware detection service for optimized model selection
"""
import logging
import subprocess
import psutil
import platform
from app.core.config import settings

logger = logging.getLogger(__name__)


class HardwareDetector:
    """Detect GPU and CPU capabilities for optimal model loading"""
    
    @staticmethod
    def has_nvidia_gpu() -> bool:
        """Check if NVIDIA GPU is available"""
        try:
            result = subprocess.run(
                ['nvidia-smi'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def has_amd_gpu() -> bool:
        """Check if AMD GPU is available"""
        try:
            result = subprocess.run(
                ['rocm-smi'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def has_metal_support() -> bool:
        """Check if macOS Metal support is available"""
        if platform.system() != "Darwin":
            return False
        try:
            result = subprocess.run(
                ['sysctl', 'hw.model'],
                capture_output=True,
                timeout=5,
                text=True
            )
            # All Apple Silicon (M1, M2, M3, etc.) supports Metal
            return 'Apple' in result.stdout or 'm1' in result.stdout.lower()
        except Exception:
            return False
    
    @staticmethod
    def get_available_memory() -> int:
        """Get available system memory in GB"""
        return int(psutil.virtual_memory().available / (1024**3))
    
    @staticmethod
    def has_gpu() -> bool:
        """Check if any GPU is available"""
        # Respect FORCE_CPU setting
        if settings.FORCE_CPU:
            logger.info("GPU disabled: FORCE_CPU=true")
            return False
        
        # Check ENABLE_GPU setting
        enable_gpu = settings.ENABLE_GPU.lower()
        if enable_gpu == "false":
            logger.info("GPU disabled: ENABLE_GPU=false")
            return False
        
        # Auto-detect
        has_any_gpu = (
            HardwareDetector.has_nvidia_gpu() or
            HardwareDetector.has_amd_gpu() or
            HardwareDetector.has_metal_support()
        )
        
        if has_any_gpu:
            logger.info("GPU detected and enabled")
        
        return has_any_gpu
    
    @staticmethod
    def get_optimal_model() -> str:
        """
        Get optimal model based on hardware.
        
        Returns:
            Model name to use (e.g., 'mistral:7b-instruct-q4_0' for CPU)
        """
        has_gpu = HardwareDetector.has_gpu()
        memory_gb = HardwareDetector.get_available_memory()
        
        logger.info(f"GPU available: {has_gpu}, Memory: {memory_gb}GB")
        
        if has_gpu:
            # With GPU, use larger model
            return "mistral:7b-instruct"
        
        # CPU only - use quantized small model
        if memory_gb >= 16:
            return "mistral:7b-instruct-q4_0"
        elif memory_gb >= 8:
            return "mistral:7b-instruct-q4_0"
        else:
            return "phi:2.7b"  # Smallest model for low-memory systems
    
    @staticmethod
    def get_ollama_options() -> dict:
        """Get optimized Ollama inference options"""
        has_gpu = HardwareDetector.has_gpu()
        
        base_options = {
            "temperature": 0.3,
            "top_p": 0.9,
        }
        
        if has_gpu:
            # GPU can handle more tokens
            base_options.update({
                "num_predict": 1000,
            })
        else:
            # CPU - reduce tokens for speed
            base_options.update({
                "num_predict": 500,  # Reduce from 1000
                "num_thread": max(1, psutil.cpu_count() - 1),  # Use all but one core
            })
        
        return base_options
