"""Locate the ffmpeg/ffprobe binaries robustly.

Prefers a system ffmpeg on PATH, but falls back to the static binary bundled by
the pip package ``imageio-ffmpeg``. This matters on locked-down machines where a
shared Homebrew can't be written to. Duration probing falls back to OpenCV when
ffprobe is unavailable (imageio-ffmpeg ships ffmpeg but not ffprobe).
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    """Path to an ffmpeg binary, or raise with install guidance."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # lazy

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        raise RuntimeError(
            "No ffmpeg available. Either install it (macOS: `brew install ffmpeg`) "
            "or `pip install imageio-ffmpeg` to use the bundled static binary."
        )


@lru_cache(maxsize=1)
def ffprobe_bin() -> str | None:
    """Path to ffprobe if present on PATH, else None (no static fallback)."""
    return shutil.which("ffprobe")


def probe_duration_seconds(video_path: Path | str) -> float:
    """Duration in seconds via ffprobe, falling back to OpenCV."""
    probe = ffprobe_bin()
    if probe:
        out = subprocess.run(
            [
                probe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())

    # Fallback: OpenCV (part of the [visual] extra).
    try:
        import cv2  # lazy

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        cap.release()
        if fps > 0 and frames > 0:
            return float(frames) / float(fps)
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(
        "Could not determine video duration: no ffprobe on PATH and OpenCV "
        "fallback failed. Install ffmpeg (with ffprobe) or the [visual] extra."
    )
