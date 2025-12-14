"""
PDF Parser Service
Extracts text and metadata from PDF files
"""
import PyPDF2
import pdfplumber
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class PDFParser:
    """Parser for PDF documents"""

    @staticmethod
    def extract_text(file_path: str) -> str:
        """
        Extract all text from PDF using pdfplumber

        Args:
            file_path: Path to PDF file

        Returns:
            Extracted text content
        """
        try:
            text = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise

    @staticmethod
    def extract_metadata(file_path: str) -> Dict:
        """
        Extract PDF metadata

        Args:
            file_path: Path to PDF file

        Returns:
            Dictionary with metadata
        """
        try:
            from pathlib import Path
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                metadata = pdf_reader.metadata or {}

                # Get title - use filename as fallback if metadata title is empty
                title = metadata.get("/Title", "").strip()
                if not title:
                    # Use filename without extension as title
                    title = Path(file_path).stem or "Untitled Document"
                
                return {
                    "title": title,
                    "author": metadata.get("/Author", ""),
                    "subject": metadata.get("/Subject", ""),
                    "creator": metadata.get("/Creator", ""),
                    "producer": metadata.get("/Producer", ""),
                    "pages": len(pdf_reader.pages),
                    "created_date": str(metadata.get("/CreationDate", "")),
                    "modified_date": str(metadata.get("/ModDate", "")),
                }
        except Exception as e:
            logger.error(f"Error extracting metadata from PDF: {e}")
            from pathlib import Path
            # Fallback: use filename as title
            return {
                "title": Path(file_path).stem or "Untitled Document",
                "pages": 0
            }

    @staticmethod
    def extract_with_structure(file_path: str) -> List[Dict]:
        """
        Extract text with page structure preserved

        Args:
            file_path: Path to PDF file

        Returns:
            List of dictionaries with page data
        """
        try:
            pages = []
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    tables = page.extract_tables() or []

                    pages.append({
                        "page_number": i + 1,
                        "text": page_text,
                        "tables": tables,
                        "has_tables": len(tables) > 0
                    })
            return pages
        except Exception as e:
            logger.error(f"Error extracting structured data from PDF: {e}")
            raise
