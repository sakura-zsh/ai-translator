"""Image payload helpers shared by clipboard / screenshot backends and the
vision translation path."""

from __future__ import annotations

import io

from PIL import Image

# Vision models cap useful input resolution; sending a 4K screenshot as PNG
# only burns tokens and upload time. Longest edge is clamped to this.
VISION_MAX_DIM = 2000
VISION_JPEG_QUALITY = 85
# Small in-bounds payloads pass through untouched (no pointless re-encode).
_PASSTHROUGH_BYTES = 256 * 1024


def sniff_image_mime(data: bytes) -> str:
    """Best-effort MIME detection from magic bytes (for data: URLs)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def downscale_for_vision(
    png: bytes,
    *,
    max_dim: int = VISION_MAX_DIM,
    jpeg_quality: int = VISION_JPEG_QUALITY,
) -> bytes:
    """Return a compact image payload for vision models.

    - Downscales so the longest edge is <= ``max_dim`` (resolution, not
      bytes, drives vision token cost — downscaling is unconditional when
      oversized).
    - Opaque images are re-encoded as JPEG; images with alpha stay PNG.
    - Within-bounds small payloads pass through untouched; within-bounds
      large payloads keep whichever of (original, re-encoded) is smaller.
    - Undecodable input is returned unchanged so the API surfaces the error.
    """
    try:
        with Image.open(io.BytesIO(png)) as img:
            img.load()
            w, h = img.size
            oversized = max(w, h) > max_dim

            if not oversized and len(png) <= _PASSTHROUGH_BYTES:
                return png  # already small enough

            if oversized:
                scale = max_dim / float(max(w, h))
                new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                img.mode == "P" and "transparency" in img.info
            )

            out = io.BytesIO()
            if has_alpha:
                img.save(out, format="PNG", optimize=True)
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
            encoded = out.getvalue()

            if oversized:
                return encoded
            return encoded if len(encoded) < len(png) else png
    except Exception:
        return png



def prepare_for_ocr(
    png: bytes,
    *,
    upscale_below: int = 1000,
    max_dim: int = 2400,
) -> bytes:
    """Upscale small screenshots before OCR.

    Tesseract accuracy drops sharply on small UI text; doubling a sub-1000px
    capture is a cheap, reliable win. Larger images pass through untouched
    (tesseract binarizes internally, so no grayscale/threshold needed).
    Undecodable input is returned unchanged.
    """
    try:
        with Image.open(io.BytesIO(png)) as img:
            img.load()
            w, h = img.size
            longest = max(w, h)
            if longest >= upscale_below:
                return png
            scale = min(2.0, max_dim / float(longest))
            if scale <= 1.0:
                return png
            img = img.resize(
                (max(1, round(w * scale)), max(1, round(h * scale))),
                Image.Resampling.LANCZOS,
            )
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return png
