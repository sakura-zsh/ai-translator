"""Screenshot capture via slurp + grim (Wayland)."""

from __future__ import annotations

import shutil
import subprocess


class ScreenshotError(Exception):
    pass


class ScreenshotCancelled(ScreenshotError):
    pass


class ScreenshotService:
    def __init__(
        self,
        slurp_bin: str = "slurp",
        grim_bin: str = "grim",
        timeout_s: float = 120.0,
    ) -> None:
        self.slurp_bin = slurp_bin
        self.grim_bin = grim_bin
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return bool(shutil.which(self.slurp_bin) and shutil.which(self.grim_bin))

    def capture_region(self) -> bytes:
        """Interactive region select → PNG bytes. Raises ScreenshotCancelled on Esc."""
        if not shutil.which(self.slurp_bin):
            raise ScreenshotError(
                f"'{self.slurp_bin}' not found. Install slurp for region selection."
            )
        if not shutil.which(self.grim_bin):
            raise ScreenshotError(
                f"'{self.grim_bin}' not found. Install grim for screenshots."
            )

        try:
            slurp = subprocess.run(
                [self.slurp_bin],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError("Region selection timed out") from exc
        except OSError as exc:
            raise ScreenshotError(f"Failed to run slurp: {exc}") from exc

        geometry = (slurp.stdout or "").strip()
        if slurp.returncode != 0 or not geometry:
            raise ScreenshotCancelled("Screenshot cancelled")

        try:
            grim = subprocess.run(
                [self.grim_bin, "-g", geometry, "-"],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError("Screenshot capture timed out") from exc
        except OSError as exc:
            raise ScreenshotError(f"Failed to run grim: {exc}") from exc

        if grim.returncode != 0 or not grim.stdout:
            err = (grim.stderr or b"").decode("utf-8", errors="replace")[:300]
            raise ScreenshotError(f"grim failed: {err or 'no image data'}")

        return grim.stdout
