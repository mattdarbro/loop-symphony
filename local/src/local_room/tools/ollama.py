"""Ollama client implementing the Tool protocol.

Provides local LLM capabilities via Ollama.
"""

import logging
from typing import Any

import httpx

from local_room.tools.base import Tool, ToolManifest

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for Ollama local LLM.

    Implements the Tool protocol with capabilities: {reasoning, synthesis, analysis}
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: int = 120,
    ) -> None:
        """Initialize the Ollama client.

        Args:
            host: Ollama API host URL
            model: Default model to use
            timeout: Request timeout in seconds
        """
        self._host = host.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._manifest = ToolManifest(
            name="ollama",
            version="1.0.0",
            description="Local LLM via Ollama",
            capabilities=frozenset({"reasoning", "synthesis", "analysis"}),
        )

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def manifest(self) -> ToolManifest:
        return self._manifest

    @property
    def model(self) -> str:
        return self._model

    async def health_check(self) -> dict[str, Any]:
        """Check if Ollama is running and the model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Check Ollama is running
                response = await client.get(f"{self._host}/api/tags")
                if response.status_code != 200:
                    return {
                        "healthy": False,
                        "error": f"Ollama returned {response.status_code}",
                    }

                # Check if our model is available
                data = response.json()
                models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]

                model_available = self._model.split(":")[0] in models

                return {
                    "healthy": True,
                    "model": self._model,
                    "model_available": model_available,
                    "available_models": models,
                }

        except httpx.ConnectError:
            return {
                "healthy": False,
                "error": "Cannot connect to Ollama. Is it running?",
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a completion from Ollama.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            model: Model to use (defaults to configured model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            The generated text
        """
        model = model or self._model

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._host}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": options,
                    },
                )

                if response.status_code != 200:
                    raise OllamaError(f"Ollama returned {response.status_code}: {response.text}")

                data = response.json()
                return data.get("message", {}).get("content", "")

        except httpx.TimeoutException:
            raise OllamaError(f"Ollama request timed out after {self._timeout}s")
        except httpx.ConnectError:
            raise OllamaError("Cannot connect to Ollama. Is it running?")

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Simple generation without chat format.

        Args:
            prompt: The prompt
            model: Model to use
            temperature: Sampling temperature

        Returns:
            The generated text
        """
        model = model or self._model

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._host}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": temperature},
                    },
                )

                if response.status_code != 200:
                    raise OllamaError(f"Ollama returned {response.status_code}")

                data = response.json()
                return data.get("response", "")

        except httpx.TimeoutException:
            raise OllamaError(f"Ollama request timed out after {self._timeout}s")
        except httpx.ConnectError:
            raise OllamaError("Cannot connect to Ollama. Is it running?")

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self._host}/api/tags")
                if response.status_code != 200:
                    return []

                data = response.json()
                return [m.get("name", "") for m in data.get("models", [])]

        except Exception:
            return []

    async def pull_model(self, model: str) -> bool:
        """Pull a model from Ollama registry.

        Args:
            model: Model name to pull

        Returns:
            True if successful
        """
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:  # Long timeout for download
                response = await client.post(
                    f"{self._host}/api/pull",
                    json={"name": model, "stream": False},
                )
                return response.status_code == 200

        except Exception as e:
            logger.error(f"Failed to pull model {model}: {e}")
            return False


class OllamaError(Exception):
    """Error from Ollama operations."""

    pass
