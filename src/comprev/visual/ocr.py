"""OCR behind an interface so the engine can be swapped.

Default implementation is PaddleOCR (Devanagari-capable, for Hinglish creatives).
The interface returns per-detection text, confidence, bounding box, and the
legibility proxies (height ratio + contrast) the corpus needs.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import SimpleQueue
from typing import Protocol

from ..schemas import BoundingBox, FrameOcr, OcrDetection
from .sampling import SampledFrame


class OcrEngine(Protocol):
    """Swappable OCR backend."""

    def read_frame(self, frame: SampledFrame) -> FrameOcr: ...


def _luminance(rgb: tuple[float, float, float]) -> float:
    """Relative luminance per WCAG, input channels in 0..255."""
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(lum_a: float, lum_b: float) -> float:
    hi, lo = max(lum_a, lum_b), min(lum_a, lum_b)
    return (hi + 0.05) / (lo + 0.05)


class PaddleOcrEngine:
    """PaddleOCR (3.x) backed implementation.

    Loads one recognizer per configured language — typically Latin (``en``) and
    Devanagari — and unions their detections, since a single PaddleOCR lang model
    won't cover both scripts in a Hinglish creative. Models are lazily built on
    first use; the doc-orientation / unwarping stages are disabled for speed.
    """

    def __init__(
        self,
        languages: list[str] | None = None,
        detection_model: str | None = None,
        max_width: int | None = None,
    ):
        self._languages = languages or ["en", "hi"]
        self._detection_model = detection_model  # None => PaddleOCR default (server)
        self._max_width = max_width              # None => no downscaling
        self._engines: dict[str, object] = {}

    def warm(self) -> None:
        """Eagerly build every language predictor (moves cold-build out of the
        timed loop and closes the lazy-build race when engines are shared)."""
        for lang in self._languages:
            self._engine_for(lang)

    def _engine_for(self, lang: str):
        # Cache the constructed engine, or None if this lang has no model
        # available — a missing script degrades that surface but must not crash
        # the whole pipeline.
        if lang not in self._engines:
            from paddleocr import PaddleOCR  # lazy import

            kwargs = dict(
                lang=lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            if self._detection_model:
                kwargs["text_detection_model_name"] = self._detection_model
            try:
                self._engines[lang] = PaddleOCR(**kwargs)
            except Exception as e:  # noqa: BLE001
                print(f"[ocr] language {lang!r} unavailable, skipping: {str(e).splitlines()[0]}")
                self._engines[lang] = None
        return self._engines[lang]

    def read_frame(self, frame: SampledFrame) -> FrameOcr:
        import numpy as np
        from PIL import Image

        img = Image.open(frame.path).convert("RGB")
        # Optional downscale for speed. Uniform scaling preserves height_ratio
        # (box_height / frame_height), so the legibility proxy is unaffected;
        # only absolute pixel boxes shrink (they aren't surfaced in the report).
        if self._max_width and img.width > self._max_width:
            new_h = round(img.height * self._max_width / img.width)
            img = img.resize((self._max_width, new_h), Image.LANCZOS)
        arr = np.asarray(img)
        h, w = arr.shape[0], arr.shape[1]

        detections: list[OcrDetection] = []
        seen: set[tuple[str, int, int]] = set()  # crude dedupe across lang models

        for lang in self._languages:
            engine = self._engine_for(lang)
            if engine is None:
                continue
            # PaddleOCR 3.x: predict() -> list of OCRResult dicts with parallel
            # lists rec_texts / rec_scores / rec_polys (4-point polygons).
            for res in engine.predict(arr) or []:
                texts = res.get("rec_texts", []) or []
                scores = res.get("rec_scores", []) or []
                polys = res.get("rec_polys", []) or res.get("dt_polys", []) or []
                for text, conf, poly in zip(texts, scores, polys):
                    if not text or not text.strip():
                        continue
                    xs = [float(p[0]) for p in poly]
                    ys = [float(p[1]) for p in poly]
                    x0, y0 = min(xs), min(ys)
                    bw, bh = max(xs) - x0, max(ys) - y0
                    key = (text.strip().lower(), int(x0 // 10), int(y0 // 10))
                    if key in seen:
                        continue
                    seen.add(key)

                    contrast = self._estimate_contrast(arr, x0, y0, bw, bh, w, h)
                    detections.append(
                        OcrDetection(
                            text=text.strip(),
                            confidence=float(conf),
                            box=BoundingBox(x=x0, y=y0, width=bw, height=bh),
                            height_ratio=bh / float(h) if h else 0.0,
                            contrast=contrast,
                        )
                    )

        return FrameOcr(
            frame_index=frame.frame_index,
            timestamp_seconds=frame.timestamp_seconds,
            is_scene_cut=frame.is_scene_cut,
            frame_width=w,
            frame_height=h,
            detections=detections,
        )

    @staticmethod
    def _estimate_contrast(arr, x0, y0, bw, bh, w, h) -> float | None:
        """Estimate text-vs-background contrast around a detection box.

        Compares mean luminance inside the box to a thin ring just outside it.
        Best-effort: returns None if the box is degenerate.
        """
        import numpy as np

        try:
            ix0, iy0 = max(int(x0), 0), max(int(y0), 0)
            ix1, iy1 = min(int(x0 + bw), w), min(int(y0 + bh), h)
            if ix1 <= ix0 or iy1 <= iy0:
                return None
            inside = arr[iy0:iy1, ix0:ix1].reshape(-1, 3).mean(axis=0)

            pad = max(2, int(bh * 0.3))
            ox0, oy0 = max(ix0 - pad, 0), max(iy0 - pad, 0)
            ox1, oy1 = min(ix1 + pad, w), min(iy1 + pad, h)
            outer = arr[oy0:oy1, ox0:ox1].reshape(-1, 3).mean(axis=0)

            return _contrast_ratio(_luminance(tuple(inside)), _luminance(tuple(outer)))
        except Exception:  # noqa: BLE001
            return None


def build_ocr_engine(
    backend: str,
    languages: list[str],
    detection_model: str | None = None,
    max_width: int | None = None,
) -> OcrEngine:
    if backend == "paddleocr":
        return PaddleOcrEngine(
            languages=languages, detection_model=detection_model, max_width=max_width
        )
    # PHASE 2: register additional OCR backends (e.g. cloud OCR) here.
    raise ValueError(f"Unknown OCR backend: {backend!r}")


# --------------------------------------------------------------------------- #
# Warm engine-pool cache + concurrent frame reader                             #
# --------------------------------------------------------------------------- #
# A pool of pre-warmed engines, cached per (config, size) so the reused worker
# process never cold-loads models twice, and so the per-frame OCR loop can run
# `size` frames concurrently (each engine is used by one thread at a time).
_POOL_CACHE: dict[tuple, list[OcrEngine]] = {}
_POOL_LOCK = threading.Lock()


def get_ocr_pool(
    backend: str,
    languages: list[str],
    detection_model: str | None,
    max_width: int | None,
    size: int,
) -> list[OcrEngine]:
    size = max(1, size)
    key = (backend, tuple(languages), detection_model, max_width, size)
    with _POOL_LOCK:
        pool = _POOL_CACHE.get(key)
        if pool is None:
            pool = [
                build_ocr_engine(backend, languages, detection_model, max_width)
                for _ in range(size)
            ]
            for engine in pool:  # eager build so the timed loop has no cold start
                if hasattr(engine, "warm"):
                    engine.warm()  # type: ignore[attr-defined]
            _POOL_CACHE[key] = pool
        return pool


def read_frames_concurrent(
    frames: list[SampledFrame],
    backend: str,
    languages: list[str],
    detection_model: str | None,
    max_width: int | None,
    max_workers: int,
) -> list[FrameOcr]:
    """OCR every frame, fanned out across a pre-warmed engine pool.

    Results are gathered **by index**, so ``ocr.json`` is identical to a serial
    run. Each engine is checked out of a queue and used by exactly one thread at
    a time (PaddleOCR predictors are not thread-safe to share concurrently).
    """
    workers = max(1, min(max_workers, len(frames))) if frames else 1
    pool = get_ocr_pool(backend, languages, detection_model, max_width, workers)
    if workers == 1:
        return [pool[0].read_frame(f) for f in frames]

    available: SimpleQueue = SimpleQueue()
    for engine in pool:
        available.put(engine)

    def _read(frame: SampledFrame) -> FrameOcr:
        engine = available.get()
        try:
            return engine.read_frame(frame)
        finally:
            available.put(engine)

    results: list[FrameOcr | None] = [None] * len(frames)
    with ThreadPoolExecutor(max_workers=workers) as pool_exec:
        futures = {pool_exec.submit(_read, f): i for i, f in enumerate(frames)}
        for future, i in futures.items():
            results[i] = future.result()
    return results  # type: ignore[return-value]  # all slots filled above
