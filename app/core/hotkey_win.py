"""Windows global hotkey to summon the app (RegisterHotKey, no extra deps).

The hotkey is registered against the main window's HWND, so WM_HOTKEY is
delivered to that window even while it is hidden in the tray; MainWindow
forwards it to summon() from nativeEvent. All functions are no-ops
(returns False / False-ish) off Windows, and parsing is pure so it can be
unit-tested cross-platform.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

SUMMON_HOTKEY_ID = 1
WM_HOTKEY = 0x0312

_MOD_ALT = 0x1
_MOD_CONTROL = 0x2
_MOD_SHIFT = 0x4
_MOD_WIN = 0x8
_MOD_NOREPEAT = 0x4000

_MOD_BITS = {
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "alt": _MOD_ALT,
    "shift": _MOD_SHIFT,
    "win": _MOD_WIN,
    "super": _MOD_WIN,
    "meta": _MOD_WIN,
}


def _vk(part: str) -> int | None:
    """Virtual-key code for 'a'-'z', '0'-'9', 'f1'-'f24'; None otherwise."""
    if len(part) == 1 and part.isalnum() and part.isascii():
        return ord(part.upper())
    if len(part) >= 2 and part[0] == "f" and part[1:].isdigit():
        n = int(part[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1  # VK_F1 = 0x70
    return None


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """Parse 'Ctrl+Alt+T' into (modifiers | MOD_NOREPEAT, virtual-key code).

    At least one modifier is required (a bare key would hijack typing).
    Returns None when the sequence is empty, malformed, or unparseable.
    """
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods = 0
    vk: int | None = None
    for part in parts:
        if part in _MOD_BITS:
            mods |= _MOD_BITS[part]
        elif _vk(part) is not None:
            if vk is not None:  # two non-modifier keys → invalid
                return None
            vk = _vk(part)
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods | _MOD_NOREPEAT, vk


def register_summon_hotkey(window: object, sequence: str) -> bool:
    """Register the global summon hotkey on the window's HWND (Windows only).

    On success stores (hwnd, id) on `window._global_hotkey` for later
    unregister. Returns False off-Windows or on any failure (e.g. the
    combination is taken by another app).
    """
    if sys.platform != "win32":
        return False
    parsed = parse_hotkey(sequence)
    if parsed is None:
        return False
    mods, vk = parsed
    try:
        import ctypes

        hwnd = int(window.winId())  # type: ignore[attr-defined]
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(hwnd, SUMMON_HOTKEY_ID, mods, vk):
            log.warning("RegisterHotKey failed for %r (already in use?)", sequence)
            return False
        window._global_hotkey = (hwnd, SUMMON_HOTKEY_ID)  # type: ignore[attr-defined]
        return True
    except Exception:
        log.warning("global hotkey registration failed", exc_info=True)
        return False


def unregister_summon_hotkey(window: object) -> None:
    """Unregister the summon hotkey previously stored on the window."""
    info = getattr(window, "_global_hotkey", None)
    if not info or sys.platform != "win32":
        return
    hwnd, hotkey_id = info
    try:
        import ctypes

        ctypes.windll.user32.UnregisterHotKey(hwnd, hotkey_id)
    except Exception:
        log.debug("UnregisterHotKey failed", exc_info=True)
    window._global_hotkey = None  # type: ignore[attr-defined]


def is_summon_hotkey_message(message: object) -> bool:
    """True when a native windows message is our WM_HOTKEY."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))  # type: ignore[arg-type]
        return int(msg.message) == WM_HOTKEY and int(msg.wParam) == SUMMON_HOTKEY_ID
    except Exception:
        log.debug("WM_HOTKEY parse failed", exc_info=True)
        return False
