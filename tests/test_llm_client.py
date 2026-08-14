"""Tests for LlmClient with mocked httpx."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.config.schema import LlmProfile
from app.core.llm_client import ApiError, AuthError, LlmClient, RateLimitError


class _MockTransport(httpx.BaseTransport):
    def __init__(self, status: int, body: dict[str, Any] | str) -> None:
        self.status = status
        self.body = body
        self.last_request: httpx.Request | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        if isinstance(self.body, dict):
            content = json.dumps(self.body).encode()
            headers = {"content-type": "application/json"}
        else:
            content = str(self.body).encode()
            headers = {"content-type": "text/plain"}
        return httpx.Response(self.status, content=content, headers=headers, request=request)


def _run_with_transport(
    transport: _MockTransport,
    profile: LlmProfile,
    messages: list[dict[str, Any]] | None = None,
) -> str:
    """Patch httpx.Client so LlmClient._request uses our mock transport."""
    client = LlmClient(profile)
    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    with patch("app.core.llm_client.httpx.Client", _PatchedClient):
        return client.chat(messages or [{"role": "user", "content": "hi"}])


def test_chat_success() -> None:
    transport = _MockTransport(
        200,
        {"choices": [{"message": {"role": "assistant", "content": "  你好  "}}]},
    )
    profile = LlmProfile(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="demo",
        api_protocol="chat_completions",
    )
    out = _run_with_transport(transport, profile)
    assert out == "你好"
    assert transport.last_request is not None
    assert transport.last_request.headers["Authorization"] == "Bearer sk-test"
    assert str(transport.last_request.url).endswith("/chat/completions")
    body = json.loads(transport.last_request.content)
    assert "messages" in body
    assert body["max_tokens"] == profile.max_tokens


def test_auth_error() -> None:
    transport = _MockTransport(401, "nope")
    profile = LlmProfile(base_url="https://example.com/v1", api_key="sk-test")
    with pytest.raises(AuthError):
        _run_with_transport(transport, profile)


def test_rate_limit() -> None:
    transport = _MockTransport(429, "slow down")
    profile = LlmProfile(base_url="https://example.com/v1", api_key="sk-test")
    with pytest.raises(RateLimitError):
        _run_with_transport(transport, profile)


def test_endpoint_normalization_chat() -> None:
    p = LlmProfile(base_url="https://api.example.com/v1/", api_protocol="chat_completions")
    assert LlmClient(p)._endpoint() == "https://api.example.com/v1/chat/completions"
    p2 = LlmProfile(
        base_url="https://api.example.com/v1/chat/completions",
        api_protocol="chat_completions",
    )
    assert LlmClient(p2)._endpoint() == "https://api.example.com/v1/chat/completions"


def test_endpoint_normalization_responses() -> None:
    p = LlmProfile(base_url="https://api.example.com/v1", api_protocol="responses")
    assert LlmClient(p)._endpoint() == "https://api.example.com/v1/responses"
    p2 = LlmProfile(
        base_url="https://api.example.com/v1/responses",
        api_protocol="responses",
    )
    assert LlmClient(p2)._endpoint() == "https://api.example.com/v1/responses"
    # Full chat URL pasted while protocol is responses → strip suffix
    p3 = LlmProfile(
        base_url="https://api.example.com/v1/chat/completions",
        api_protocol="responses",
    )
    assert LlmClient(p3)._endpoint() == "https://api.example.com/v1/responses"


def test_responses_protocol_request_and_parse() -> None:
    transport = _MockTransport(
        200,
        {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "  译文  "}],
                }
            ]
        },
    )
    profile = LlmProfile(
        base_url="https://relay.example.com/v1",
        api_key="sk-relay",
        model="gpt-4o",
        api_protocol="responses",
        max_tokens=1024,
        temperature=0.1,
    )
    out = _run_with_transport(
        transport,
        profile,
        messages=[
            {"role": "system", "content": "You are a translator."},
            {"role": "user", "content": "hello"},
        ],
    )
    assert out == "译文"
    assert transport.last_request is not None
    assert str(transport.last_request.url).endswith("/responses")
    body = json.loads(transport.last_request.content)
    assert body["model"] == "gpt-4o"
    assert body["max_output_tokens"] == 1024
    assert body["instructions"] == "You are a translator."
    assert body["input"][0]["role"] == "user"
    assert "messages" not in body


def test_responses_output_text_field() -> None:
    transport = _MockTransport(200, {"output_text": "shortcut reply"})
    profile = LlmProfile(
        base_url="https://relay.example.com/v1",
        api_protocol="responses",
    )
    out = _run_with_transport(transport, profile)
    assert out == "shortcut reply"


def test_legacy_config_defaults_to_chat() -> None:
    # Old configs without api_protocol field
    p = LlmProfile.from_dict(
        {
            "id": "x",
            "name": "old",
            "base_url": "https://x/v1",
            "model": "m",
        }
    )
    assert p.api_protocol == "chat_completions"


def test_invalid_protocol_falls_back() -> None:
    p = LlmProfile.from_dict(
        {
            "id": "x",
            "name": "bad",
            "base_url": "https://x/v1",
            "api_protocol": "whatever",
            "model": "m",
        }
    )
    assert p.api_protocol == "chat_completions"


def test_api_error_status() -> None:
    transport = _MockTransport(500, {"error": "boom"})
    profile = LlmProfile(base_url="https://example.com/v1")
    with pytest.raises(ApiError) as ei:
        _run_with_transport(transport, profile)
    assert ei.value.status_code == 500
