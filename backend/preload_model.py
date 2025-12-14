"""
Preload embedding model at container startup
Runs before Celery worker starts to avoid download during first task
"""
import sys
from sentence_transformers import SentenceTransformer
from app.core.config import settings

print(f"[PRELOAD] Starting model download: {settings.EMBEDDING_MODEL}")
print(f"[PRELOAD] Dimension: {settings.EMBEDDING_DIMENSION}")

try:
    model = SentenceTransformer(settings.EMBEDDING_MODEL)
    print(f"[PRELOAD] ✓ Model loaded successfully")
    
    # Test encoding
    test_sentence = "This is a test sentence for embedding"
    embedding = model.encode(test_sentence)
    print(f"[PRELOAD] ✓ Test encoding successful, dimension: {len(embedding)}")
    
    if len(embedding) != settings.EMBEDDING_DIMENSION:
        print(f"[PRELOAD] ⚠ WARNING: Dimension mismatch. Got {len(embedding)}, expected {settings.EMBEDDING_DIMENSION}")
    
    print("[PRELOAD] ✓ Model ready for Celery worker")
    sys.exit(0)
    
except Exception as e:
    print(f"[PRELOAD] ✗ Failed to preload model: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
