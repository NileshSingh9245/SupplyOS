"""The native AI adapter contract is tested without external calls or live keys."""
from __future__ import annotations

import importlib
import json
import secrets

import httpx
import pytest

from app.core import config


@pytest.fixture
def provider_module(monkeypatch):
    for field in config.Settings.model_fields.values():
        if isinstance(field.validation_alias, str):
            monkeypatch.delenv(field.validation_alias, raising=False)
    settings = config.Settings(
        _env_file=None, app_env="test", free_only_mode=False,
        database_url="postgresql+asyncpg://test_user@127.0.0.1/supplyos_test_config",
        database_url_sync="postgresql+psycopg2://test_user@127.0.0.1/supplyos_test_config",
        redis_url="redis://127.0.0.1:6379/0", jwt_secret=secrets.token_urlsafe(48),
        anthropic_api_key="", ai_provider="anthropic",
        frontend_url="http://localhost:3000", cookie_secure=False, cookie_samesite="lax",
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    module = importlib.import_module("app.infrastructure.external.ai_provider")
    monkeypatch.setattr(module, "settings", settings)
    return module


def mock_transport(monkeypatch, module, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_native_messages_request_and_text_blocks(provider_module, monkeypatch):
    key = secrets.token_urlsafe(24)

    def handler(request):
        if request.headers.get("x-api-key") != key:
            pytest.fail("Native adapter omitted its private key", pytrace=False)
        assert request.url == "https://api.anthropic.com/v1/messages"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["system"] == "Summarize metrics"
        assert body["messages"] == [{"role": "user", "content": "Aggregate metrics"}]
        assert body["max_tokens"] == 140
        return httpx.Response(200, json={"content": [
            {"type": "text", "text": "First observation."},
            {"type": "thinking", "thinking": "Not output to users."},
            {"type": "text", "text": "Second observation."},
        ]})

    mock_transport(monkeypatch, provider_module, handler)
    provider = provider_module.AnthropicProvider(key, "test-model")
    text = await provider.analyze(
        system_prompt="Summarize metrics", user_prompt="Aggregate metrics", max_tokens=140,
    )
    assert text == "First observation.\nSecond observation."


@pytest.mark.asyncio
async def test_provider_error_does_not_expose_response_body(provider_module, monkeypatch):
    key = secrets.token_urlsafe(24)
    mock_transport(monkeypatch, provider_module, lambda request: httpx.Response(
        401, json={"error": {"message": key}},
    ))
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        await provider_module.AnthropicProvider(key, "test-model").analyze(
            system_prompt="System", user_prompt="Metrics",
        )
    if key in str(error.value):
        pytest.fail("Provider failure exposed private response data", pytrace=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"content": "not a list"}, {"content": []}])
async def test_invalid_provider_messages_fail_safely(provider_module, monkeypatch, body):
    mock_transport(monkeypatch, provider_module, lambda request: httpx.Response(200, json=body))
    with pytest.raises(RuntimeError, match="Anthropic returned"):
        await provider_module.AnthropicProvider(secrets.token_urlsafe(24), "test-model").analyze(
            system_prompt="System", user_prompt="Metrics",
        )


@pytest.mark.asyncio
async def test_network_failure_is_sanitized(provider_module, monkeypatch):
    key = secrets.token_urlsafe(24)

    def handler(request):
        raise httpx.ConnectError(key, request=request)

    mock_transport(monkeypatch, provider_module, handler)
    with pytest.raises(RuntimeError, match="unreachable") as error:
        await provider_module.AnthropicProvider(key, "test-model").analyze(
            system_prompt="System", user_prompt="Metrics",
        )
    if key in str(error.value):
        pytest.fail("Network failure exposed private data", pytrace=False)


def test_unconfigured_provider_is_disabled(provider_module):
    assert provider_module.get_ai_provider() is None


def test_native_key_selects_native_adapter(provider_module, monkeypatch):
    values = provider_module.settings.model_dump()
    settings = config.Settings(
        **values, _env_file=None,
        database_url=provider_module.settings.database_url,
        database_url_sync=provider_module.settings.database_url_sync,
        redis_url=provider_module.settings.redis_url,
        jwt_secret=secrets.token_urlsafe(48), anthropic_api_key=secrets.token_urlsafe(24),
    )
    monkeypatch.setattr(provider_module, "settings", settings)
    assert isinstance(provider_module.get_ai_provider(), provider_module.AnthropicProvider)
