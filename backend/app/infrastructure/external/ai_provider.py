"""Direct, optional Claude Messages API configured by the application owner.

The rest of the codebase depends only on `AIProvider`. Swap providers by
changing `AI_PROVIDER` env var and adding a new implementation.
"""
from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import get_settings

settings = get_settings()


class AIProvider(Protocol):
    async def analyze(
        self, *, system_prompt: str, user_prompt: str,
        max_tokens: int = 800, temperature: float = 0.2,
    ) -> str: ...


class AnthropicProvider:
    """Native Messages API; uses the core HTTP client rather than a private SDK."""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    async def analyze(
        self, *, system_prompt: str, user_prompt: str,
        max_tokens: int = 800, temperature: float = 0.2,
    ) -> str:
        if settings.free_only_mode:
            raise RuntimeError("External AI summaries are on hold in free-only mode")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": self._model,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Anthropic request failed (HTTP {exc.response.status_code})") from None
        except httpx.RequestError:
            raise RuntimeError("Anthropic service is unreachable") from None

        try:
            content = response.json()["content"]
            if not isinstance(content, list):
                raise ValueError
            text = "\n".join(
                block["text"] for block in content
                if isinstance(block, dict) and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ).strip()
        except (ValueError, KeyError, TypeError):
            raise RuntimeError("Anthropic returned an invalid message") from None
        if not text:
            raise RuntimeError("Anthropic returned no text content")
        return text


def get_ai_provider() -> AIProvider | None:
    if settings.free_only_mode or not settings.anthropic_api_key:
        return None
    return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.ai_model)
