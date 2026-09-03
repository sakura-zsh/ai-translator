"""Background QRunnable tasks so the UI never blocks on HTTP/OCR/capture."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

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
