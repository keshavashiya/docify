"""
URL Parser Service
Fetches and extracts content from web pages
"""
import httpx
from bs4 import BeautifulSoup
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class URLParser:
    """Parser for web URLs"""

    @staticmethod
    async def fetch_and_parse(url: str, timeout: int = 30) -> Dict:
        """
        Fetch URL and extract content

        Args:
            url: URL to fetch
            timeout: Request timeout in seconds

        Returns:
            Dictionary with text and metadata
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # Remove script, style, and other non-content elements
                for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    element.decompose()

                # Extract text
                text = soup.get_text()

                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)

                # Extract metadata
                metadata = {
                    "title": "",
                    "description": "",
                    "author": "",
                    "url": str(response.url),
                    "status_code": response.status_code
                }

                # Get title
                if soup.title:
                    metadata["title"] = soup.title.string.strip() if soup.title.string else ""

                # Get meta description
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc:
                    metadata["description"] = meta_desc.get("content", "")

                # Get author
                meta_author = soup.find("meta", attrs={"name": "author"})
                if meta_author:
                    metadata["author"] = meta_author.get("content", "")

                # Try Open Graph tags
                if not metadata["title"]:
                    og_title = soup.find("meta", property="og:title")
                    if og_title:
                        metadata["title"] = og_title.get("content", "")

                if not metadata["description"]:
                    og_desc = soup.find("meta", property="og:description")
                    if og_desc:
                        metadata["description"] = og_desc.get("content", "")

                return {
                    "text": text,
                    "metadata": metadata
                }

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching URL {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing URL {url}: {e}")
            raise
