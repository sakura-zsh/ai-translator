"""Clipboard image reading with platform backends (Wayland / Windows)."""

from __future__ import annotations

import sys


class ClipboardImageError(Exception):
    pass


def _backend_module():
    if sys.platform == "win32":
        from app.core import clipboard_windows as mod
    else:
        from app.core import clipboard_wayland as mod
    return mod


class ClipboardImageService:
    """Facade over the platform clipboard backend.

    All backends implement:

    - ``available() -> bool``
    - ``list_types() -> list[str]``
    - ``read_png() -> bytes`` (PNG; raises ClipboardImageError)
    """

    def __init__(self) -> None:
        self._impl = _backend_module().ClipboardImageService()

    def available(self) -> bool:
        return self._impl.available()

    def list_types(self) -> list[str]:
        return self._impl.list_types()

    def read_png(self) -> bytes:
        return self._impl.read_png()
