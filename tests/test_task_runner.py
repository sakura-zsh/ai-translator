"""Tests for TaskRunner (§3.5): worker boilerplate deduplication."""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.workers.tasks import TaskRunner  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture()
def pool(qapp: QApplication):  # type: ignore[no-untyped-def]
    # Dedicated pool so tests never depend on globalInstance state.
    p = QThreadPool()
    p.setMaxThreadCount(2)
    yield p
    p.clear()
    p.waitForDone(2000)


def _pump(qapp: QApplication, pool: QThreadPool, rounds: int = 40) -> None:
    """Wait for pool threads, then deliver queued callbacks to the GUI loop."""
    for _ in range(rounds):
        qapp.processEvents()
        if pool.waitForDone(25):
            qapp.processEvents()
            qapp.processEvents()


def test_run_delivers_result_and_resets_busy(
    qapp: QApplication, pool: QThreadPool
) -> None:
    runner = TaskRunner(pool)
    results: list[object] = []
    runner.run(lambda: 42, on_ok=results.append)
    assert runner.busy is True  # in flight immediately after run()

    _pump(qapp, pool)
    assert results == [42]
    assert runner.busy is False


def test_run_delivers_exception_object(
    qapp: QApplication, pool: QThreadPool
) -> None:
    runner = TaskRunner(pool)
    errs: list[Exception] = []

    def boom() -> object:
        raise ValueError("kaputt")

    runner.run(
        boom,
        on_ok=lambda _r: pytest.fail("on_ok must not fire"),
        on_err=errs.append,
    )
    _pump(qapp, pool)

    assert len(errs) == 1
    assert isinstance(errs[0], ValueError)
    assert str(errs[0]) == "kaputt"
    assert runner.busy is False


def test_run_ignores_second_submit_while_busy(
    qapp: QApplication, pool: QThreadPool
) -> None:
    started = threading.Event()
    calls = threading.Semaphore(0)

    def work() -> int:
        started.set()
        calls.acquire(timeout=2)
        return 1

    runner = TaskRunner(pool)
    results: list[int] = []
    runner.run(work, on_ok=results.append)
    # First task blocks inside work(); the second submit must be dropped.
    assert runner.busy is True
    runner.run(lambda: 2, on_ok=results.append)
    calls.release()
    assert started.wait(2)
    _pump(qapp, pool)

    assert results == [1]
    assert runner.busy is False


def test_run_without_callbacks_is_safe(
    qapp: QApplication, pool: QThreadPool
) -> None:
    runner = TaskRunner(pool)
    runner.run(lambda: None)
    _pump(qapp, pool)
    assert runner.busy is False


def test_tasks_run_on_worker_thread(
    qapp: QApplication, pool: QThreadPool
) -> None:
    runner = TaskRunner(pool)
    threads: list[threading.Thread] = []
    runner.run(lambda: threads.append(threading.current_thread()))
    _pump(qapp, pool)

    assert len(threads) == 1
    assert threads[0] is not threading.main_thread()
