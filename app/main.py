"""Application entrypoint."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config.store import ConfigStore
from app.ui.main_window import MainWindow
from app.ui.widgets import apply_theme


def main() -> int:
    # Prefer Wayland on niri/CachyOS; allow override via env.
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
