"""Application entrypoint."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config.store import ConfigStore
from app.ui.first_run_dialog import FirstRunDialog
from app.ui.main_window import MainWindow
from app.ui.widgets import apply_theme


def main() -> int:
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

    app = QApplication(sys.argv)
    app.setApplicationName("AI Translator")
    app.setOrganizationName("ai-translator")
    app.setApplicationVersion("0.1.0")

    store = ConfigStore()
    config = store.load()
    apply_theme(app, config.ui.theme)

    window = MainWindow(store, config)
    window.show()

    # First run: offer the provider wizard (skippable, never forced).
    if config.needs_setup():
        wizard = FirstRunDialog(config.get_active_profile(), window)
        if wizard.exec() == FirstRunDialog.DialogCode.Accepted:
            profile = wizard.result_profile()
            config.upsert_profile(profile)
            config.active_profile_id = profile.id
            try:
                store.save(config)
            except OSError:
                pass
            window.reload_config(config)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
