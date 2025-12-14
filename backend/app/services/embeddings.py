"""
Embeddings Service
Generates vector embeddings using Ollama (optimized for M-series Macs)
"""
import logging
from typing import List, Optional
import numpy as np
import httpx
import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingsService:
    """Service for generating and managing embeddings via Ollama"""

    def __init__(self):
        """Initialize embeddings service with Ollama backend"""
        self.ollama_url = settings.OLLAMA_BASE_URL
        self.model_name = "all-minilm:22m"  # Fast, lightweight embeddings
        self.embedding_dimension = 384  # all-minilm:22m dimension
        
        logger.info(f"Embeddings Service initialized with Ollama at {self.ollama_url}")
        logger.info(f"Using model: {self.model_name}")

    def embed(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text via Ollama (synchronous).

        Args:
            text: Text to embed

        Returns:
            Embedding vector (list of floats) or None if failed
        """
        if not text or len(text.strip()) == 0:
            logger.warning("Empty text provided for embedding")
            return None

        try:
            response = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={
                    "model": self.model_name, 
                    "prompt": text,
                    "options": {
                        "num_ctx": 2048
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            
            embedding = data.get("embedding")
            if not embedding:
                logger.error(f"No embedding in Ollama response. Response: {data}")
                return None
            
            # Verify dimension
            if len(embedding) != self.embedding_dimension:
                logger.error(
                    f"Embedding dimension mismatch. Expected {self.embedding_dimension}, "
                    f"got {len(embedding)}"
                )
                return None
            
            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding via Ollama: {e}")
            return None

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts via Ollama (synchronous).

        Args:
            texts: List of texts to embed
            batch_size: Ignored (Ollama processes sequentially for stability)

        Returns:
            List of embedding vectors
        """
        if not texts:
            logger.warning("Empty text list provided for embedding")
            return []

        try:
            # Filter out empty texts
            non_empty_texts = [(i, t) for i, t in enumerate(texts) if t and len(t.strip()) > 0]
            
            if not non_empty_texts:
                logger.warning("All texts were empty")
                return [None] * len(texts)

            logger.info(f"Generating embeddings for {len(non_empty_texts)} texts via Ollama")

            embeddings = [None] * len(texts)
            
            # Process texts sequentially (one at a time for stability)
            for i, (original_idx, text) in enumerate(non_empty_texts):
                try:
                    # Truncate text if too long (max 2000 chars for safety)
                    truncated_text = text[:2000] if len(text) > 2000 else text
                    
                    response = requests.post(
                        f"{self.ollama_url}/api/embeddings",
                        json={
                            "model": self.model_name, 
                            "prompt": truncated_text,
                            "options": {
                                "num_ctx": 2048  # nomic-embed-text max context
                            }
                        },
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()
                    embedding = data.get("embedding")
                    
                    if embedding and len(embedding) == self.embedding_dimension:
                        embeddings[original_idx] = embedding
                        if (i + 1) % 5 == 0:
                            logger.info(f"Progress: {i + 1}/{len(non_empty_texts)} embeddings generated")
                    else:
                        if not embedding:
                            logger.warning(f"No embedding from Ollama for index {original_idx}. Response: {data.keys()}")
                        else:
                            logger.warning(f"Invalid embedding dimension for index {original_idx}: {len(embedding)} vs {self.embedding_dimension}")
                        embeddings[original_idx] = None
                except Exception as e:
                    logger.warning(f"Failed to embed text at index {original_idx}: {e}")
                    embeddings[original_idx] = None

            successful = sum(1 for e in embeddings if e is not None)
            logger.info(f"Successfully generated {successful}/{len(texts)} embeddings")
            return embeddings

        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return [None] * len(texts)

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Similarity score (0-1)
        """
        try:
            arr1 = np.array(vec1)
            arr2 = np.array(vec2)

            # Normalize vectors
            arr1_norm = arr1 / np.linalg.norm(arr1)
            arr2_norm = arr2 / np.linalg.norm(arr2)

            # Calculate cosine similarity
            similarity = np.dot(arr1_norm, arr2_norm)

            return float(similarity)

        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    @staticmethod
    def l2_distance(vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate L2 (Euclidean) distance between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Distance score
        """
        try:
            arr1 = np.array(vec1)
            arr2 = np.array(vec2)

            # Calculate L2 distance
            distance = np.linalg.norm(arr1 - arr2)

            return float(distance)

        except Exception as e:
            logger.error(f"Error calculating L2 distance: {e}")
            return float('inf')


# Singleton instance
_embeddings_service = None


def get_embeddings_service() -> EmbeddingsService:
    """Get or create embeddings service singleton"""
    global _embeddings_service
    if _embeddings_service is None:
        _embeddings_service = EmbeddingsService()
    return _embeddings_service
