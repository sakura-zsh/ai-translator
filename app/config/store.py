"""Load and save app config (Windows: %APPDATA%, else XDG)."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

from app.config.schema import AppConfig


def default_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "ai-translator" / "config.json"

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ai-translator" / "config.json"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig.default()
            # Best-effort first-run write; a read-only HOME or full disk must
            # not crash startup — we simply run on in-memory defaults.
            with contextlib.suppress(OSError):
                self.save(config)
            return config
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                return AppConfig.default()
            return AppConfig.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return AppConfig.default()

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".config.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
            # Unix-only permission tightening; no-op semantics on Windows ACLs
            if sys.platform != "win32":
                with contextlib.suppress(OSError):
                    os.chmod(self.path, 0o600)
        except Exception:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
            raise
