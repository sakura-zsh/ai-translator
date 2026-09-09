"""Shared pytest fixtures and hooks.

Deterministic Qt teardown: PySide6 crashes with a segfault during
interpreter shutdown on some Python versions (observed on 3.11) when
QApplication and lingering Qt objects (e.g. ipc._pending_sockets) are
destroyed by the garbage collector at exit. Destroy things explicitly
and in the right order instead.
"""

from __future__ import annotations

import gc

import pytest


@pytest.fixture(autouse=True)
def _drop_pending_ipc_sockets():
    """Never let kept-alive QLocalSockets outlive a test (see app/ipc.py)."""
    yield
    from app import ipc

    ipc._pending_sockets.clear()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: N802
    """Destroy the QApplication before interpreter shutdown."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QCoreApplication.instance()
    if app is not None:
        app.processEvents()
        app.sendPostedEvents(None, 0)
        del app
    gc.collect()
