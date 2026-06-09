"""Build the text-presence-over-time corpus from per-frame OCR.

For each distinct on-screen string we record the frames/timestamps it appeared
on, how long it was on screen (count of frames x sample interval), worst-case
legibility (min height ratio, min contrast), and the worst OCR confidence. This
is what lets a check reason about disclaimer *dwell time* and *legibility*.
"""

from __future__ import annotations

import re

from ..schemas import FrameOcr, TextAppearance, VisualCorpus


def _normalize(text: str) -> str:
    """Loose normalization for grouping near-identical detections across frames."""
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\sऀ-ॿ]", "", t)  # keep word chars + Devanagari block
    return t


def build_corpus(
    frame_ocrs: list[FrameOcr],
    sample_interval_seconds: float,
    ocr_low_confidence: float,
    frame_paths: dict[int, str] | None = None,
    static_image: bool = False,
) -> VisualCorpus:
    # Group detections by normalized text, keeping the best (longest) raw form.
    groups: dict[str, dict] = {}

    for fo in frame_ocrs:
        for det in fo.detections:
            key = _normalize(det.text)
            if not key:
                continue
            g = groups.setdefault(
                key,
                {
                    "display": det.text,
                    "frame_indices": [],
                    "timestamps": [],
                    "height_ratios": [],
                    "contrasts": [],
                    "confidences": [],
                },
            )
            # Prefer the longest raw spelling as the display form.
            if len(det.text) > len(g["display"]):
                g["display"] = det.text
            g["frame_indices"].append(fo.frame_index)
            g["timestamps"].append(fo.timestamp_seconds)
            g["height_ratios"].append(det.height_ratio)
            if det.contrast is not None:
                g["contrasts"].append(det.contrast)
            g["confidences"].append(det.confidence)

    appearances: list[TextAppearance] = []
    for g in groups.values():
        n_frames = len(set(g["frame_indices"]))
        min_conf = min(g["confidences"])
        appearances.append(
            TextAppearance(
                text=g["display"],
                frame_indices=sorted(set(g["frame_indices"])),
                timestamps=sorted(set(g["timestamps"])),
                # Each sampled frame represents one interval of on-screen presence.
                on_screen_seconds=n_frames * sample_interval_seconds,
                min_height_ratio=min(g["height_ratios"]),
                max_height_ratio=max(g["height_ratios"]),
                min_contrast=min(g["contrasts"]) if g["contrasts"] else None,
                min_ocr_confidence=min_conf,
                low_confidence=min_conf < ocr_low_confidence,
            )
        )

    # Longest-on-screen first — most relevant for disclaimer reasoning.
    appearances.sort(key=lambda a: a.on_screen_seconds, reverse=True)

    return VisualCorpus(
        sample_interval_seconds=sample_interval_seconds,
        frames=frame_ocrs,
        appearances=appearances,
        frame_paths=frame_paths or {},
        static_image=static_image,
    )
