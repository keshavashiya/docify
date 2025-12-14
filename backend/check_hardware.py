#!/usr/bin/env python3
"""
Hardware detection check - run before starting the backend
"""
from app.services.hardware import HardwareDetector

if __name__ == "__main__":
    detector = HardwareDetector()
    
    print("\n=== Hardware Detection ===")
    print(f"NVIDIA GPU: {detector.has_nvidia_gpu()}")
    print(f"AMD GPU: {detector.has_amd_gpu()}")
    print(f"Metal (macOS): {detector.has_metal_support()}")
    print(f"Has GPU: {detector.has_gpu()}")
    print(f"Available Memory: {detector.get_available_memory()}GB")
    print(f"\nOptimal Model: {detector.get_optimal_model()}")
    print(f"Ollama Options: {detector.get_ollama_options()}")
    print("\n")
