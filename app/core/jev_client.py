"""Jev (TypeSafe System One) decision client.

Jev never generates text. You send a ``state`` plus typed ``questions``
(``choice`` / ``score`` / ``noul``) and get back calibrated, structured
answers. The app uses it purely as an auxiliary judge:

* **scene routing**  — which translation scene fits this text
* **language detection** — resolve ``source_lang == "auto"``
* **quality scoring** — rate a finished translation, optionally retry

Two wire protocols are supported because relays differ:

``native``
    ``POST {base}/v1/systemone`` with ``{state, model, questions}`` —
    TypeSafe's own shape (also served by several relays under
    ``/api/v1/decide``).
``openai``
    ``POST {base}/chat/completions`` asking for a JSON-only reply, for
    relays that only speak Chat Completions.

``api_protocol="auto"`` probes the native endpoints first and falls back
to the OpenAI-compatible one. The winning route is cached per base URL,
so the probe is paid once per process.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config.schema import JevConfig
from app.core.llm_client import (
    ApiError,
    AuthError,
    LlmClient,
    RateLimitError,
    TimeoutError,
)

log = logging.getLogger(__name__)

# Native endpoint paths we probe, in order of likelihood. The official
# host serves /v1/systemone; relay implementations often mirror
# TypeSafe's /api/v1/decide instead.
_NATIVE_PATHS = ("/v1/systemone", "/api/v1/decide", "/v1/decide", "/api/v1/systemone")

# Suffixes stripped from a pasted Base URL before rebuilding endpoints,
# so users can paste the address with or without the endpoint attached.
_STRIPPABLE = ("/chat/completions", "/responses", *_NATIVE_PATHS, "/v1")

# Jev's context budget is ~64k tokens for state + questions combined,
# but our three uses send short inputs; cap defensively.
MAX_STATE_CHARS = 24000

# Quality rubric for the `score` question — ordered low → high.
_QUALITY_LEVELS = [
    "严重错误：漏译、错译或与原文语义不符",
    "多处错误：基本意思可辨，但存在明显误译或生硬表达",
    "基本正确：意思准确，但有少量不自然或不够地道之处",
    "准确流畅：忠实原文且表达自然",
    "准确且地道：完全忠实原文，表达如同母语者撰写",
]


@dataclass(frozen=True)
class _Route:
    kind: str  # "native" | "openai"
    url: str


class _RouteMismatch(ApiError):
    """The endpoint answered, but not in a shape this protocol understands.

    Retryable in ``auto`` mode: the same URL may serve the native body but
    reply with an OpenAI-shaped envelope (or vice versa), and a relay may
    expose the decision path under a different suffix.
    """


# Resolved route per (protocol|base_url) — avoids re-probing each call.
_ROUTE_CACHE: dict[str, _Route] = {}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def base_root(base_url: str) -> str:
    """``https://host/v1`` → ``https://host``; a pasted endpoint is unwound too.

    Stripping repeats until stable so ``/v1/chat/completions`` unwinds all
    the way to the host instead of stopping at ``/v1``.
    """
    raw = (base_url or "").strip().rstrip("/")
    changed = True
    while changed:
        changed = False
        for suffix in _STRIPPABLE:
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)].rstrip("/")
                changed = True
                break
    return raw


def native_candidates(base_url: str) -> list[str]:
    """Native endpoint URLs, most likely first."""
    raw = (base_url or "").strip().rstrip("/")
    # The user pasted the exact decision endpoint — respect it verbatim.
    if raw.endswith("/systemone") or raw.endswith("/decide"):
        return [raw]
    root = base_root(raw)
    if not root:
        return []
    return [f"{root}{path}" for path in _NATIVE_PATHS]


def openai_endpoint(base_url: str) -> str:
    root = base_root(base_url)
    return f"{root}/v1/chat/completions" if root else ""


def _coerce_answer(raw: Any, qtype: str) -> dict[str, Any]:
    """Normalize a bare value from a Chat-Completions relay into a dict."""
    if isinstance(raw, dict):
        return raw
    if qtype == "choice":
        return {"choice": str(raw)}
    if qtype == "noul":
        try:
            return {"noul": float(raw)}
        except (TypeError, ValueError):
            return {"noul": 1.0 if str(raw).strip().lower() in ("yes", "true") else 0.0}
    if qtype == "score":
        try:
            return {"score": float(raw)}
        except (TypeError, ValueError):
            return {}
    return {"value": raw}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a model reply, tolerating code fences."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    fence = _JSON_FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except ValueError:
            return None
    return None


class JevClient:
    """Thin client for Jev's decision API (native + Chat-Completions)."""

    def __init__(self, config: JevConfig) -> None:
        self.config = config

    # ── Configuration ─────────────────────────────────────────────
    @property
    def protocol(self) -> str:
        return getattr(self.config, "api_protocol", None) or "auto"

    def is_configured(self) -> bool:
        """True when a Base URL is present (``enabled`` is checked by callers)."""
        return bool((self.config.base_url or "").strip())

    def _cache_key(self) -> str:
        return f"{self.protocol}|{(self.config.base_url or '').strip().rstrip('/')}"

    def _routes(self) -> list[_Route]:
        proto = self.protocol
        base = self.config.base_url
        if proto == "native":
            return [_Route("native", u) for u in native_candidates(base)]
        if proto == "openai":
            url = openai_endpoint(base)
            return [_Route("openai", url)] if url else []
        routes = [_Route("native", u) for u in native_candidates(base)]
        url = openai_endpoint(base)
        if url:
            routes.append(_Route("openai", url))
        return routes

    def _candidate_routes(self) -> list[_Route]:
        routes = self._routes()
        cached = _ROUTE_CACHE.get(self._cache_key())
        if cached and cached in routes:
            return [cached] + [r for r in routes if r != cached]
        return routes

    # ── Transport ─────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        key = (self.config.api_key or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _post(self, url: str, body: dict[str, Any]) -> Any:
        timeout = httpx.Timeout(self.config.timeout_s)
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=self._headers(), json=body)
        except httpx.TimeoutException as exc:
            log.warning("jev request timed out after %ss", self.config.timeout_s)
            raise TimeoutError(
                f"Jev 请求超时（{self.config.timeout_s}s）"
            ) from exc
        except httpx.RequestError as exc:
            log.warning("jev network error: %s", exc)
            raise ApiError(f"Jev 网络错误：{exc}") from exc

        if resp.status_code in (401, 403):
            raise AuthError(f"Jev 认证失败（{resp.status_code}）：{resp.text[:200]}")
        if resp.status_code == 429:
            raise RateLimitError(f"Jev 触发限流：{resp.text[:200]}")
        if resp.status_code >= 400:
            raise ApiError(
                f"Jev 接口错误 {resp.status_code}：{resp.text[:300]}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError("Jev 返回的不是合法 JSON") from exc

    # ── Core decision call ────────────────────────────────────────
    def decide(
        self,
        state: str,
        questions: dict[str, dict[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Ask Jev typed questions about ``state``; returns answers by question id."""
        if not questions:
            return {}
        if isinstance(state, str) and len(state) > MAX_STATE_CHARS:
            state = state[:MAX_STATE_CHARS] + "…[truncated]"

        model_name = model or self.config.model or "jev-latest"
        errors: list[str] = []
        routes = self._candidate_routes()
        if not routes:
            raise ApiError("Jev Base URL 未配置")

        for route in routes:
            try:
                if route.kind == "native":
                    answers = self._decide_native(route.url, state, questions, model_name)
                else:
                    answers = self._decide_openai(route.url, state, questions, model_name)
            except (AuthError, RateLimitError, TimeoutError):
                # Credentials / quota / reachability: another path won't help.
                raise
            except ApiError as exc:
                # 404/405 = wrong path, 400/422 = wrong body shape, and an
                # unparseable envelope all mean "try the next route".
                if isinstance(exc, _RouteMismatch) or exc.status_code in (400, 404, 405, 422):
                    log.info("jev route failed (%s): %s", route.url, exc)
                    errors.append(f"{route.url} → {exc}")
                    continue
                raise
            _ROUTE_CACHE[self._cache_key()] = route
            return answers

        detail = "；".join(errors) if errors else "无可用端点"
        raise ApiError(f"Jev 无可用的接口地址：{detail}")

    def _decide_native(
        self,
        url: str,
        state: str,
        questions: dict[str, dict[str, Any]],
        model: str,
    ) -> dict[str, dict[str, Any]]:
        data = self._post(url, {"state": state, "model": model, "questions": questions})
        if not isinstance(data, dict):
            raise _RouteMismatch(f"Jev 响应结构异常：{str(data)[:200]}")

        answers = data.get("answers")
        if not isinstance(answers, dict):
            # Some relays wrap the native payload one level down.
            for key in ("result", "data", "output"):
                inner = data.get(key)
                if isinstance(inner, dict) and isinstance(inner.get("answers"), dict):
                    answers = inner["answers"]
                    break

        if isinstance(answers, dict):
            return {k: v for k, v in answers.items() if isinstance(v, dict)}

        # Same URL, OpenAI-shaped envelope: {choices:[{message:{content:"{...}"}}]}
        # or {output_text: "..."}. Parse the JSON out of the text instead.
        salvaged = self._answers_from_text_envelope(data, questions)
        if salvaged is not None:
            return salvaged
        raise _RouteMismatch(f"Jev 响应缺少 answers：{str(data)[:200]}")

    def _answers_from_text_envelope(
        self,
        data: Any,
        questions: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]] | None:
        """Coerce an OpenAI/Responses-shaped reply into the answers map."""
        content = self._openai_content(data)
        if content is None:
            return None
        parsed = _extract_json_object(content)
        if parsed is None:
            return None
        answers_raw = parsed.get("answers") if isinstance(parsed.get("answers"), dict) else parsed
        if not isinstance(answers_raw, dict):
            return None
        out: dict[str, dict[str, Any]] = {}
        for qid, spec in questions.items():
            if qid in answers_raw:
                out[qid] = _coerce_answer(answers_raw[qid], str(spec.get("type", "")))
        return out

    def _decide_openai(
        self,
        url: str,
        state: str,
        questions: dict[str, dict[str, Any]],
        model: str,
    ) -> dict[str, dict[str, Any]]:
        system = (
            "You are a structured decision engine. You never write prose or "
            "explain yourself. Given a state and a map of typed questions, "
            "reply with ONLY a JSON object that maps each question id to its "
            'answer: choice → {"choice": "<one of the criteria keys>"}, '
            'score → {"score": <number>}, '
            'noul → {"noul": <probability between 0 and 1>}. '
            "Use exactly the question ids given. No markdown, no code fences, "
            "no commentary."
        )
        user = json.dumps({"state": state, "questions": questions}, ensure_ascii=False)
        data = self._post(
            url,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "stream": False,
            },
        )
        # Native envelope served on a Chat-Completions URL: accept it too.
        if isinstance(data, dict) and isinstance(data.get("answers"), dict):
            return {k: v for k, v in data["answers"].items() if isinstance(v, dict)}

        salvaged = self._answers_from_text_envelope(data, questions)
        if salvaged is not None:
            return salvaged
        raise _RouteMismatch(f"Jev 未返回可解析的答案：{str(data)[:200]}")

    @staticmethod
    def _openai_content(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "".join(
                        str(p.get("text", ""))
                        for p in content
                        if isinstance(p, dict)
                    )
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        return None

    # ── High-level helpers (the three product features) ───────────
    def detect_language(self, text: str, languages: list[tuple[str, str]]) -> str | None:
        """Pick the source language code from ``languages`` ([(code, label)])."""
        snippet = (text or "").strip()
        if not snippet or not languages:
            return None
        criteria = {code: label for code, label in languages}
        answers = self.decide(
            snippet,
            {
                "source_language": {
                    "type": "choice",
                    "instructions": (
                        "Which language is this text written in? Choose the single "
                        "best match. Ignore code, URLs and numbers when deciding."
                    ),
                    "criteria": criteria,
                }
            },
        )
        answer = answers.get("source_language") or {}
        picked = str(answer.get("choice", "")).strip()
        if picked in criteria:
            return picked
        # Relays occasionally echo the label instead of the key.
        for code, label in languages:
            if picked and picked == label:
                return code
        return None

    def route_scene(self, text: str, scenes: list[tuple[str, str, str]]) -> str | None:
        """Pick the best scene id from ``scenes`` ([(id, label, prompt_hint)])."""
        snippet = (text or "").strip()
        if not snippet or not scenes:
            return None
        criteria: dict[str, str] = {}
        for sid, label, hint in scenes:
            description = label
            if hint.strip():
                description = f"{label}：{hint.strip()}"
            criteria[sid] = description
        answers = self.decide(
            snippet,
            {
                "scene": {
                    "type": "choice",
                    "instructions": (
                        "Which translation style fits this text best? "
                        "Judge by the domain, register and intended audience."
                    ),
                    "criteria": criteria,
                }
            },
        )
        answer = answers.get("scene") or {}
        picked = str(answer.get("choice", "")).strip()
        return picked if picked in criteria else None

    def score_quality(self, source: str, translation: str) -> float | None:
        """Rate a translation 0..1 (higher is better); None when unavailable."""
        src = (source or "").strip()
        dst = (translation or "").strip()
        if not src or not dst:
            return None
        state = json.dumps(
            {"source": src[:12000], "translation": dst[:12000]},
            ensure_ascii=False,
        )
        answers = self.decide(
            state,
            {
                "quality": {
                    "type": "score",
                    "instructions": (
                        "Rate the translation against the source. Consider "
                        "faithfulness, completeness, fluency and naturalness."
                    ),
                    "criteria": _QUALITY_LEVELS,
                }
            },
        )
        answer = answers.get("quality") or {}
        raw = answer.get("score")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        top = len(_QUALITY_LEVELS) - 1
        if top <= 0:
            return None
        return max(0.0, min(value / top, 1.0))

    # ── Diagnostics (settings dialog) ─────────────────────────────
    def test_connection(self) -> str:
        """Round-trip a trivial question; returns a human-readable result."""
        answers = self.decide(
            "Hello, world.",
            {
                "english": {
                    "type": "noul",
                    "instructions": "Is this text written in English?",
                }
            },
        )
        answer = answers.get("english") or {}
        noul = answer.get("noul")
        if noul is None:
            raise ApiError("Jev 已响应，但未返回预期字段")
        return f"Jev 连接正常 · 模型 {self.config.model} · 置信度 {float(noul):.2f}"

    def list_models(self) -> list[str]:
        """Fetch model ids (TypeSafe ``/v1/models`` or OpenAI-style list)."""
        root = base_root(self.config.base_url)
        if not root:
            raise ApiError("Jev Base URL 未配置")
        last_error: Exception | None = None
        for url in (f"{root}/v1/models", f"{root}/models"):
            timeout = httpx.Timeout(self.config.timeout_s)
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(url, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"Jev 请求超时（{self.config.timeout_s}s）") from exc
            except httpx.RequestError as exc:
                raise ApiError(f"Jev 网络错误：{exc}") from exc

            if resp.status_code in (401, 403):
                raise AuthError(f"Jev 认证失败（{resp.status_code}）：{resp.text[:200]}")
            if resp.status_code >= 400:
                last_error = ApiError(
                    f"Jev 接口错误 {resp.status_code}：{resp.text[:200]}",
                    status_code=resp.status_code,
                )
                continue
            try:
                data = resp.json()
            except ValueError as exc:
                raise ApiError("Jev 返回的不是合法 JSON") from exc
            models = LlmClient._extract_model_ids(data)
            if models:
                return models
            last_error = ApiError("Jev 模型列表为空")
        if last_error:
            raise last_error
        raise ApiError("Jev 模型列表不可用")
