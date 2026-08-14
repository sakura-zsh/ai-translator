"""Configuration dataclasses and defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex[:12]


ApiProtocol = Literal["chat_completions", "responses"]


@dataclass
class LlmProfile:
    id: str = field(default_factory=_new_id)
    name: str = "OpenAI-compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    # chat_completions: /v1/chat/completions
    # responses:        /v1/responses  (OpenAI Responses API / 多数中转站)
    api_protocol: ApiProtocol = "chat_completions"
    model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    temperature: float = 0.2
    timeout_s: float = 60.0
    max_tokens: int = 4096

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmProfile:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        proto = kwargs.get("api_protocol", "chat_completions")
        if proto not in ("chat_completions", "responses"):
            kwargs["api_protocol"] = "chat_completions"
        return cls(**kwargs)


@dataclass
class TranslationConfig:
    source_lang: str = "auto"
    target_lang: str = "zh"
    image_mode: Literal["ocr", "vision"] = "ocr"
    supplementary_prompt: str = ""
    ocr_langs: str = "eng+chi_sim"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslationConfig:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        mode = kwargs.get("image_mode", "ocr")
        if mode not in ("ocr", "vision"):
            kwargs["image_mode"] = "ocr"
        return cls(**kwargs)


@dataclass
class HotkeysConfig:
    translate: str = "Ctrl+Return"
    screenshot: str = "Ctrl+Shift+S"
    paste_image: str = "Ctrl+Shift+V"
    swap_langs: str = "Ctrl+Shift+X"
    copy_result: str = "Ctrl+Shift+C"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotkeysConfig:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class UiConfig:
    theme: Literal["dark", "light"] = "dark"
    window_width: int = 920
    window_height: int = 640
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UiConfig:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "hotkeys"}
        theme = kwargs.get("theme", "dark")
        if theme not in ("dark", "light"):
            kwargs["theme"] = "dark"
        hotkeys_data = data.get("hotkeys") or {}
        if isinstance(hotkeys_data, dict):
            kwargs["hotkeys"] = HotkeysConfig.from_dict(hotkeys_data)
        return cls(**kwargs)


HISTORY_LIMIT = 10
_HISTORY_TEXT_MAX = 4000


@dataclass
class HistoryEntry:
    id: str = field(default_factory=_new_id)
    ts: float = 0.0
    source_lang: str = "auto"
    target_lang: str = "zh"
    mode: str = "text"  # text / ocr / vision
    source_text: str = ""
    result_text: str = ""
    model: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)

    def menu_label(self) -> str:
        src = " ".join((self.source_text or "").split())
        if not src:
            src = f"[{self.mode}]"
        if len(src) > 36:
            src = src[:36] + "…"
        return f"{self.source_lang}→{self.target_lang}  {src}"


@dataclass
class AppConfig:
    version: int = 1
    active_profile_id: str = "default"
    profiles: list[LlmProfile] = field(default_factory=list)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    history: list[HistoryEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.profiles:
            self.profiles = [
                LlmProfile(id="default", name="OpenAI-compatible"),
            ]
            self.active_profile_id = "default"
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[:HISTORY_LIMIT]

    @classmethod
    def default(cls) -> AppConfig:
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        profiles_raw = data.get("profiles") or []
        profiles = [
            LlmProfile.from_dict(p) for p in profiles_raw if isinstance(p, dict)
        ]
        if not profiles:
            profiles = [LlmProfile(id="default", name="OpenAI-compatible")]

        translation_raw = data.get("translation") or {}
        ui_raw = data.get("ui") or {}
        history_raw = data.get("history") or []
        history = [
            HistoryEntry.from_dict(h) for h in history_raw if isinstance(h, dict)
        ][:HISTORY_LIMIT]

        active = data.get("active_profile_id") or profiles[0].id
        if not any(p.id == active for p in profiles):
            active = profiles[0].id

        return cls(
            version=int(data.get("version", 1)),
            active_profile_id=active,
            profiles=profiles,
            translation=TranslationConfig.from_dict(
                translation_raw if isinstance(translation_raw, dict) else {}
            ),
            ui=UiConfig.from_dict(ui_raw if isinstance(ui_raw, dict) else {}),
            history=history,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def push_history(
        self,
        *,
        source_lang: str,
        target_lang: str,
        mode: str,
        source_text: str,
        result_text: str,
        model: str = "",
        ts: float | None = None,
    ) -> HistoryEntry:
        import time as _time

        entry = HistoryEntry(
            ts=float(ts if ts is not None else _time.time()),
            source_lang=source_lang or "auto",
            target_lang=target_lang or "zh",
            mode=mode or "text",
            source_text=(source_text or "")[:_HISTORY_TEXT_MAX],
            result_text=(result_text or "")[:_HISTORY_TEXT_MAX],
            model=model or "",
        )
        # newest first; drop near-duplicates of the latest entry
        if self.history:
            last = self.history[0]
            if (
                last.source_text == entry.source_text
                and last.result_text == entry.result_text
                and last.source_lang == entry.source_lang
                and last.target_lang == entry.target_lang
            ):
                self.history[0] = entry
                return entry
        self.history.insert(0, entry)
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[:HISTORY_LIMIT]
        return entry

    def clear_history(self) -> None:
        self.history = []

    def get_history(self, entry_id: str) -> HistoryEntry | None:
        for entry in self.history:
            if entry.id == entry_id:
                return entry
        return None

    def get_active_profile(self) -> LlmProfile:
        for profile in self.profiles:
            if profile.id == self.active_profile_id:
                return profile
        return self.profiles[0]

    def get_profile(self, profile_id: str) -> LlmProfile | None:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def upsert_profile(self, profile: LlmProfile) -> None:
        for i, existing in enumerate(self.profiles):
            if existing.id == profile.id:
                self.profiles[i] = profile
                return
        self.profiles.append(profile)

    def remove_profile(self, profile_id: str) -> bool:
        if len(self.profiles) <= 1:
            return False
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        if len(self.profiles) == before:
            return False
        if self.active_profile_id == profile_id:
            self.active_profile_id = self.profiles[0].id
        return True
