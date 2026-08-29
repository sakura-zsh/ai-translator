"""Screenshot capture with platform backends (Wayland / Windows)."""

from __future__ import annotations

import sys


class ScreenshotError(Exception):
    pass


class ScreenshotCancelled(ScreenshotError):
    pass


def _backend_module():
    if sys.platform == "win32":
        from app.core import screenshot_windows as mod
    else:
        from app.core import screenshot_wayland as mod
    return mod


class ScreenshotService:
    """Facade over the platform screenshot backend.

    All backends implement:

    - ``available() -> bool``
    - ``capture_region() -> bytes`` (PNG; raises ScreenshotCancelled on Esc)
    - ``requires_gui_thread: bool`` (modal Qt overlays need the GUI thread)
    """

    def __init__(self) -> None:
        self._impl = _backend_module().ScreenshotService()

    @property
    def requires_gui_thread(self) -> bool:
        return bool(getattr(self._impl, "requires_gui_thread", False))

    def available(self) -> bool:
        return self._impl.available()

    def capture_region(self) -> bytes:
        """Interactive region select → PNG bytes. Raises ScreenshotCancelled on Esc."""
        return self._impl.capture_region()
