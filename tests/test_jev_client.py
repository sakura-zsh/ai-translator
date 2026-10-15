"""Tests for the Jev (System One) decision client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.config.schema import JevConfig
from app.core.jev_client import (
    JevClient,
    base_root,
    native_candidates,
    openai_endpoint,
)
from app.core.llm_client import ApiError, AuthError


@pytest.fixture(autouse=True)
def _clear_route_cache() -> Any:
    """Route resolution is cached per base URL — isolate every test."""
    from app.core import jev_client

    jev_client._ROUTE_CACHE.clear()
    yield
    jev_client._ROUTE_CACHE.clear()


class _RouteTransport(httpx.BaseTransport):
    """Answers per exact URL path; anything unmatched returns 404."""

    def __init__(self, routes: dict[str, tuple[int, Any]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        # Exact-path matching: suffix tests are fooled because
        # "/api/v1/systemone" also ends with "/v1/systemone".
        for fragment, (status, body) in self.routes.items():
            if path == fragment:
                if isinstance(body, str):
                    return httpx.Response(
                        status,
                        content=body.encode(),
                        headers={"content-type": "text/plain"},
                        request=request,
                    )
                return httpx.Response(
                    status,
                    content=json.dumps(body).encode(),
                    headers={"content-type": "application/json"},
                    request=request,
                )
        return httpx.Response(
            404,
            content=b'{"error":"not found"}',
            headers={"content-type": "application/json"},
            request=request,
        )


def _client(config: JevConfig, transport: _RouteTransport) -> JevClient:
    """The transport is injected in ``_run``; kept here for readability."""
    return JevClient(config)


def _run(client: JevClient, transport: _RouteTransport, fn: Any) -> Any:
    real = httpx.Client

    class _Patched(real):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    with patch("app.core.jev_client.httpx.Client", _Patched):
        return fn()


ANSWER = {
    "model": "jev-latest",
    "answers": {
        "q": {"type": "noul", "noul": 0.97},
        "route": {"type": "choice", "choice": "billing", "confidence": 0.9},
        "quality": {"type": "score", "score": 3.0, "confidence": 0.8},
    },
    "usage": {"input_tokens": 12, "output_tokens": 3},
}

QUESTIONS = {
    "q": {"type": "noul", "instructions": "Is it?"},
    "route": {"type": "choice", "instructions": "Where?", "criteria": {"billing": "x"}},
    "quality": {"type": "score", "instructions": "How good?", "criteria": ["a", "b", "c", "d"]},
}


# ── URL normalization ─────────────────────────────────────────────
def test_base_root_unwinds_pasted_endpoints() -> None:
    assert base_root("https://api.typesafe.ai") == "https://api.typesafe.ai"
    assert base_root("https://api.typesafe.ai/v1") == "https://api.typesafe.ai"
    assert base_root("https://api.typesafe.ai/v1/systemone") == "https://api.typesafe.ai"
    assert base_root("https://relay.test/api/v1/decide") == "https://relay.test"
    assert base_root("https://relay.test/v1/chat/completions") == "https://relay.test"
    assert base_root("  https://relay.test/v1/  ") == "https://relay.test"


def test_native_candidates_prefer_systemone() -> None:
    assert native_candidates("https://api.typesafe.ai")[0] == (
        "https://api.typesafe.ai/v1/systemone"
    )
    # v1 is not duplicated when the user already pasted it.
    assert native_candidates("https://api.typesafe.ai/v1")[0] == (
        "https://api.typesafe.ai/v1/systemone"
    )
    # A pasted decision endpoint is used verbatim, not re-derived.
    assert native_candidates("https://relay.test/api/v1/decide") == [
        "https://relay.test/api/v1/decide"
    ]


def test_openai_endpoint() -> None:
    assert openai_endpoint("https://relay.test/v1") == (
        "https://relay.test/v1/chat/completions"
    )
    assert openai_endpoint("") == ""


# ── Configuration gate ────────────────────────────────────────────
def test_base_url_is_not_hardcoded() -> None:
    """The whole point: no default address, the user supplies the relay."""
    assert JevConfig().base_url == ""
    client = JevClient(JevConfig())
    assert client.is_configured() is False
    client = JevClient(JevConfig(base_url="https://relay.test/v1"))
    assert client.is_configured() is True


# ── Native protocol ───────────────────────────────────────────────
def test_decide_native_parses_answers() -> None:
    transport = _RouteTransport({"/v1/systemone": (200, ANSWER)})
    client = _client(JevConfig(base_url="https://relay.test", api_key="k"), transport)

    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))

    assert answers["q"]["noul"] == 0.97
    assert answers["route"]["choice"] == "billing"
    req = transport.requests[0]
    assert str(req.url) == "https://relay.test/v1/systemone"
    assert req.headers["Authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["state"] == "hi"
    assert body["model"] == "jev-latest"
    assert set(body["questions"]) == set(QUESTIONS)


def test_decide_native_accepts_openai_shaped_envelope() -> None:
    """Same URL, Chat-Completions envelope — parse the JSON out of content."""
    transport = _RouteTransport(
        {
            "/v1/systemone": (
                200,
                {"choices": [{"message": {"content": json.dumps(ANSWER)}}]},
            )
        }
    )
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["q"]["noul"] == 0.97


def test_decide_native_accepts_wrapped_payload() -> None:
    transport = _RouteTransport({"/v1/systemone": (200, {"data": ANSWER})})
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["route"]["choice"] == "billing"


def test_auto_falls_back_to_next_endpoint_then_openai() -> None:
    """Native paths 404 → later native path answers; nothing crashed."""
    transport = _RouteTransport(
        {
            "/v1/systemone": (404, {"error": "no"}),
            "/api/v1/decide": (404, {"error": "no"}),
            "/v1/decide": (404, {"error": "no"}),
            "/api/v1/systemone": (200, ANSWER),
        }
    )
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["q"]["noul"] == 0.97
    assert str(transport.requests[-1].url).endswith("/api/v1/systemone")


def test_auto_falls_back_to_chat_completions() -> None:
    """Every native path fails → OpenAI-compatible route wins."""
    transport = _RouteTransport(
        {"/v1/chat/completions": (200, {"choices": [{"message": {"content": json.dumps(ANSWER)}}]})}
    )
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["route"]["choice"] == "billing"
    assert str(transport.requests[-1].url).endswith("/v1/chat/completions")


def test_route_is_cached_after_first_success() -> None:
    transport = _RouteTransport({"/v1/systemone": (200, ANSWER)})
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    first = len(transport.requests)
    _run(client, transport, lambda: client.decide("hi again", QUESTIONS))
    # Second call goes straight to the cached route — exactly one more request.
    assert len(transport.requests) == first + 1


def test_pinned_native_protocol_does_not_try_openai() -> None:
    transport = _RouteTransport(
        {"/v1/chat/completions": (200, {"choices": [{"message": {"content": "{}"}}]})}
    )
    client = _client(
        JevConfig(base_url="https://relay.test", api_protocol="native"), transport
    )
    with pytest.raises(ApiError):
        _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert all("chat/completions" not in str(r.url) for r in transport.requests)


def test_auth_error_is_not_retried_on_other_routes() -> None:
    transport = _RouteTransport({"/v1/systemone": (401, {"error": "bad key"})})
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    with pytest.raises(AuthError):
        _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert len(transport.requests) == 1


def test_openai_protocol_sends_json_instruction() -> None:
    transport = _RouteTransport(
        {"/v1/chat/completions": (200, {"choices": [{"message": {"content": json.dumps(ANSWER)}}]})}
    )
    client = _client(
        JevConfig(base_url="https://relay.test", api_protocol="openai"), transport
    )
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["quality"]["score"] == 3.0
    body = json.loads(transport.requests[0].content)
    assert body["messages"][0]["role"] == "system"
    assert "JSON" in body["messages"][0]["content"]


def test_openai_protocol_salvages_bare_values() -> None:
    """A relay may answer with bare values instead of typed objects."""
    transport = _RouteTransport(
        {
            "/v1/chat/completions": (
                200,
                {"choices": [{"message": {"content": '{"route": "billing", "q": 0.8}'}}]},
            )
        }
    )
    client = _client(
        JevConfig(base_url="https://relay.test", api_protocol="openai"), transport
    )
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["route"]["choice"] == "billing"
    assert answers["q"]["noul"] == 0.8


def test_openai_fenced_json_is_parsed() -> None:
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    transport = _RouteTransport(
        {"/v1/chat/completions": (200, {"choices": [{"message": {"content": fenced}}]})}
    )
    client = _client(
        JevConfig(base_url="https://relay.test", api_protocol="openai"), transport
    )
    answers = _run(client, transport, lambda: client.decide("hi", QUESTIONS))
    assert answers["q"]["noul"] == 0.97


# ── High-level features ───────────────────────────────────────────
def _stub_decide(monkeypatch: Any, payload: dict[str, dict[str, Any]]) -> None:
    monkeypatch.setattr(JevClient, "decide", lambda self, *a, **k: payload)


def test_detect_language_returns_code(monkeypatch: Any) -> None:
    _stub_decide(monkeypatch, {"source_language": {"choice": "ja"}})
    client = JevClient(JevConfig(base_url="https://x/v1"))
    assert client.detect_language("こんにちは", [("zh", "Chinese"), ("ja", "Japanese")]) == "ja"


def test_detect_language_accepts_label_echo(monkeypatch: Any) -> None:
    _stub_decide(monkeypatch, {"source_language": {"choice": "Japanese"}})
    client = JevClient(JevConfig(base_url="https://x/v1"))
    assert client.detect_language("こんにちは", [("ja", "Japanese")]) == "ja"


def test_detect_language_rejects_unknown_choice(monkeypatch: Any) -> None:
    _stub_decide(monkeypatch, {"source_language": {"choice": "klingon"}})
    client = JevClient(JevConfig(base_url="https://x/v1"))
    assert client.detect_language("x", [("ja", "Japanese")]) is None


def test_route_scene_returns_valid_id(monkeypatch: Any) -> None:
    _stub_decide(monkeypatch, {"scene": {"choice": "technical"}})
    client = JevClient(JevConfig(base_url="https://x/v1"))
    scenes = [("general", "通用", ""), ("technical", "技术文档", "保留代码原文")]
    assert client.route_scene("def f(): ...", scenes) == "technical"


def test_score_quality_normalizes_to_unit_range() -> None:
    client = JevClient(JevConfig(base_url="https://x/v1"))

    # 4 levels → top index 4; a score of 4 normalizes to 1.0.
    for raw, expected in ((4.0, 1.0), (2.0, 0.5), (0.0, 0.0), (99.0, 1.0)):
        client.decide = lambda *a, _r=raw, **k: {"quality": {"score": _r}}  # type: ignore[method-assign]
        assert client.score_quality("src", "dst") == expected


def test_score_quality_missing_field_returns_none() -> None:
    client = JevClient(JevConfig(base_url="https://x/v1"))
    client.decide = lambda *a, **k: {"quality": {}}  # type: ignore[method-assign]
    assert client.score_quality("src", "dst") is None


def test_helpers_short_circuit_on_empty_input() -> None:
    client = JevClient(JevConfig(base_url="https://x/v1"))
    assert client.detect_language("", [("en", "English")]) is None
    assert client.route_scene("  ", [("general", "通用", "")]) is None
    assert client.score_quality("src", "") is None


# ── Diagnostics ───────────────────────────────────────────────────
def test_test_connection_reports_model() -> None:
    transport = _RouteTransport(
        {"/v1/systemone": (200, {"answers": {"english": {"type": "noul", "noul": 0.99}}})}
    )
    client = _client(JevConfig(base_url="https://relay.test", model="jev-1.13.0"), transport)
    message = _run(client, transport, client.test_connection)
    assert "jev-1.13.0" in message
    assert "0.99" in message


def test_list_models_reads_typesafe_shape() -> None:
    transport = _RouteTransport(
        {
            "/v1/models": (
                200,
                {"models": [{"name": "jev-latest"}, {"name": "jev-1.13.0"}]},
            )
        }
    )
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    models = _run(client, transport, client.list_models)
    assert models == ["jev-1.13.0", "jev-latest"]


def test_list_models_reads_openai_shape() -> None:
    transport = _RouteTransport(
        {"/models": (200, {"data": [{"id": "jev-latest"}]})}
    )
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    models = _run(client, transport, client.list_models)
    assert models == ["jev-latest"]


def test_decide_without_base_url_raises() -> None:
    client = JevClient(JevConfig())
    with pytest.raises(ApiError):
        client.decide("hi", QUESTIONS)


def test_long_state_is_truncated() -> None:
    transport = _RouteTransport({"/v1/systemone": (200, ANSWER)})
    client = _client(JevConfig(base_url="https://relay.test"), transport)
    _run(client, transport, lambda: client.decide("x" * 40000, QUESTIONS))
    body = json.loads(transport.requests[0].content)
    assert len(body["state"]) < 40000
    assert body["state"].endswith("[truncated]")
