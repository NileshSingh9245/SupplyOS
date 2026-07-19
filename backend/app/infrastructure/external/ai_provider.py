"""AI provider protocol + Claude implementation via emergentintegrations.

The rest of the codebase depends only on `AIProvider`. Swap providers by
changing `AI_PROVIDER` env var and adding a new implementation.
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings

settings = get_settings()


class AIProvider(Protocol):
    async def analyze(
        self, *, system_prompt: str, user_prompt: str,
        max_tokens: int = 800, temperature: float = 0.2,
    ) -> str: ...


class ClaudeProvider:
    """Claude Sonnet 4.5 via emergentintegrations.LlmChat."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self._api_key = api_key
        self._model = model

    async def analyze(
        self, *, system_prompt: str, user_prompt: str,
        max_tokens: int = 800, temperature: float = 0.2,
    ) -> str:
        # Lazy import so backend can start even if emergentintegrations is temporarily broken
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import uuid

        chat = LlmChat(
            api_key=self._api_key,
            session_id=str(uuid.uuid4()),
            system_message=system_prompt,
        ).with_model("anthropic", self._model).with_params(max_tokens=max_tokens, temperature=temperature)
        resp = await chat.send_message(UserMessage(text=user_prompt))
        return resp if isinstance(resp, str) else str(resp)


def get_ai_provider() -> AIProvider | None:
    if not settings.emergent_llm_key:
        return None
    if settings.ai_provider == "anthropic":
        return ClaudeProvider(api_key=settings.emergent_llm_key, model=settings.ai_model)
    # Future: openai, gemini
    return ClaudeProvider(api_key=settings.emergent_llm_key)
