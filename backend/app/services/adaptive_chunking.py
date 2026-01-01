"""
Adaptive Chunking Service
Document-type aware chunking with optimized sizes (v2 Phase 3)

Chunk sizes are optimized based on document type:
- Code: 512 tokens (preserve function/class boundaries)
- Papers/PDFs: 1024 tokens (larger semantic units)
- Web content: 768 tokens (balanced for variety)
- Text/Notes: 512 tokens (standard paragraphs)
"""
import logging
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.schemas.chunk import ChunkCreate
from app.services.chunking import ChunkingService

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Document types for adaptive chunking"""
    CODE = "code"
    PAPER = "paper"
    PDF = "pdf"
    WEB = "web"
    MARKDOWN = "markdown"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class ChunkingConfig:
    """Configuration for document-type specific chunking"""
    chunk_size: int
    overlap: int
    preserve_paragraphs: bool
    preserve_code_blocks: bool


# Optimized configurations per document type
CHUNKING_CONFIGS: Dict[DocumentType, ChunkingConfig] = {
    DocumentType.CODE: ChunkingConfig(
        chunk_size=512,
        overlap=100,
        preserve_paragraphs=False,
        preserve_code_blocks=True
    ),
    DocumentType.PAPER: ChunkingConfig(
        chunk_size=1024,
        overlap=150,
        preserve_paragraphs=True,
        preserve_code_blocks=False
    ),
    DocumentType.PDF: ChunkingConfig(
        chunk_size=1024,
        overlap=150,
        preserve_paragraphs=True,
        preserve_code_blocks=False
    ),
    DocumentType.WEB: ChunkingConfig(
        chunk_size=768,
        overlap=100,
        preserve_paragraphs=True,
        preserve_code_blocks=True
    ),
    DocumentType.MARKDOWN: ChunkingConfig(
        chunk_size=768,
        overlap=100,
        preserve_paragraphs=True,
        preserve_code_blocks=True
    ),
    DocumentType.TEXT: ChunkingConfig(
        chunk_size=512,
        overlap=50,
        preserve_paragraphs=True,
        preserve_code_blocks=False
    ),
    DocumentType.UNKNOWN: ChunkingConfig(
        chunk_size=512,
        overlap=50,
        preserve_paragraphs=True,
        preserve_code_blocks=False
    ),
}


class AdaptiveChunkingService:
    """
    Adaptive chunking that adjusts chunk size based on document type.

    Benefits:
    - Code: Smaller chunks preserve function boundaries
    - Papers: Larger chunks maintain argument coherence
    - Web: Medium chunks handle mixed content
    """

    def __init__(self):
        self.base_chunker = ChunkingService()

    def detect_document_type(
        self,
        content: str,
        resource_type: str,
        file_extension: Optional[str] = None
    ) -> DocumentType:
        """
        Detect document type from content and metadata.

        Args:
            content: Document text content
            resource_type: Resource type from DB (pdf, url, text, etc.)
            file_extension: Optional file extension

        Returns:
            Detected DocumentType
        """
        resource_type_lower = resource_type.lower() if resource_type else ""
        ext = (file_extension or "").lower().lstrip(".")

        # Check by extension/type first
        if ext in ["py", "js", "ts", "java", "cpp", "c", "go", "rs", "rb"]:
            return DocumentType.CODE
        if ext == "md":
            return DocumentType.MARKDOWN
        if resource_type_lower == "pdf" or ext == "pdf":
            # Check if it's an academic paper
            if self._is_academic_paper(content):
                return DocumentType.PAPER
            return DocumentType.PDF
        if resource_type_lower == "url":
            return DocumentType.WEB

        # Content-based detection
        if self._looks_like_code(content):
            return DocumentType.CODE
        if self._is_academic_paper(content):
            return DocumentType.PAPER
        if "```" in content or content.startswith("#"):
            return DocumentType.MARKDOWN

        return DocumentType.TEXT

    def _looks_like_code(self, content: str) -> bool:
        """Check if content looks like code"""
        code_indicators = [
            r'\bdef\s+\w+\s*\(',          # Python functions
            r'\bfunction\s+\w+\s*\(',      # JS functions
            r'\bclass\s+\w+\s*[:\{]',      # Class definitions
            r'\bimport\s+[\w\.]+',         # Import statements
            r'\bfrom\s+\w+\s+import',      # Python imports
            r'const\s+\w+\s*=',            # JS const
            r'let\s+\w+\s*=',              # JS let
            r'\breturn\s+',                # Return statements
        ]

        matches = sum(1 for pattern in code_indicators
                     if re.search(pattern, content[:2000]))
        return matches >= 3

    def _is_academic_paper(self, content: str) -> bool:
        """Check if content looks like an academic paper"""
        academic_indicators = [
            "abstract",
            "introduction",
            "methodology",
            "conclusion",
            "references",
            "et al.",
            "arxiv",
            "doi:",
            "figure",
            "table",
        ]

        content_lower = content[:5000].lower()
        matches = sum(1 for indicator in academic_indicators
                     if indicator in content_lower)
        return matches >= 3

    def chunk_document(
        self,
        content: str,
        resource_id: str,
        resource_type: str,
        file_extension: Optional[str] = None
    ) -> Tuple[List[ChunkCreate], DocumentType, ChunkingConfig]:
        """
        Chunk document with adaptive sizing.

        Args:
            content: Document text content
            resource_id: Resource UUID
            resource_type: Type from database
            file_extension: Optional file extension

        Returns:
            Tuple of (chunks, detected_type, config_used)
        """
        # Detect document type
        doc_type = self.detect_document_type(content, resource_type, file_extension)
        config = CHUNKING_CONFIGS[doc_type]

        logger.info(f"Adaptive chunking: type={doc_type.value}, "
                   f"chunk_size={config.chunk_size}, overlap={config.overlap}")

        # Create type-specific chunker
        chunker = ChunkingService(
            chunk_size=config.chunk_size,
            overlap=config.overlap
        )

        # Special handling for code
        if config.preserve_code_blocks and doc_type == DocumentType.CODE:
            chunks = self._chunk_code(content, resource_id, chunker)
        else:
            chunks = chunker.chunk_text(
                content,
                resource_id,
                preserve_paragraphs=config.preserve_paragraphs
            )

        return chunks, doc_type, config

    def _chunk_code(
        self,
        content: str,
        resource_id: str,
        chunker: ChunkingService
    ) -> List[ChunkCreate]:
        """
        Special chunking for code that preserves function/class boundaries.
        """
        chunks = []
        sequence = 0

        # Split by function/class definitions
        # Pattern matches Python and JS/TS function/class definitions
        patterns = [
            r'(?m)^(?:async\s+)?(?:def|function)\s+\w+',  # Functions
            r'(?m)^class\s+\w+',                          # Classes
        ]

        # Find all definition points
        split_points = [0]
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                split_points.append(match.start())
        split_points = sorted(set(split_points))
        split_points.append(len(content))

        # Create chunks from split points
        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i + 1]

            # Find a good ending point (next blank line or end)
            section = content[start:end].strip()
            if not section:
                continue

            # Check token count
            token_count = chunker.count_tokens(section)

            if token_count > chunker.chunk_size * 1.5:
                # Too large, use regular chunking
                sub_chunks = chunker.chunk_text(section, resource_id, preserve_paragraphs=False)
                for sub_chunk in sub_chunks:
                    sub_chunk.sequence = sequence
                    chunks.append(sub_chunk)
                    sequence += 1
            else:
                chunks.append(ChunkCreate(
                    resource_id=resource_id,
                    content=section,
                    sequence=sequence,
                    token_count=token_count
                ))
                sequence += 1

        return chunks


# Singleton instance
_adaptive_chunker: Optional[AdaptiveChunkingService] = None


def get_adaptive_chunker() -> AdaptiveChunkingService:
    """Get or create adaptive chunker singleton"""
    global _adaptive_chunker
    if _adaptive_chunker is None:
        _adaptive_chunker = AdaptiveChunkingService()
    return _adaptive_chunker
