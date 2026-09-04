"""Application entrypoint."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtWidgets import QApplication

from app import __version__
from app.config.store import ConfigStore
from app.core import hotkey_win
from app.ipc import ActivateServer, notify_running
from app.logsetup import setup_logging
from app.ui.first_run_dialog import FirstRunDialog
from app.ui.main_window import MainWindow
from app.ui.widgets import apply_theme

log = logging.getLogger(__name__)


def _notify_existing_instance() -> None:
    """Second launch: poke the running instance and exit (QApplication is
    required because QLocalSocket lives in QtNetwork)."""
    QApplication(sys.argv)
    if notify_running("activate"):
        print("已通知正在运行的 AI Translator 唤起窗口。", file=sys.stderr)
    else:
        print("AI Translator 已在运行，但暂时无法通知（可能正在退出）。", file=sys.stderr)


def main() -> int:
    setup_logging()

    # Prefer the native platform plugin; allow override via env.
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    else:
        # Prefer Wayland on niri/CachyOS; X11 users may override via env.
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

    # High-DPI is default in Qt6; ensure pixmaps scale cleanly.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Single instance: a stale lock file is harmless, QLockFile detects and
    # removes it. The lock object must outlive app.exec(), hence no with-block.
    lock = QLockFile(str(Path(tempfile.gettempdir()) / "ai-translator.lock"))
    if not lock.tryLock(0):
        _notify_existing_instance()
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("AI Translator")
    app.setOrganizationName("ai-translator")
    app.setApplicationVersion(__version__)

    store = ConfigStore()
    config = store.load()
    apply_theme(app, config.ui.theme)

    window = MainWindow(store, config)
    window.show()
    log.info("AI Translator %s started", __version__)

    # Windows global summon hotkey: app-level WM_HOTKEY filter is the
    # primary delivery path (inert off-Windows). Local keeps it alive
    # for the whole event loop; underscore marks it as intentionally held.
    _hotkey_filter = hotkey_win.install_native_filter(window.summon)

    # Single-instance activation: later launches summon this window. The
    # server is parented to the app so it lives until process exit.
    activate_server = ActivateServer(parent=app)

    def _dispatch_command(command: str) -> None:
        if command == "activate":
            window.summon()
        else:
            log.info("unknown IPC command ignored: %s", command)

    if activate_server.start():
        activate_server.command_received.connect(_dispatch_command)
    else:
        log.warning("single-instance activation disabled (socket unavailable)")

    # First run: offer the provider wizard (skippable, never forced).
    if config.needs_setup():
        wizard = FirstRunDialog(config.get_active_profile(), window)
        if wizard.exec() == FirstRunDialog.DialogCode.Accepted:
            profile = wizard.result_profile()
            config.upsert_profile(profile)
            config.active_profile_id = profile.id
            with contextlib.suppress(OSError):
                store.save(config)
            window.reload_config(config)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
