"""Scene presets: quick-switch translation styles (prompt fragments).

The selected preset is combined with the user's always-on supplementary
prompt from settings: preset text first, personal extra appended.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.schema import TranslationConfig


@dataclass(frozen=True)
class ScenePreset:
    id: str
    label: str
    prompt: str  # empty → no extra instructions


SCENE_PRESETS: list[ScenePreset] = [
    ScenePreset("general", "通用", ""),
    ScenePreset(
        "academic",
        "学术论文",
        "使用严谨的学术书面语；专业术语采用学界通用译法，首次出现时在括号内保留英文原词；"
        "长句可按中文习惯断句，但不得增删信息。",
    ),
    ScenePreset(
        "technical",
        "技术文档",
        "面向工程师的技术文档风格：代码、命令、API 名称、文件路径、配置键名一律保留原文不翻译；"
        "术语采用业界通用译法；语言简洁准确，步骤清晰。",
    ),
    ScenePreset(
        "casual",
        "口语化",
        "使用自然流畅的口语化表达，像母语者日常说话一样翻译；避免书面腔和翻译腔，可适当拆分长句。",
    ),
    ScenePreset(
        "formal",
        "正式书面",
        "使用正式书面语，语法严谨、措辞得体，适合新闻、公文、商务信函等场景。",
    ),
]

_BY_ID = {p.id: p for p in SCENE_PRESETS}

# Custom scenes are stored in the config as plain dicts:
# {"id": str, "label": str, "prompt": str} (sanitized by the schema).


def all_scene_presets(
    custom_scenes: list[dict[str, str]] | None = None,
) -> list[ScenePreset]:
    """Builtin presets first, then the user's custom scenes."""
    custom = [
        ScenePreset(
            id=str(c.get("id", "")),
            label=str(c.get("label", "")),
            prompt=str(c.get("prompt", "")),
        )
        for c in (custom_scenes or [])
    ]
    return SCENE_PRESETS + custom


def get_scene(
    scene_id: str, custom_scenes: list[dict[str, str]] | None = None
) -> ScenePreset:
    """Look up a scene by id; builtin wins over custom, general is the fallback."""
    if scene_id in _BY_ID:
        return _BY_ID[scene_id]
    for c in custom_scenes or []:
        if c.get("id") == scene_id:
            return ScenePreset(
                id=scene_id,
                label=str(c.get("label", "")),
                prompt=str(c.get("prompt", "")),
            )
    return _BY_ID["general"]


def scene_prompt(
    scene_id: str, custom_scenes: list[dict[str, str]] | None = None
) -> str:
    return get_scene(scene_id, custom_scenes).prompt


def effective_extra_prompt(config: TranslationConfig) -> str:
    """Preset prompt + the user's personal supplementary prompt, combined."""
    parts = [scene_prompt(config.scene, config.custom_scenes).strip()]
    extra = (config.supplementary_prompt or "").strip()
    if extra:
        parts.append(extra)
    return "\n".join(p for p in parts if p)


# ── Glossary text serialization (settings dialog ⇆ config) ────────
GLOSSARY_MAX = 100
# Earliest separator in a line wins; Tab allows "term<tab>value" pastes.
_GLOSSARY_SEPARATORS = ("→", "->", "=", "\t")


def parse_glossary(text: str) -> dict[str, str]:
    """Parse glossary text, one entry per line: `term = translation`.

    Supported separators: →, ->, =, Tab. The earliest separator in the
    line wins; blank lines and entries missing either side are skipped.
    Capped at GLOSSARY_MAX entries.
    """
    result: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        cuts = [(line.index(sep), sep) for sep in _GLOSSARY_SEPARATORS if sep in line]
        if not cuts:
            continue
        pos, sep = min(cuts, key=lambda pair: pair[0])
        term = line[:pos].strip()
        value = line[pos + len(sep):].strip()
        if term and value:
            result[term] = value
        if len(result) >= GLOSSARY_MAX:
            break
    return result


def format_glossary(glossary: dict[str, str] | None) -> str:
    """Render a glossary dict back to editable `term = translation` lines."""
    return "\n".join(f"{k} = {v}" for k, v in (glossary or {}).items())
