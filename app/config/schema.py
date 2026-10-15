"""Configuration dataclasses and defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex[:12]


ApiProtocol = Literal["chat_completions", "responses"]
JevProtocol = Literal["auto", "native", "openai"]


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


CUSTOM_SCENES_MAX = 20


JEV_QUALITY_THRESHOLD_DEFAULT = 0.6


@dataclass
class JevConfig:
    """Jev — TypeSafe 的 System One 决策模型（辅助判断，不做翻译）。

    Jev 不吃 ``messages``：它接收一段 ``state`` 和一组带类型的
    ``questions``（choice / score / noul），返回带置信概率的结构化答案。
    本应用用它做三件事：场景自动路由、源语言检测、译文质量评分。

    ``base_url`` 故意留空：官方地址是 ``https://api.typesafe.ai``，但
    用户多经由中转站调用，硬编码反而添乱，一律由用户在设置里填。
    """

    enabled: bool = False
    # 留空 = 未配置。官方 api.typesafe.ai / OpenRouter / 自建中转皆可。
    base_url: str = ""
    api_key: str = ""
    model: str = "jev-latest"
    # auto: 依次探测原生与 OpenAI 兼容端点；native: state+questions；
    # openai: 走 /chat/completions，要求模型回 JSON。
    api_protocol: JevProtocol = "auto"
    timeout_s: float = 30.0
    # ── 三个功能开关 ──
    route_scene: bool = True
    detect_language: bool = True
    score_quality: bool = False
    # 译文质量低于阈值时是否自动重译一次（仅在 score_quality 打开时生效）。
    quality_threshold: float = JEV_QUALITY_THRESHOLD_DEFAULT
    retry_on_low_quality: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> JevConfig:
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
        proto = kwargs.get("api_protocol", "auto")
        if proto not in ("auto", "native", "openai"):
            kwargs["api_protocol"] = "auto"
        kwargs["enabled"] = bool(kwargs.get("enabled", False))
        kwargs["base_url"] = str(kwargs.get("base_url", "") or "").strip()
        kwargs["api_key"] = str(kwargs.get("api_key", "") or "").strip()
        model = str(kwargs.get("model", "") or "").strip()
        kwargs["model"] = model or "jev-latest"
        try:
            timeout = float(kwargs.get("timeout_s", 30.0))
        except (TypeError, ValueError):
            timeout = 30.0
        kwargs["timeout_s"] = max(5.0, min(timeout, 600.0))
        for flag in ("route_scene", "detect_language", "score_quality", "retry_on_low_quality"):
            kwargs[flag] = bool(kwargs.get(flag, cls.__dataclass_fields__[flag].default))
        try:
            threshold = float(
                kwargs.get("quality_threshold", JEV_QUALITY_THRESHOLD_DEFAULT)
            )
        except (TypeError, ValueError):
            threshold = JEV_QUALITY_THRESHOLD_DEFAULT
        kwargs["quality_threshold"] = max(0.0, min(threshold, 1.0))
        return cls(**kwargs)


def sanitize_custom_scenes(raw: Any) -> list[dict[str, str]]:
    """Normalize user-defined scene entries: keep well-formed, unique ids."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw[:CUSTOM_SCENES_MAX]:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        prompt = str(item.get("prompt", ""))
        if not sid or not label or sid in seen:
            continue
        seen.add(sid)
        out.append({"id": sid, "label": label, "prompt": prompt})
    return out


@dataclass
class TranslationConfig:
    source_lang: str = "auto"
    target_lang: str = "zh"
    image_mode: Literal["ocr", "vision"] = "ocr"
    supplementary_prompt: str = ""
    ocr_langs: str = "eng+chi_sim"
    auto_copy_result: bool = False
    scene: str = "general"  # id of a builtin or custom scene preset
    glossary: dict[str, str] = field(default_factory=dict)
    # Absolute path to the tesseract binary; empty → look up in PATH.
    tesseract_path: str = ""
    # User-defined scenes: [{"id", "label", "prompt"}]; the five builtin
    # presets live in app/core/presets.py and are always available.
    custom_scenes: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.custom_scenes = sanitize_custom_scenes(self.custom_scenes)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslationConfig:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        mode = kwargs.get("image_mode", "ocr")
        if mode not in ("ocr", "vision"):
            kwargs["image_mode"] = "ocr"
        kwargs["auto_copy_result"] = bool(kwargs.get("auto_copy_result", False))
        kwargs["tesseract_path"] = str(kwargs.get("tesseract_path", "") or "")

        glossary_raw = kwargs.get("glossary")
        glossary: dict[str, str] = {}
        if isinstance(glossary_raw, dict):
            for term, translation in list(glossary_raw.items())[:100]:
                term_s, trans_s = str(term).strip(), str(translation).strip()
                if term_s and trans_s:
                    glossary[term_s] = trans_s
        kwargs["glossary"] = glossary
        return cls(**kwargs)


@dataclass
class HotkeysConfig:
    translate: str = "Ctrl+Return"
    screenshot: str = "Ctrl+Shift+S"
    paste_image: str = "Ctrl+Shift+V"
    swap_langs: str = "Ctrl+Shift+X"
    copy_result: str = "Ctrl+Shift+C"
    extract_text: str = "Ctrl+Shift+T"
    # Global hotkey to summon the app (Windows only; on Linux/Wayland bind
    # the launch command to a compositor shortcut — single-instance IPC
    # makes the second launch activate the first).
    summon: str = "Ctrl+Alt+T"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotkeysConfig:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


TTS_RATE_MIN = -50
TTS_RATE_MAX = 100


@dataclass
class TtsConfig:
    """Text-to-speech settings (edge-tts engine, see app/core/tts.py)."""

    # Any edge-tts voice name; the settings dialog offers a curated list
    # and allows pasting arbitrary voice identifiers.
    voice: str = "zh-CN-XiaoxiaoNeural"
    # Speaking-rate offset in percent: -50 slow … +100 fast; 0 = normal.
    rate: int = 0
    # Read the translation aloud automatically when a translation finishes.
    auto_pronounce: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TtsConfig:
        if not isinstance(data, dict):
            data = {}
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        voice = str(kwargs.get("voice", "") or "").strip()
        kwargs["voice"] = voice or "zh-CN-XiaoxiaoNeural"
        try:
            rate = int(kwargs.get("rate", 0))
        except (TypeError, ValueError):
            rate = 0
        kwargs["rate"] = max(TTS_RATE_MIN, min(rate, TTS_RATE_MAX))
        kwargs["auto_pronounce"] = bool(kwargs.get("auto_pronounce", False))
        return cls(**kwargs)


@dataclass
class UiConfig:
    theme: Literal["dark", "light"] = "dark"
    window_width: int = 920
    window_height: int = 640
    window_maximized: bool = False
    splitter_sizes: list[int] = field(default_factory=list)
    close_to_tray: bool = True
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UiConfig:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known and k != "hotkeys"}
        theme = kwargs.get("theme", "dark")
        if theme not in ("dark", "light"):
            kwargs["theme"] = "dark"
        kwargs["window_maximized"] = bool(kwargs.get("window_maximized", False))
        kwargs["close_to_tray"] = bool(kwargs.get("close_to_tray", True))
        sizes_raw = kwargs.get("splitter_sizes")
        kwargs["splitter_sizes"] = (
            [int(s) for s in sizes_raw if isinstance(s, (int, float))]
            if isinstance(sizes_raw, list)
            else []
        )
        hotkeys_data = data.get("hotkeys") or {}
        if isinstance(hotkeys_data, dict):
            kwargs["hotkeys"] = HotkeysConfig.from_dict(hotkeys_data)
        return cls(**kwargs)


HISTORY_LIMIT_DEFAULT = 10
HISTORY_LIMIT_MAX = 100
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


@dataclass
class AppConfig:
    version: int = 1
    active_profile_id: str = "default"
    profiles: list[LlmProfile] = field(default_factory=list)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    jev: JevConfig = field(default_factory=JevConfig)
    history: list[HistoryEntry] = field(default_factory=list)
    history_limit: int = HISTORY_LIMIT_DEFAULT
    # Version of the app that last ran this config; used to surface
    # upgrades ("已更新到 …") on startup and to detect stale instances
    # after a package upgrade.
    last_run_version: str = ""

    def __post_init__(self) -> None:
        if not self.profiles:
            self.profiles = [
                LlmProfile(id="default", name="OpenAI-compatible"),
            ]
            self.active_profile_id = "default"
        self.history_limit = max(0, min(int(self.history_limit), HISTORY_LIMIT_MAX))
        if len(self.history) > self.history_limit:
            self.history = self.history[: self.history_limit]

    @classmethod
    def default(cls) -> AppConfig:
        return cls()

    def needs_setup(self) -> bool:
        """True when still running on the untouched default profile.

        Used to decide whether to offer the first-run provider wizard.
        """
        if len(self.profiles) != 1:
            return False
        p = self.profiles[0]
        default = LlmProfile(id="default")
        return (
            p.id == "default"
            and p.api_key == ""
            and p.base_url == default.base_url
            and p.model == default.model
        )

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

        active = data.get("active_profile_id") or profiles[0].id
        if not any(p.id == active for p in profiles):
            active = profiles[0].id

        cfg = cls(
            version=int(data.get("version", 1)),
            active_profile_id=active,
            profiles=profiles,
            translation=TranslationConfig.from_dict(
                translation_raw if isinstance(translation_raw, dict) else {}
            ),
            ui=UiConfig.from_dict(ui_raw if isinstance(ui_raw, dict) else {}),
            tts=TtsConfig.from_dict(data.get("tts")),
            jev=JevConfig.from_dict(data.get("jev")),
            history=[],
            last_run_version=str(data.get("last_run_version", "") or ""),
            history_limit=int(data.get("history_limit", HISTORY_LIMIT_DEFAULT)),
        )
        cfg.history = [
            HistoryEntry.from_dict(h) for h in history_raw if isinstance(h, dict)
        ][: cfg.history_limit]
        return cfg

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
        if len(self.history) > self.history_limit:
            self.history = self.history[: self.history_limit]
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
