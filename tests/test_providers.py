"""Sanity checks for provider templates."""

from app.core.providers import PROVIDER_TEMPLATES, get_template


def test_template_ids_and_urls_unique() -> None:
    ids = [t.id for t in PROVIDER_TEMPLATES]
    assert len(ids) == len(set(ids))
    urls = [t.base_url for t in PROVIDER_TEMPLATES]
    assert len(urls) == len(set(urls))
    for t in PROVIDER_TEMPLATES:
        assert t.base_url.startswith("http")


def test_known_providers_present() -> None:
    ids = {t.id for t in PROVIDER_TEMPLATES}
    assert {"openai", "deepseek", "siliconflow", "ollama"} <= ids


def test_local_providers_need_no_key() -> None:
    for tid in ("ollama", "lmstudio"):
        t = get_template(tid)
        assert t is not None and t.key_required is False


def test_get_template_unknown_returns_none() -> None:
    assert get_template("nope") is None
