"""Tests for single-instance IPC (app.ipc).

Requires PySide6 (skipped automatically when unavailable).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ipc import ActivateServer, notify_running, unique_server_name  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    import os

    # offscreen + QApplication (not plain QCoreApplication) so this module
    # can run before/after GUI test modules without Qt instance conflicts.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


def _pump(app: QApplication, ms: int = 300) -> None:
    """Process events for up to `ms` milliseconds."""
    steps = max(1, ms // 20)
    for _ in range(steps):
        app.processEvents()
        QThread.msleep(20)


def test_server_emits_command(qapp: QApplication) -> None:
    server = ActivateServer(unique_server_name())
    assert server.start() is True
    received: list[str] = []
    server.command_received.connect(received.append)

    assert notify_running("activate", name=server.name) is True
    _pump(qapp)

    assert received == ["activate"]
    server.stop()


def test_notify_returns_false_without_server(qapp: QApplication) -> None:
    # Unique name → nobody is listening → connect must fail, not hang.
    assert notify_running("activate", timeout_ms=200, name=unique_server_name()) is False


def test_start_recovers_from_stale_server(qapp: QApplication) -> None:
    name = unique_server_name()
    first = ActivateServer(name)
    assert first.start() is True
    first.stop()

    second = ActivateServer(name)
    assert second.start() is True  # stale socket file must not block
    second.stop()


def test_server_ignores_empty_payload(qapp: QApplication) -> None:
    server = ActivateServer(unique_server_name())
    assert server.start() is True
    received: list[str] = []
    server.command_received.connect(received.append)

    assert notify_running("   \n", name=server.name) is True  # whitespace-only token
    _pump(qapp, ms=150)

    assert received == []
    server.stop()
