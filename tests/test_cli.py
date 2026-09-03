"""Tests for the headless CLI (app.cli)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from app import cli
from app.config.schema import AppConfig


class _StubClient:
    """Stands in for LlmClient; records what the CLI forwards."""

    calls: list[dict] = []

    def __init__(self, profile) -> None:  # noqa: ANN001
        self.profile = profile

    def chat(self, messages: list[dict], **_kwargs: object) -> str:
        _StubClient.calls.append({"kind": "text", "messages": messages})
        return "译文"

    def chat_vision(self, system_prompt: str, user_text: str, image: bytes, **_kwargs) -> str:
        _StubClient.calls.append({"kind": "vision", "system": system_prompt, "image": image})
        return "图片译文"


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep log files out of the developer's real state dir."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture()
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> type[_StubClient]:
    _StubClient.calls = []
    monkeypatch.setattr("app.core.translator.LlmClient", _StubClient)
    return _StubClient


@pytest.fixture()
def side_effects(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture clipboard/notification side effects instead of firing them."""
    seen: dict = {"copy": [], "notify": []}
    monkeypatch.setattr(cli, "copy_to_clipboard", lambda text: seen["copy"].append(text) or True)
    monkeypatch.setattr(cli, "notify", lambda *args: seen["notify"].append(args))
    return seen


def _config_path(tmp_path: Path, *, mutate=None) -> str:
    cfg = AppConfig()
    if mutate:
        mutate(cfg)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False), encoding="utf-8")
    return str(path)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


# ── text paths ────────────────────────────────────────────────────
def test_translates_positional_text_and_copies(
    stub_llm, side_effects, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["Hello world", "--config", _config_path(tmp_path)])
    assert rc == 0
    assert "译文" in capsys.readouterr().out
    assert side_effects["copy"] == ["译文"]
    assert side_effects["notify"], "notification should fire by default"
    assert stub_llm.calls[0]["kind"] == "text"
    assert "Hello world" in stub_llm.calls[0]["messages"][-1]["content"]


def test_no_copy_and_no_notify_suppress_side_effects(
    stub_llm, side_effects, tmp_path: Path
) -> None:
    rc = cli.main(["hi", "--no-copy", "--no-notify", "--config", _config_path(tmp_path)])
    assert rc == 0
    assert side_effects["copy"] == []
    assert side_effects["notify"] == []


def test_reads_stdin_when_no_text_given(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("piped text"))
    rc = cli.main(["--no-copy", "--no-notify", "--config", _config_path(tmp_path)])
    assert rc == 0
    assert "piped text" in stub_llm.calls[0]["messages"][-1]["content"]


def test_clipboard_flag_reads_clipboard(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "read_clipboard_text", lambda: "from clipboard")
    rc = cli.main(["--clipboard", "--no-copy", "--no-notify", "--config", _config_path(tmp_path)])
    assert rc == 0
    assert "from clipboard" in stub_llm.calls[0]["messages"][-1]["content"]


def test_empty_input_reports_error(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "read_clipboard_text", lambda: "   ")
    rc = cli.main(["--clipboard", "--no-copy", "--no-notify", "--config", _config_path(tmp_path)])
    assert rc == 1
    assert "没有可翻译的文本" in capsys.readouterr().err


def test_no_input_source_is_usage_error(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Tty:
        def isatty(self) -> bool:
            return True

        def read(self) -> str:
            raise AssertionError("stdin must not be read when it is a tty")

    monkeypatch.setattr("sys.stdin", _Tty())
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", _config_path(tmp_path)])
    assert exc.value.code == 2


# ── image paths ───────────────────────────────────────────────────
def test_screenshot_uses_vision_when_requested(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "capture_screenshot", _png)
    rc = cli.main(
        ["--screenshot", "--mode", "vision", "--no-copy", "--no-notify",
         "--config", _config_path(tmp_path)]
    )
    assert rc == 0
    assert stub_llm.calls[0]["kind"] == "vision"


def test_image_flag_reads_clipboard_image(
    stub_llm, side_effects, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "read_clipboard_image", _png)

    class _StubOcr:
        def __init__(self, tesseract_bin: str = "tesseract", **_kwargs: object) -> None:
            self.tesseract_bin = tesseract_bin

        def extract_text(self, image: bytes, langs: str = "eng+chi_sim") -> str:
            return "extracted"

    # cli.py imports OcrService directly, so patch it in the cli namespace.
    monkeypatch.setattr(cli, "OcrService", _StubOcr)
    rc = cli.main(
        ["--image", "--mode", "ocr", "--no-copy", "--no-notify",
         "--config", _config_path(tmp_path)]
    )
    assert rc == 0
    assert stub_llm.calls[0]["kind"] == "text"
    assert "extracted" in stub_llm.calls[0]["messages"][-1]["content"]


# ── configuration wiring ──────────────────────────────────────────
def test_unknown_profile_is_reported(
    stub_llm, side_effects, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["hi", "--profile", "nope", "--config", _config_path(tmp_path)])
    assert rc == 1
    assert "未找到服务商" in capsys.readouterr().err


def test_profile_matches_by_name(
    stub_llm, side_effects, tmp_path: Path
) -> None:
    def rename(cfg: AppConfig) -> None:
        cfg.profiles[0].name = "MyProvider"

    rc = cli.main(
        ["hi", "--profile", "myprovider", "--no-copy", "--no-notify",
         "--config", _config_path(tmp_path, mutate=rename)]
    )
    assert rc == 0
    assert stub_llm.calls, "translation should have run"


def test_language_flags_override_config(stub_llm, side_effects, tmp_path: Path) -> None:
    rc = cli.main(
        ["hi", "-s", "en", "-t", "ja", "--no-copy", "--no-notify",
         "--config", _config_path(tmp_path)]
    )
    assert rc == 0
    system = stub_llm.calls[0]["messages"][0]["content"]
    assert "English" in system and "Japanese" in system


def test_glossary_is_injected_into_prompt(stub_llm, side_effects, tmp_path: Path) -> None:
    def add_glossary(cfg: AppConfig) -> None:
        cfg.translation.glossary = {"Transformer": "变压器"}

    rc = cli.main(
        ["hi", "--no-copy", "--no-notify",
         "--config", _config_path(tmp_path, mutate=add_glossary)]
    )
    assert rc == 0
    system = stub_llm.calls[0]["messages"][0]["content"]
    assert "变压器" in system


def test_cli_never_writes_config(stub_llm, side_effects, tmp_path: Path) -> None:
    """The GUI may be running; a CLI save would clobber unsaved edits."""
    path = Path(_config_path(tmp_path))
    before = path.read_text(encoding="utf-8")
    assert cli.main(["hi", "--no-copy", "--no-notify", "--config", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == before


# ── packaging contract ────────────────────────────────────────────
def test_cli_imports_without_qt() -> None:
    """Headless Linux sessions have no usable Qt; the CLI must not need it."""
    if sys.platform == "win32":
        pytest.skip("Windows backends require Qt by design")
    code = (
        "import sys; import app.cli;"
        "assert not [m for m in sys.modules if m.startswith('PySide6')];"
        "print('qt-free')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "qt-free" in proc.stdout


def test_console_script_entrypoint_resolves() -> None:
    """pyproject registers `ai-translator-cli = app.cli:main`."""
    import importlib

    module = importlib.import_module("app.cli")
    assert callable(module.main)
