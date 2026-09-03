"""Tests for vision payload preparation (app.core.imaging)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.imaging import (
    downscale_for_vision,
    normalize_to_png,
    prepare_for_ocr,
    sniff_image_mime,
)


def _png_bytes(w: int, h: int, *, alpha: bool = False, noise: bool = False) -> bytes:
    """Build a test PNG; noise makes it incompressible (like a screenshot)."""
    mode = "RGBA" if alpha else "RGB"
    img = Image.new(mode, (w, h))
    if noise:
        px = img.load()
        for y in range(0, h, 5):
            for x in range(0, w, 5):
                if alpha:
                    px[x, y] = (x % 256, y % 256, (x * y) % 256, 255)
                else:
                    px[x, y] = (x % 256, y % 256, (x * y) % 256)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_small_image_passthrough() -> None:
    small = _png_bytes(200, 100)
    assert downscale_for_vision(small) is small


def test_large_image_downscaled_to_max_dim() -> None:
    big = _png_bytes(4000, 2000, noise=True)
    out = downscale_for_vision(big, max_dim=2000)
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == 2000
        assert img.size == (2000, 1000)
    assert len(out) < len(big)


def test_large_opaque_image_becomes_jpeg() -> None:
    big = _png_bytes(3000, 1500, noise=True)
    out = downscale_for_vision(big, max_dim=2000)
    assert sniff_image_mime(out) == "image/jpeg"


def test_alpha_image_stays_png() -> None:
    big = _png_bytes(3000, 1500, alpha=True, noise=True)
    out = downscale_for_vision(big, max_dim=2000)
    assert sniff_image_mime(out) == "image/png"
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= 2000


def test_undecodable_input_returned_unchanged() -> None:
    garbage = b"\x00\x01\x02 not an image"
    assert downscale_for_vision(garbage) is garbage


def test_sniff_image_mime() -> None:
    assert sniff_image_mime(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert sniff_image_mime(b"\xff\xd8\xff\xe0....") == "image/jpeg"
    assert sniff_image_mime(b"GIF89a....") == "image/gif"
    assert sniff_image_mime(b"BM....") == "image/bmp"
    assert sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"
    assert sniff_image_mime(b"whatever") == "application/octet-stream"


def test_downscale_never_upsizes() -> None:
    # 1500x800 within max_dim=1000? No: larger edge 1500 > 1000 → scale down.
    mid = _png_bytes(1500, 800, noise=True)
    out = downscale_for_vision(mid, max_dim=1000)
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == 1000


@pytest.mark.parametrize("max_dim", [500, 1000, 2000])
def test_downscale_respects_limit(max_dim: int) -> None:
    big = _png_bytes(4000, 3000, noise=True)
    out = downscale_for_vision(big, max_dim=max_dim)
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= max_dim


# ── prepare_for_ocr ───────────────────────────────────────────────
def test_ocr_small_image_upscaled() -> None:
    small = _png_bytes(400, 300)
    out = prepare_for_ocr(small)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (800, 600)


def test_ocr_large_image_untouched() -> None:
    big = _png_bytes(1200, 900)
    assert prepare_for_ocr(big) is big


def test_ocr_upscale_capped_at_max_dim() -> None:
    tiny = _png_bytes(500, 100)
    out = prepare_for_ocr(tiny, max_dim=600)
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == 600


def test_ocr_undecodable_unchanged() -> None:
    garbage = b"not an image at all"
    assert prepare_for_ocr(garbage) is garbage


# ── normalize_to_png ──────────────────────────────────────────────
def test_normalize_converts_foreign_format_to_png() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(buf, format="JPEG")
    out = normalize_to_png(buf.getvalue())
    assert sniff_image_mime(out) == "image/png"
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (8, 8)


def test_normalize_preserves_alpha() -> None:
    src = _png_bytes(8, 8, alpha=True)
    out = normalize_to_png(src)
    with Image.open(io.BytesIO(out)) as img:
        assert img.mode == "RGBA"


def test_normalize_is_idempotent_for_png() -> None:
    src = _png_bytes(8, 8)
    out = normalize_to_png(src)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (8, 8)
    assert sniff_image_mime(out) == "image/png"


def test_normalize_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        normalize_to_png(b"\x00\x01\x02 not an image")


def test_normalize_rejects_empty_payload() -> None:
    with pytest.raises(ValueError):
        normalize_to_png(b"")
