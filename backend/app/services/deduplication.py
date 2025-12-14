"""
Deduplication Service
Handles content normalization, hashing, and duplicate detection
"""
import hashlib
import re
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import Resource
import logging

logger = logging.getLogger(__name__)


class DeduplicationService:
    """Service for detecting and managing duplicate resources"""

    @staticmethod
    def normalize_content(text: str) -> str:
        """
        Normalize content for consistent hashing

        Normalization steps:
        1. Convert to lowercase
        2. Remove extra whitespace
        3. Remove common boilerplate patterns
        4. Strip leading/trailing whitespace

        Args:
            text: Raw text content

        Returns:
            Normalized text
        """
        # Lowercase
        text = text.lower()

        # Remove extra whitespace (multiple spaces, tabs, newlines)
        text = re.sub(r'\s+', ' ', text)

        # Remove common boilerplate patterns
        text = re.sub(r'page \d+ of \d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'©.*?\d{4}', '', text)
        text = re.sub(r'copyright.*?\d{4}', '', text, flags=re.IGNORECASE)

        # Remove URLs
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    @staticmethod
    def generate_content_hash(text: str) -> str:
        """
        Generate SHA256 hash of normalized content

        Args:
            text: Text content to hash

        Returns:
            64-character hexadecimal hash
        """
        normalized = DeduplicationService.normalize_content(text)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def check_duplicate(content_hash: str, db: Session) -> Optional[Resource]:
        """
        Check if content hash already exists in database

        Args:
            content_hash: SHA256 hash to check
            db: Database session

        Returns:
            Original resource if duplicate found, None otherwise
        """
        try:
            return db.query(Resource).filter(
                Resource.content_hash == content_hash
            ).first()
        except Exception as e:
            logger.error(f"Error checking for duplicate: {e}")
            return None

    @staticmethod
    def link_duplicate(
        new_resource: Resource,
        original_resource: Resource,
        db: Session
    ) -> Resource:
        """
        Link new resource as duplicate of original

        This allows the new resource to reuse the original's
        chunks and embeddings, saving processing time.

        Args:
            new_resource: Newly uploaded resource
            original_resource: Original resource with same content
            db: Database session

        Returns:
            Updated new resource
        """
        try:
            new_resource.is_duplicate_of = original_resource.id
            new_resource.embedding_status = "complete"  # Reuse original's embeddings
            new_resource.chunks_count = original_resource.chunks_count

            db.commit()
            db.refresh(new_resource)

            logger.info(
                f"Linked resource {new_resource.id} as duplicate of {original_resource.id}"
            )

            return new_resource

        except Exception as e:
            logger.error(f"Error linking duplicate: {e}")
            db.rollback()
            raise

    @staticmethod
    def get_deduplication_stats(db: Session) -> dict:
        """
        Get deduplication statistics

        Args:
            db: Database session

        Returns:
            Dictionary with stats
        """
        try:
            total_resources = db.query(Resource).count()
            duplicates = db.query(Resource).filter(
                Resource.is_duplicate_of.isnot(None)
            ).count()
            unique_resources = total_resources - duplicates

            dedup_rate = (duplicates / total_resources * 100) if total_resources > 0 else 0

            return {
                "total_resources": total_resources,
                "unique_resources": unique_resources,
                "duplicates": duplicates,
                "deduplication_rate": round(dedup_rate, 2)
            }
        except Exception as e:
            logger.error(f"Error getting deduplication stats: {e}")
            return {
                "total_resources": 0,
                "unique_resources": 0,
                "duplicates": 0,
                "deduplication_rate": 0.0
            }
