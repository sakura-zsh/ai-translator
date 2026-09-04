"""Background QRunnable tasks so the UI never blocks on HTTP/OCR/capture."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    finished = Signal(object)
    # Exception instance (preserves the type so callers can branch on it,
    # e.g. ScreenshotCancelled vs. real failures) — never a bare string.
    error = Signal(object)


class FunctionWorker(QRunnable):
    """Run a callable in the thread pool and emit result/error."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 — surface any failure to UI
            log.error("worker task failed: %s", exc, exc_info=exc)
            self.signals.error.emit(exc)
            return
        self.signals.finished.emit(result)


class TaskRunner(QObject):
    """Deduplicates the FunctionWorker + connect + pool.start boilerplate.

    `busy` is True from run() until the queued ok/err callback has fired on
    the GUI thread — use it to guard against double submits. Callers keep
    ownership of busy-state *visuals* (button disable, status text).

    Implementation note: ok/err callbacks are stored and dispatched from
    bound slots. Connecting worker signals directly to plain closures would
    work only while the closures stay referenced; bound slots on this
    long-lived QObject are always safe for queued cross-thread delivery.
    """

    def __init__(self, pool: QThreadPool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = pool
        self._busy = False
        self._ok_cb: Callable[[Any], None] | None = None
        self._err_cb: Callable[[Exception], None] | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    def run(
        self,
        work: Callable[..., Any],
        on_ok: Callable[[Any], None] | None = None,
        on_err: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run `work` on the pool; deliver result/error on the GUI thread.

        Ignored while another task is still in flight (busy guard).
        """
        if self._busy:
            return
        self._busy = True
        self._ok_cb = on_ok
        self._err_cb = on_err

        worker = FunctionWorker(work)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        self._pool.start(worker)

    def _on_finished(self, result: Any) -> None:
        self._busy = False
        cb, self._ok_cb = self._ok_cb, None
        if cb is not None:
            cb(result)

    def _on_error(self, exc: Exception) -> None:
        self._busy = False
        cb, self._err_cb = self._err_cb, None
        if cb is not None:
            cb(exc)
