"""OCR via tesseract CLI."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class OcrError(Exception):
    pass


class OcrService:
    def __init__(self, tesseract_bin: str = "tesseract", timeout_s: float = 60.0) -> None:
        self.tesseract_bin = tesseract_bin
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(shutil.which(self.tesseract_bin))

    def extract_text(self, image_png: bytes, langs: str = "eng+chi_sim") -> str:
        if not shutil.which(self.tesseract_bin):
            raise OcrError(
                "tesseract not found. Install with: "
                "sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim"
            )
        if not image_png:
            raise OcrError("Empty image")

        with tempfile.TemporaryDirectory(prefix="ai-translator-ocr-") as tmp:
            img_path = Path(tmp) / "input.png"
            img_path.write_bytes(image_png)
            try:
                proc = subprocess.run(
                    [
                        self.tesseract_bin,
                        str(img_path),
                        "stdout",
                        "-l",
                        langs or "eng",
                        "--psm",
                        "6",
                    ],
                    capture_output=True,
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrError("OCR timed out") from exc
            except OSError as exc:
                raise OcrError(f"Failed to run tesseract: {exc}") from exc

            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")
                if "Error opening data file" in err or "Failed loading language" in err:
                    raise OcrError(
                        f"Missing tesseract language data for '{langs}'. "
                        "Install matching tesseract-data-* packages.\n"
                        f"{err[:300]}"
                    )
                raise OcrError(f"tesseract failed: {err[:400]}")

            text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
            if not text:
                raise OcrError("OCR produced no text")
            return text
