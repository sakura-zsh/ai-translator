"""Shared pytest fixtures and hooks.

Deterministic Qt teardown: PySide6 crashes with a segfault during
interpreter shutdown on some Python versions (observed on 3.11) while
garbage-collecting Qt objects left over from UI tests — regardless of
whether QApplication is destroyed explicitly first. All tests have
already passed at that point, so the shutdown crash carries no signal
about test health: bypass interpreter finalization entirely with
os._exit() and keep the real exit status.
"""

from __future__ import annotations

import os
import sys

import pytest

_exit_status = 0


@pytest.fixture(autouse=True)
def _drop_pending_ipc_sockets():
    """Never let kept-alive QLocalSockets outlive a test (see app/ipc.py)."""
    yield
    from app import ipc

    ipc._pending_sockets.clear()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: N802
    global _exit_status
    _exit_status = exitstatus


def pytest_unconfigure(config) -> None:  # noqa: N802
    # Last hook before pytest returns to the shell: hard-exit so the
    # interpreter never runs its final GC over Qt objects.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status)
