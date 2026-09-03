"""Command-line interface: translate without ever launching the GUI.

Deliberately free of PySide6 imports at module scope — on Linux the whole
text/clipboard-image/screenshot path runs on wl-paste / wl-copy / slurp / grim
and must work in headless sessions where Qt is unavailable or unusable. Qt is
imported lazily only for the Windows backends, which genuinely need it.

The CLI only ever *reads* the config. It never writes it back: the GUI may be
running concurrently, and a CLI save would clobber unsaved GUI edits.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from app import __version__
from app.config.schema import LlmProfile
from app.config.store import ConfigStore
from app.core.ocr import OcrError, OcrService
from app.core.presets import effective_extra_prompt
from app.core.translator import Translator
from app.logsetup import setup_logging

log = logging.getLogger("app.cli")

_IS_WINDOWS = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

# Longest result still worth showing in a desktop notification.
_NOTIFY_BODY_MAX = 200


class CliError(Exception):
    """User-facing failure: printed to stderr, exits non-zero."""


# --------------------------------------------------------------------------
# Platform helpers
# --------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    timeout: float = 10.0,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with UTF-8 text I/O, never raising on failure."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
        timeout=timeout,
        check=False,
    )


def _ensure_qt_app() -> None:
    """Create a minimal QApplication if one does not exist yet.

    Only Windows clipboard/screenshot backends need this. QApplication keeps
    itself alive via ``instance()``, so no reference needs to be held here.
    """
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])


# --------------------------------------------------------------------------
# Clipboard text
# --------------------------------------------------------------------------


def read_clipboard_text() -> str:
    """Read clipboard text without Qt wherever the platform allows it."""
    if _IS_WINDOWS:
        proc = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-Clipboard -Raw",
            ]
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip()
        raise CliError("无法读取剪贴板（Get-Clipboard 失败）")

    if _IS_MAC:
        if not shutil.which("pbpaste"):
            raise CliError("未找到 pbpaste，无法读取剪贴板")
        proc = _run(["pbpaste"])
        if proc.returncode != 0:
            raise CliError(f"pbpaste 失败：{(proc.stderr or '').strip()}")
        return (proc.stdout or "").strip()

    for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
        if not shutil.which(cmd[0]):
            continue
        proc = _run(cmd)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip()
    raise CliError("未找到 wl-paste 或 xclip，无法读取剪贴板")


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the clipboard. Returns True on success."""
    if not text:
        return False

    if _IS_WINDOWS:
        # clip.exe mangles non-ASCII depending on the console code page, so
        # hand the value straight to Qt instead.
        try:
            _ensure_qt_app()
            from PySide6.QtWidgets import QApplication

            clipboard = QApplication.clipboard()
            if clipboard is None:
                return False
            clipboard.setText(text)
            return True
        except Exception as exc:  # noqa: BLE001 — clipboard is best-effort
            log.debug("Windows clipboard write failed: %s", exc)
            return False

    if _IS_MAC:
        if not shutil.which("pbcopy"):
            return False
        proc = _run(["pbcopy"], input_text=text)
        return proc.returncode == 0

    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = _run(cmd, input_text=text)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return True
    return False


def notify(title: str, body: str) -> None:
    """Fire a desktop notification; silently skipped when unsupported."""
    body = (body or "").strip().replace("\n", " ")
    if len(body) > _NOTIFY_BODY_MAX:
        body = body[: _NOTIFY_BODY_MAX - 1] + "…"
    try:
        if _IS_MAC and shutil.which("osascript"):
            script = f'display notification "{body}" with title "{title}"'
            _run(["osascript", "-e", script], timeout=5)
        elif shutil.which("notify-send"):
            _run(["notify-send", title, body], timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("notification failed: %s", exc)


# --------------------------------------------------------------------------
# Image capture
# --------------------------------------------------------------------------


def read_clipboard_image() -> bytes:
    """Read an image from the clipboard as PNG bytes."""
    from app.core.clipboard_image import ClipboardImageError, ClipboardImageService

    if _IS_WINDOWS:
        _ensure_qt_app()
    service = ClipboardImageService()
    try:
        return service.read_png()
    except ClipboardImageError as exc:
        raise CliError(str(exc)) from exc


def capture_screenshot() -> bytes:
    """Interactive region capture → PNG bytes."""
    from app.core.screenshot import ScreenshotCancelled, ScreenshotError, ScreenshotService

    if _IS_WINDOWS:
        _ensure_qt_app()
    service = ScreenshotService()
    try:
        return service.capture_region()
    except ScreenshotCancelled as exc:
        raise CliError(str(exc) or "截图已取消") from exc
    except ScreenshotError as exc:
        raise CliError(str(exc)) from exc


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------


def _resolve_profile(config, name: str | None) -> LlmProfile:
    if not name:
        return config.get_active_profile()
    lowered = name.casefold()
    for profile in config.profiles:
        if profile.id.casefold() == lowered or profile.name.casefold() == lowered:
            return profile
    available = ", ".join(p.name for p in config.profiles)
    raise CliError(f"未找到服务商「{name}」。可选：{available}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-translator-cli",
        description="AI 翻译器命令行模式：不启动图形界面完成翻译。",
        epilog=(
            "示例：\n"
            '  ai-translator-cli "Hello world"\n'
            "  ai-translator-cli --clipboard -t ja\n"
            "  ai-translator-cli --screenshot --mode vision\n"
            "  echo 'text' | ai-translator-cli\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("text", nargs="*", help="要翻译的文本（省略则从标准输入读取）")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--clipboard", action="store_true", help="翻译剪贴板中的文本")
    source.add_argument("--image", action="store_true", help="翻译剪贴板中的图片")
    source.add_argument("--screenshot", action="store_true", help="截图后翻译")

    parser.add_argument("-s", "--source", help="源语言代码（默认取配置）")
    parser.add_argument("-t", "--target", help="目标语言代码（默认取配置）")
    parser.add_argument(
        "--mode",
        choices=("ocr", "vision"),
        help="图片翻译方式（默认取配置）",
    )
    parser.add_argument("--profile", help="按名称或 ID 指定服务商（默认取当前启用项）")
    parser.add_argument("--no-copy", action="store_true", help="不把结果写回剪贴板")
    parser.add_argument("--no-notify", action="store_true", help="不发送桌面通知")
    parser.add_argument("--verbose", action="store_true", help="输出诊断信息到 stderr")
    parser.add_argument("--config", help="指定配置文件路径（默认取用户配置目录）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _collect_input(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, bytes | None]:
    """Return (text, image_png) for the requested input source."""
    if args.screenshot:
        return "", capture_screenshot()
    if args.image:
        return "", read_clipboard_image()

    if args.clipboard:
        text = read_clipboard_text()
    elif args.text:
        text = " ".join(args.text)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.error("请提供待翻译文本，或指定 --clipboard / --image / --screenshot")

    text = text.strip()
    if not text:
        raise CliError("没有可翻译的文本")
    return text, None


def main(argv: list[str] | None = None) -> int:
    setup_logging(to_stderr=False)
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        text, image = _collect_input(args, parser)

        store = ConfigStore(Path(args.config)) if args.config else ConfigStore()
        config = store.load()
        profile = _resolve_profile(config, args.profile)
        translation = config.translation

        source_lang = args.source or translation.source_lang
        target_lang = args.target or translation.target_lang
        extra = effective_extra_prompt(translation)
        translator = Translator(
            ocr=OcrService(tesseract_bin=translation.tesseract_path or "tesseract")
        )

        if image:
            mode = args.mode or translation.image_mode
            if args.verbose:
                print(f"[mode] {mode} ({len(image)} bytes)", file=sys.stderr)
            result = translator.translate_image(
                image,
                mode=mode,
                source_lang=source_lang,
                target_lang=target_lang,
                profile=profile,
                supplementary_prompt=extra,
                glossary=translation.glossary,
                ocr_langs=translation.ocr_langs,
            )
        else:
            if args.verbose:
                print(f"[text] {len(text)} chars", file=sys.stderr)
            result = translator.translate_text(
                text,
                source_lang=source_lang,
                target_lang=target_lang,
                profile=profile,
                supplementary_prompt=extra,
                glossary=translation.glossary,
            )
    except CliError as exc:
        log.info("cli error: %s", exc)
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except OcrError as exc:
        log.warning("ocr failed: %s", exc)
        print(f"OCR 失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — CLI must never dump a traceback
        log.exception("cli failed")
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    output = (result.text or "").strip()
    if output:
        print(output)

    if not args.no_copy and copy_to_clipboard(output):
        if args.verbose:
            print("[copied] 已复制到剪贴板", file=sys.stderr)
    elif not args.no_copy and args.verbose:
        print("[copy skipped] 无可用剪贴板写入工具", file=sys.stderr)

    if not args.no_notify:
        notify("AI 翻译", output or "（空结果）")

    if args.verbose:
        print(f"[model] {result.model}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
