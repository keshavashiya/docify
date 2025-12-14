"""
Chunking Service
Intelligently splits text into chunks with overlap and context preservation
"""
import tiktoken
from typing import List, Dict, Optional
from app.schemas.chunk import ChunkCreate
import logging

logger = logging.getLogger(__name__)


class ChunkingService:
    """Service for intelligent text chunking"""

    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        """
        Initialize chunking service

        Args:
            chunk_size: Target chunk size in tokens
            overlap: Number of overlapping tokens between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"Could not load tiktoken encoding: {e}. Using approximate token counting.")
            self.encoding = None

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text

        Args:
            text: Text to count tokens for

        Returns:
            Number of tokens
        """
        if self.encoding:
            return len(self.encoding.encode(text))
        else:
            # Approximate: 1 token ≈ 4 characters
            return len(text) // 4

    def chunk_text(
        self,
        text: str,
        resource_id: str,
        preserve_paragraphs: bool = True
    ) -> List[ChunkCreate]:
        """
        Split text into chunks with overlap

        Args:
            text: Text to chunk
            resource_id: ID of the resource
            preserve_paragraphs: Try to keep paragraphs intact

        Returns:
            List of chunk schemas
        """
        chunks = []

        if preserve_paragraphs:
            paragraphs = text.split('\n\n')
            current_chunk = ""
            sequence = 0

            for para in paragraphs:
                if not para.strip():
                    continue

                para_tokens = self.count_tokens(para)
                current_tokens = self.count_tokens(current_chunk)

                # If adding this paragraph would exceed chunk size
                if current_tokens + para_tokens > self.chunk_size and current_chunk:
                    # Save current chunk
                    chunks.append(ChunkCreate(
                        resource_id=resource_id,
                        content=current_chunk.strip(),
                        sequence=sequence,
                        token_count=self.count_tokens(current_chunk)
                    ))
                    sequence += 1

                    # Start new chunk with overlap
                    # Take last few sentences from previous chunk
                    sentences = current_chunk.split('. ')
                    overlap_text = '. '.join(sentences[-2:]) if len(sentences) > 1 else ""
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    # Add paragraph to current chunk
                    if current_chunk:
                        current_chunk += "\n\n" + para
                    else:
                        current_chunk = para

            # Add last chunk
            if current_chunk.strip():
                chunks.append(ChunkCreate(
                    resource_id=resource_id,
                    content=current_chunk.strip(),
                    sequence=sequence,
                    token_count=self.count_tokens(current_chunk)
                ))
        else:
            # Simple token-based chunking
            tokens = text.split()
            current_chunk_tokens = []
            sequence = 0

            for token in tokens:
                current_chunk_tokens.append(token)

                if len(current_chunk_tokens) >= self.chunk_size:
                    chunk_text = ' '.join(current_chunk_tokens)
                    chunks.append(ChunkCreate(
                        resource_id=resource_id,
                        content=chunk_text,
                        sequence=sequence,
                        token_count=len(current_chunk_tokens)
                    ))
                    sequence += 1

                    # Keep overlap tokens
                    current_chunk_tokens = current_chunk_tokens[-self.overlap:]

            # Add remaining tokens
            if current_chunk_tokens:
                chunk_text = ' '.join(current_chunk_tokens)
                chunks.append(ChunkCreate(
                    resource_id=resource_id,
                    content=chunk_text,
                    sequence=sequence,
                    token_count=len(current_chunk_tokens)
                ))

        return chunks

    def chunk_with_structure(
        self,
        pages: List[Dict],
        resource_id: str
    ) -> List[ChunkCreate]:
        """
        Chunk with page structure preservation (for PDFs)

        Args:
            pages: List of page dictionaries with text and page_number
            resource_id: ID of the resource

        Returns:
            List of chunk schemas
        """
        chunks = []
        sequence = 0

        for page in pages:
            page_text = page.get("text", "")
            page_number = page.get("page_number", 0)

            if not page_text.strip():
                continue

            # Chunk the page text
            page_chunks = self.chunk_text(
                page_text,
                resource_id,
                preserve_paragraphs=True
            )

            # Add page number to metadata
            for chunk in page_chunks:
                chunk.sequence = sequence
                chunk.page_number = page_number
                chunk.metadata = {"page": page_number}
                chunks.append(chunk)
                sequence += 1

        return chunks
