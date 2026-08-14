"""OpenAI-compatible client: Chat Completions + Responses API via httpx."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config.schema import LlmProfile


class LlmError(Exception):
    """Base LLM error."""


class AuthError(LlmError):
    pass


class RateLimitError(LlmError):
    pass


class TimeoutError(LlmError):
    pass


class ApiError(LlmError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmClient:
    def __init__(self, profile: LlmProfile) -> None:
        self.profile = profile

    @property
    def protocol(self) -> str:
        return getattr(self.profile, "api_protocol", None) or "chat_completions"

    def _endpoint(self) -> str:
        base = self.profile.base_url.rstrip("/")
        if self.protocol == "responses":
            if base.endswith("/responses"):
                return base
            # Allow pasting a full chat endpoint by accident
            if base.endswith("/chat/completions"):
                base = base[: -len("/chat/completions")]
            return f"{base}/responses"

        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/responses"):
            base = base[: -len("/responses")]
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        key = (self.profile.api_key or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        model_name = model or self.profile.model
        temp = self.profile.temperature if temperature is None else temperature
        tokens = self.profile.max_tokens if max_tokens is None else max_tokens

        if self.protocol == "responses":
            body = self._build_responses_body(
                messages,
                model=model_name,
                temperature=temp,
                max_tokens=tokens,
            )
        else:
            body = {
                "model": model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": tokens,
                "stream": False,
            }
        return self._request(body)

    def chat_vision(
        self,
        system_prompt: str,
        user_text: str,
        image_png: bytes,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        b64 = base64.b64encode(image_png).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        model_name = model or self.profile.vision_model or self.profile.model
        temp = self.profile.temperature if temperature is None else temperature
        tokens = self.profile.max_tokens if max_tokens is None else max_tokens

        if self.protocol == "responses":
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {
                            "type": "input_image",
                            "image_url": data_url,
                        },
                    ],
                },
            ]
            body = self._build_responses_body(
                messages,
                model=model_name,
                temperature=temp,
                max_tokens=tokens,
                already_responses_content=True,
            )
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ]
            body = {
                "model": model_name,
                "messages": messages,
                "temperature": temp,
                "max_tokens": tokens,
                "stream": False,
            }
        return self._request(body)

    def test_connection(self) -> str:
        """Minimal probe — returns a short reply or raises."""
        return self.chat(
            [
                {
                    "role": "user",
                    "content": "Reply with exactly: ok",
                }
            ],
            max_tokens=16,
            temperature=0,
        )

    def _build_responses_body(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        already_responses_content: bool = False,
    ) -> dict[str, Any]:
        """Map chat-style messages → OpenAI Responses API body.

        - system role → instructions
        - other roles → input items
        - content parts converted to input_text / input_image when needed
        """
        instructions_parts: list[str] = []
        input_items: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    if content.strip():
                        instructions_parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("text"):
                            instructions_parts.append(str(part["text"]))
                        elif isinstance(part, str):
                            instructions_parts.append(part)
                continue

            if already_responses_content and isinstance(content, list):
                input_items.append({"role": role, "content": content})
                continue

            input_items.append(
                {
                    "role": role,
                    "content": self._to_responses_content(content),
                }
            )

        body: dict[str, Any] = {
            "model": model,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "stream": False,
        }
        if instructions_parts:
            body["instructions"] = "\n\n".join(instructions_parts)
        return body

    @staticmethod
    def _to_responses_content(content: Any) -> Any:
        """Convert chat content to Responses content parts when multimodal."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)

        parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                if part is not None:
                    parts.append({"type": "input_text", "text": str(part)})
                continue
            ptype = part.get("type")
            if ptype in ("text", "input_text"):
                parts.append({"type": "input_text", "text": part.get("text", "")})
            elif ptype in ("image_url", "input_image"):
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    url = image_url.get("url", "")
                else:
                    url = image_url or part.get("url", "")
                parts.append({"type": "input_image", "image_url": url})
            elif "text" in part:
                parts.append({"type": "input_text", "text": part.get("text", "")})
            else:
                parts.append(part)
        return parts

    def _request(self, body: dict[str, Any]) -> str:
        timeout = httpx.Timeout(self.profile.timeout_s)
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Request timed out after {self.profile.timeout_s}s") from exc
        except httpx.RequestError as exc:
            raise ApiError(f"Network error: {exc}") from exc

        if resp.status_code in (401, 403):
            raise AuthError(f"Authentication failed ({resp.status_code}): {resp.text[:300]}")
        if resp.status_code == 429:
            raise RateLimitError(f"Rate limited: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise ApiError(
                f"API error {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise ApiError("Invalid JSON in API response") from exc

        content = self._extract_text(data)
        if content is None:
            raise ApiError(f"Unexpected response shape: {str(data)[:300]}")
        return content.strip()

    def _extract_text(self, data: Any) -> str | None:
        """Parse both Chat Completions and Responses response shapes."""
        if not isinstance(data, dict):
            return None

        # ── Responses API convenience field ──
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return str(data["output_text"]).strip()

        # ── Responses API: output[] message content ──
        output = data.get("output")
        if isinstance(output, list):
            texts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                # Skip non-message items (reasoning, function_call, etc.) unless texty
                item_type = item.get("type")
                if item_type and item_type not in ("message", "output_text", "text"):
                    # Still try nested content
                    pass
                content = item.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            ptype = part.get("type", "")
                            if ptype in ("output_text", "text", "input_text"):
                                texts.append(str(part.get("text", "")))
                            elif isinstance(part.get("text"), str):
                                texts.append(part["text"])
                        elif isinstance(part, str):
                            texts.append(part)
                elif isinstance(item.get("text"), str):
                    texts.append(item["text"])
            joined = "".join(texts).strip()
            if joined:
                return joined

        # ── Chat Completions: choices[0].message.content ──
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None

        if content is None:
            # Some relays: choices[0].text
            try:
                content = data["choices"][0]["text"]
            except (KeyError, IndexError, TypeError):
                content = None

        if content is None:
            return None
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("text", "output_text"):
                    parts.append(str(part.get("text", "")))
                elif isinstance(part, str):
                    parts.append(part)
            return "".join(parts)
        return str(content)
