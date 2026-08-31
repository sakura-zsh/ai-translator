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


def _run_vision_with_transport(
    transport: _MockTransport,
    profile: LlmProfile,
    image: bytes,
) -> str:
    client = LlmClient(profile)
    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    with patch("app.core.llm_client.httpx.Client", _PatchedClient):
        return client.chat_vision("system prompt", "translate this", image)


def test_chat_vision_data_url_mime_follows_payload() -> None:
    # JPEG magic bytes → data URL must say image/jpeg (payload may be JPEG
    # after downscale_for_vision compression).
    transport = _MockTransport(
        200, {"choices": [{"message": {"content": "ok"}}]}
    )
    profile = LlmProfile(base_url="https://example.com/v1", api_key="k")
    _run_vision_with_transport(transport, profile, b"\xff\xd8\xff\xe0fakejpeg")
    body = json.loads(transport.last_request.content)
    url = body["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_chat_vision_png_payload_keeps_png_mime() -> None:
    transport = _MockTransport(
        200, {"choices": [{"message": {"content": "ok"}}]}
    )
    profile = LlmProfile(base_url="https://example.com/v1", api_key="k")
    _run_vision_with_transport(transport, profile, b"\x89PNG\r\n\x1a\nfakepng")
    body = json.loads(transport.last_request.content)
    url = body["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


# ── list_models ───────────────────────────────────────────────────
def _run_models_with_transport(transport: _MockTransport, profile: LlmProfile) -> list[str]:
    client = LlmClient(profile)
    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    with patch("app.core.llm_client.httpx.Client", _PatchedClient):
        return client.list_models()


def test_list_models_openai_shape() -> None:
    transport = _MockTransport(
        200,
        {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "gpt-4o"}]},
    )
    profile = LlmProfile(base_url="https://api.example.com/v1", api_key="sk-x")
    models = _run_models_with_transport(transport, profile)
    assert models == ["gpt-4o", "gpt-4o-mini"]  # sorted, deduped
    assert str(transport.last_request.url).endswith("/v1/models")
    assert transport.last_request.headers["Authorization"] == "Bearer sk-x"


def test_list_models_ollama_style() -> None:
    transport = _MockTransport(200, {"models": [{"name": "llava"}, {"name": "llama3.2"}]})
    profile = LlmProfile(base_url="http://127.0.0.1:11434/v1")
    assert _run_models_with_transport(transport, profile) == ["llama3.2", "llava"]


def test_list_models_auth_error() -> None:
    transport = _MockTransport(401, "bad key")
    profile = LlmProfile(base_url="https://api.example.com/v1", api_key="wrong")
    with pytest.raises(AuthError):
        _run_models_with_transport(transport, profile)


def test_list_models_empty_list_raises() -> None:
    transport = _MockTransport(200, {"data": []})
    profile = LlmProfile(base_url="https://api.example.com/v1")
    with pytest.raises(ApiError):
        _run_models_with_transport(transport, profile)


def test_models_endpoint_strips_pasted_suffix() -> None:
    p = LlmProfile(
        base_url="https://api.example.com/v1/chat/completions",
        api_protocol="chat_completions",
    )
    assert LlmClient(p)._models_endpoint() == "https://api.example.com/v1/models"


# ── reasoning leakage (chain-of-thought) ──────────────────────────
def test_chat_strips_think_block() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": "<think>We need to translate... hmm</think>\n译文内容"
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "译文内容"


def test_chat_strips_multiple_and_unclosed_think_blocks() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": "<think>a</think>中间<think>b</think>最终结果"
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "中间最终结果"

    transport2 = _MockTransport(
        200,
        {"choices": [{"message": {"content": "好开头<think>被截断的思维链"}}]},
    )
    assert _run_with_transport(transport2, profile) == "好开头"


def test_chat_only_think_block_raises() -> None:
    transport = _MockTransport(
        200,
        {"choices": [{"message": {"content": "<think>只有思维链</think>"}}]},
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    with pytest.raises(ApiError, match="only reasoning"):
        _run_with_transport(transport, profile)


def test_chat_plain_content_not_mangled() -> None:
    # HTML-ish text must survive; only the specific reasoning tags are stripped.
    transport = _MockTransport(
        200,
        {"choices": [{"message": {"content": "<b>Bold</b> <note>note</note>"}}]},
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert (
        _run_with_transport(transport, profile)
        == "<b>Bold</b> <note>note</note>"
    )


def test_strip_reasoning_tag_variants() -> None:
    from app.core.llm_client import strip_reasoning

    assert strip_reasoning("<thinking>x</thinking>ans") == "ans"
    assert strip_reasoning("<REASONING>x</REASONING>ans") == "ans"
    assert strip_reasoning("<think arg='1'>x</think >  ans  ") == "ans"
    assert strip_reasoning("no tags here") == "no tags here"


def test_responses_reasoning_items_skipped() -> None:
    transport = _MockTransport(
        200,
        {
            "output": [
                {"type": "reasoning", "summary": [{"text": "thinking..."}]},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "最终译文"}],
                },
            ]
        },
    )
    profile = LlmProfile(
        base_url="https://relay.example.com/v1",
        api_protocol="responses",
        model="m",
    )
    assert _run_with_transport(transport, profile) == "最终译文"


# ── <final_translation> tag extraction ────────────────────────────
def test_tagged_extraction_beats_reasoning_before_answer() -> None:
    """Exact repro of the field report: CoT then answer, no <think> tags."""
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            'This input is in English: "this is". The instruction '
                            "says if the input is already in English, reverse the "
                            'direction. "this is" is a short English phrase, so '
                            "translate into Simplified Chinese. "
                            "<final_translation>这是</final_translation>"
                        )
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "这是"


def test_tagged_extraction_multiline_and_surrounding_chatter() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            "Let me think...\n<final_translation>\n"
                            "line one\nline two\n\n</final_translation>\n"
                            "I checked the formatting."
                        )
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "line one\nline two"


def test_tagged_extraction_first_non_empty_pair_wins() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            "<final_translation></final_translation>"
                            "<final_translation>答案</final_translation>"
                        )
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "答案"


def test_tagged_unclosed_tag_falls_back_to_rest() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": "thinking... <final_translation>截断的答案"
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "截断的答案"


def test_tagged_extraction_inside_tag_reasoning_stripped() -> None:
    transport = _MockTransport(
        200,
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            "<final_translation><think>oops</think>译文"
                            "</final_translation>"
                        )
                    }
                }
            ]
        },
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "译文"


def test_no_tags_falls_back_to_legacy_behavior() -> None:
    transport = _MockTransport(
        200,
        {"choices": [{"message": {"content": "普通回复，没有标签"}}]},
    )
    profile = LlmProfile(base_url="https://example.com/v1", model="m")
    assert _run_with_transport(transport, profile) == "普通回复，没有标签"


def test_extract_tagged_final_unit() -> None:
    from app.core.llm_client import extract_tagged_final

    assert extract_tagged_final("x<final_translation> A </final_translation>") == "A"
    assert extract_tagged_final(
        "<FINAL_TRANSLATION>case</FINAL_TRANSLATION>"
    ) == "case"
    assert extract_tagged_final("<final_translation>open") == "open"
    assert extract_tagged_final("no tags") == ""
