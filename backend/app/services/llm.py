"""
LLM Service
Handles calls to Ollama (local) or cloud LLMs (OpenAI, Anthropic)
"""
import httpx
import logging
import json
from typing import Optional, List, Dict
from app.core.config import settings
from app.services.hardware import HardwareDetector

logger = logging.getLogger(__name__)


class LLMService:
    """Service for LLM interactions (Ollama, OpenAI, Anthropic)"""

    def __init__(self):
        self.ollama_base_url = settings.OLLAMA_BASE_URL
        # Auto-detect optimal model if not explicitly configured
        self.default_model = settings.DEFAULT_MODEL or HardwareDetector.get_optimal_model()
        self.openai_api_key = settings.OPENAI_API_KEY
        self.anthropic_api_key = settings.ANTHROPIC_API_KEY
        self.hardware = HardwareDetector()
        logger.info(f"LLM Service initialized with model: {self.default_model}")

    async def call_ollama(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        top_p: float = 0.9
    ) -> str:
        """
        Call local Ollama LLM with streaming for faster response times.

        Args:
            prompt: The prompt to send
            model: Model name (default: mistral)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1, lower = deterministic)
            top_p: Nucleus sampling parameter

        Returns:
            Generated text response
        """
        model = model or self.default_model

        try:
            # Get hardware-aware options
            hw_options = self.hardware.get_ollama_options()
            
            # Use streaming for faster time-to-first-token
            # Adjust timeout based on hardware (CPU needs more time)
            timeout = 600 if not self.hardware.has_gpu() else 300
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Build options, filtering out None values
                options = {
                    "temperature": hw_options.get("temperature", temperature),
                    "top_p": hw_options.get("top_p", top_p),
                    "num_predict": hw_options.get("num_predict", max_tokens),
                }
                if hw_options.get("num_thread"):
                    options["num_thread"] = hw_options.get("num_thread")
                
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": True,  # Stream for faster response
                        "options": options
                    }
                )

                if response.status_code != 200:
                    logger.error(f"Ollama error: {response.text}")
                    raise Exception(f"Ollama API error: {response.status_code}")

                # Collect streamed response
                full_response = ""
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            full_response += chunk.get("response", "")
                        except json.JSONDecodeError:
                            pass
                
                return full_response.strip()

        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama. Is it running?")
            raise Exception(
                "Ollama is not available. Start it with: ollama serve"
            )
        except Exception as e:
            logger.error(f"Error calling Ollama: {e}")
            raise

    async def call_openai(
        self,
        prompt: str,
        model: str = "gpt-3.5-turbo",
        max_tokens: int = 1000,
        temperature: float = 0.3
    ) -> str:
        """
        Call OpenAI API (if API key configured).

        Args:
            prompt: The prompt to send
            model: Model name
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text response
        """
        if not self.openai_api_key:
            raise Exception("OpenAI API key not configured")

        try:
            import openai
            openai.api_key = self.openai_api_key

            response = openai.ChatCompletion.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful research assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )

            return response['choices'][0]['message']['content'].strip()

        except ImportError:
            raise Exception("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            logger.error(f"Error calling OpenAI: {e}")
            raise

    async def call_anthropic(
        self,
        prompt: str,
        model: str = "claude-2",
        max_tokens: int = 1000,
        temperature: float = 0.3
    ) -> str:
        """
        Call Anthropic Claude API (if API key configured).

        Args:
            prompt: The prompt to send
            model: Model name
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text response
        """
        if not self.anthropic_api_key:
            raise Exception("Anthropic API key not configured")

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            return response.content[0].text.strip()

        except ImportError:
            raise Exception("Anthropic package not installed. Install with: pip install anthropic")
        except Exception as e:
            logger.error(f"Error calling Anthropic: {e}")
            raise

    async def call(
        self,
        prompt: str,
        provider: str = "ollama",
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        **kwargs
    ) -> str:
        """
        Generic call method that routes to appropriate provider.

        Args:
            prompt: The prompt to send
            provider: "ollama", "openai", or "anthropic"
            model: Model name
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text response
        """
        if provider == "ollama":
            return await self.call_ollama(prompt, model, max_tokens, temperature)
        elif provider == "openai":
            return await self.call_openai(prompt, model, max_tokens, temperature)
        elif provider == "anthropic":
            return await self.call_anthropic(prompt, model, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def call_with_json(
        self,
        prompt: str,
        provider: str = "ollama",
        model: Optional[str] = None,
        max_tokens: int = 1000
    ) -> Dict:
        """
        Call LLM expecting JSON response.
        Useful for structured outputs like query expansion.

        Args:
            prompt: The prompt to send
            provider: LLM provider
            model: Model name
            max_tokens: Maximum tokens to generate

        Returns:
            Parsed JSON response
        """
        import json

        response_text = await self.call(
            prompt,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=0.1  # Lower temperature for structured output
        )

        try:
            # Try to parse JSON from response
            # Sometimes LLM wraps it in markdown code blocks
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text

            return json.loads(json_str)

        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response: {response_text}")
            raise Exception("LLM response was not valid JSON")


# Singleton instance
_llm_service = None


def get_llm_service() -> LLMService:
    """Get or create LLM service singleton"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


# Helper function for sync code
def call_llm(
    prompt: str,
    provider: str = "ollama",
    model: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.3
) -> str:
    """
    Sync wrapper for LLM calls.
    Use this when you can't use async/await.

    Args:
        prompt: The prompt to send
        provider: LLM provider
        model: Model name
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature

    Returns:
        Generated text response
    """
    import asyncio

    llm = get_llm_service()

    # Create event loop if needed
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        llm.call(
            prompt,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature
        )
    )
