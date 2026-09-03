"""Application logging: rotating file in the user state dir + stderr."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUPS = 2


def default_log_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        return Path(base) / "ai-translator" / "logs"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ai-translator"


def setup_logging(*, level: int = logging.INFO, to_stderr: bool = True) -> Path | None:
    """Install a rotating file handler (and optional stderr handler).

    Safe to call multiple times; later calls are no-ops on the root logger.
    Returns the log file path when file logging was installed.
    """
    root = logging.getLogger()
    if getattr(root, "_ai_translator_configured", False):
        return None
    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    log_file: Path | None = None
    try:
        log_dir = default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ai-translator.log"
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        # Read-only FS etc. — logging is best-effort, never fatal.
        log_file = None

    if to_stderr:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    root._ai_translator_configured = True  # type: ignore[attr-defined]
    return log_file
