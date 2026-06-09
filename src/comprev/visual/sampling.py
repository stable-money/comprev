"""Frame sampling: fixed-interval frames + extra frames at scene cuts.

Uses ffmpeg for extraction and PySceneDetect to locate scene cuts (where a
disclaimer is likely to appear/disappear). All sampled frames are written to
``<artifacts_dir>/frames/`` so any verdict that cites a frame can be audited.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..media import ffmpeg_bin, probe_duration_seconds


@dataclass
class SampledFrame:
    frame_index: int          # monotonic index in sampling order
    timestamp_seconds: float
    path: Path
    is_scene_cut: bool


def get_duration_seconds(video_path: Path | str) -> float:
    """Probe duration (ffprobe, or OpenCV fallback)."""
    return probe_duration_seconds(video_path)


def _detect_scene_cut_times(video_path: Path, threshold: float) -> list[float]:
    """Return scene-cut start times (seconds) using PySceneDetect."""
    from scenedetect import ContentDetector, detect  # lazy import

    scenes = detect(str(video_path), ContentDetector(threshold=threshold))
    # Each scene is (start, end) FrameTimecode; the cut of interest is the start.
    return [start.get_seconds() for start, _end in scenes]


def _extract_frame(video_path: Path, timestamp: float, dest: Path) -> bool:
    """Extract a single JPEG at ``timestamp``. Returns True on success."""
    proc = subprocess.run(
        [
            ffmpeg_bin(), "-y", "-loglevel", "error",
            "-ss", f"{timestamp:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(dest),
        ],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and dest.exists()


def sample_frames(
    video_path: Path | str,
    artifacts_dir: Path | str,
    interval_seconds: float = 2.0,
    scene_detect: bool = True,
    scene_threshold: float = 27.0,
    max_workers: int = 4,
) -> tuple[list[SampledFrame], float]:
    """Sample frames at a fixed interval plus scene cuts.

    Returns (sorted unique sampled frames, duration_seconds). Frame extraction
    runs concurrently across ``max_workers`` ffmpeg subprocesses, but each runs
    the same command to the same path and the result is re-sorted by index, so
    output is identical to a serial run.
    """
    video_path = Path(video_path)
    frames_dir = Path(artifacts_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    duration = get_duration_seconds(video_path)

    # Fixed-interval timestamps.
    times: set[float] = set()
    t = 0.0
    while t < duration:
        times.add(round(t, 3))
        t += interval_seconds

    # Extra frames at scene cuts.
    cut_times: set[float] = set()
    if scene_detect:
        try:
            cut_times = {round(c, 3) for c in _detect_scene_cut_times(video_path, scene_threshold)}
        except Exception as e:  # noqa: BLE001
            # Scene detection is best-effort; interval sampling still proceeds.
            print(f"[sampling] scene detection skipped: {e}")
    times |= cut_times

    # The index is the position in sorted order (preserved even if some
    # extractions fail), matching the original serial enumeration exactly.
    plan = [
        (idx, ts, frames_dir / f"frame_{idx:04d}_{ts:08.3f}.jpg")
        for idx, ts in enumerate(sorted(times))
    ]

    def _extract(task: tuple[int, float, Path]) -> tuple[int, float, Path, bool]:
        idx, ts, dest = task
        return idx, ts, dest, _extract_frame(video_path, ts, dest)

    workers = max(1, min(max_workers, len(plan))) if plan else 1
    if workers == 1:
        results = [_extract(task) for task in plan]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_extract, plan))

    sampled = [
        SampledFrame(
            frame_index=idx,
            timestamp_seconds=ts,
            path=dest,
            is_scene_cut=ts in cut_times,
        )
        for idx, ts, dest, ok in sorted(results, key=lambda r: r[0])
        if ok
    ]

    return sampled, duration
