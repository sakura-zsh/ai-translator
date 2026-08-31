"""Read image bytes from the Wayland clipboard via wl-paste."""

from __future__ import annotations

import io
import shutil
import subprocess

from PIL import Image

from app.core.clipboard_image import ClipboardImageError


class ClipboardImageService:
    def __init__(self, wl_paste_bin: str = "wl-paste", timeout_s: float = 10.0) -> None:
        self.wl_paste_bin = wl_paste_bin
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(shutil.which(self.wl_paste_bin))

    def list_types(self) -> list[str]:
        if not shutil.which(self.wl_paste_bin):
            raise ClipboardImageError(
                "wl-paste not found. Install wl-clipboard."
            )
        try:
            proc = subprocess.run(
                [self.wl_paste_bin, "--list-types"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ClipboardImageError(f"Failed to list clipboard types: {exc}") from exc
        if proc.returncode != 0:
            return []
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]

    def read_png(self) -> bytes:
        types = self.list_types()
        image_types = [t for t in types if t.startswith("image/")]
        if types and not image_types:
            # Types are known and contain no image — fail fast instead of
            # spawning one wl-paste per candidate mime below. This keeps
            # plain-text paste (the common case) from doing ~6 subprocess
            # round-trips before falling back to Qt.
            raise ClipboardImageError("Clipboard has no image data")
        if not image_types:
            # Prefer common order if list is empty/odd
            candidates = [
                "image/png",
                "image/jpeg",
                "image/jpg",
                "image/webp",
                "image/bmp",
                "image/gif",
            ]
        else:
            preferred = ["image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"]
            ordered = [t for t in preferred if t in image_types]
            ordered += [t for t in image_types if t not in ordered]
            candidates = ordered

        last_err: Exception | None = None
        for mime in candidates:
            try:
                raw = self._paste_type(mime)
                if raw:
                    return self._to_png(raw)
            except Exception as exc:  # noqa: BLE001 — try next mime
                last_err = exc
                continue

        if last_err:
            raise ClipboardImageError(f"No usable image in clipboard: {last_err}")
        raise ClipboardImageError("Clipboard has no image data")

    def _paste_type(self, mime: str) -> bytes:
        try:
            proc = subprocess.run(
                [self.wl_paste_bin, "--type", mime, "--no-newline"],
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ClipboardImageError(f"wl-paste failed: {exc}") from exc
        if proc.returncode != 0 or not proc.stdout:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:200]
            raise ClipboardImageError(f"No data for {mime}: {err}")
        return proc.stdout

    @staticmethod
    def _to_png(raw: bytes) -> bytes:
        try:
            with Image.open(io.BytesIO(raw)) as img:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
        except Exception as exc:  # PIL.UnidentifiedImageError etc.
            raise ClipboardImageError(f"Invalid image data: {exc}") from exc
