"""End-to-end orchestration: video -> artifacts -> per-check verdicts -> report.

Every intermediate artifact (sampled frames, OCR, transcript, corpus) is written
under ``out/<video_id>/`` so a human can audit any verdict. The two pipelines are
independent; either can be skipped (e.g. for incremental verification), and
checks that depended on a skipped surface degrade to ``uncertain`` (fail-safe).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import EngineConfig, checks_hash
from .routing import route
from .schemas import (
    Check,
    CheckResult,
    CheckStatus,
    Transcript,
    VideoReport,
    VisualCorpus,
)


def _video_id(video_path: Path) -> str:
    return video_path.stem


# --------------------------------------------------------------------------- #
# Pipeline runners (each independently runnable / dumps its artifacts)         #
# --------------------------------------------------------------------------- #
def run_visual(video_path: Path, artifacts_dir: Path, cfg: EngineConfig) -> tuple[VisualCorpus, float]:
    from .visual.corpus import build_corpus
    from .visual.ocr import read_frames_concurrent
    from .visual.sampling import sample_frames

    vc = cfg.visual
    frames, duration = sample_frames(
        video_path,
        artifacts_dir,
        interval_seconds=vc.sample_interval_seconds,
        scene_detect=vc.scene_detect,
        scene_threshold=vc.scene_threshold,
        max_workers=vc.frame_extract_workers,
    )
    # OCR every frame across a warm, pre-built engine pool (index-ordered output).
    frame_ocrs = read_frames_concurrent(
        frames, vc.backend, vc.ocr_languages,
        detection_model=vc.ocr_detection_model, max_width=vc.ocr_max_width,
        max_workers=vc.ocr_max_workers,
    )
    frame_paths = {f.frame_index: str(f.path) for f in frames}

    corpus = build_corpus(
        frame_ocrs,
        sample_interval_seconds=vc.sample_interval_seconds,
        ocr_low_confidence=vc.ocr_low_confidence,
        frame_paths=frame_paths,
    )

    (artifacts_dir / "ocr.json").write_text(
        json.dumps([fo.model_dump(mode="json") for fo in frame_ocrs], indent=2, ensure_ascii=False)
    )
    (artifacts_dir / "corpus.json").write_text(
        json.dumps(corpus.model_dump(mode="json"), indent=2, ensure_ascii=False)
    )
    return corpus, duration


def run_image(image_path: Path, artifacts_dir: Path, cfg: EngineConfig) -> VisualCorpus:
    """Visual pipeline for a single still image (no ffmpeg sampling).

    Treats the image as a one-frame corpus so the same fusion/routing path can
    review a static creative. Dumps ``ocr.json`` / ``corpus.json`` like
    ``run_visual`` for a consistent audit trail.
    """
    from PIL import Image

    from .visual.corpus import build_corpus
    from .visual.ocr import get_ocr_pool
    from .visual.sampling import SampledFrame

    vc = cfg.visual
    # Normalize any input format (png/webp/bmp/jpg) to a single JPEG frame, the
    # same invariant the video path and the vision API client rely on (the
    # client sends frames as image/jpeg).
    frames_dir = artifacts_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    jpg_path = frames_dir / "frame_0000_0000.000.jpg"
    Image.open(image_path).convert("RGB").save(jpg_path, "JPEG", quality=95)

    engine = get_ocr_pool(
        vc.backend, vc.ocr_languages,
        vc.ocr_detection_model, vc.ocr_max_width, size=1,
    )[0]
    frame = SampledFrame(
        frame_index=0, timestamp_seconds=0.0, path=jpg_path, is_scene_cut=False
    )
    frame_ocr = engine.read_frame(frame)

    corpus = build_corpus(
        [frame_ocr],
        sample_interval_seconds=vc.sample_interval_seconds,
        ocr_low_confidence=vc.ocr_low_confidence,
        frame_paths={0: str(jpg_path)},
        static_image=True,  # a still has no on-screen duration
    )

    (artifacts_dir / "ocr.json").write_text(
        json.dumps([frame_ocr.model_dump(mode="json")], indent=2, ensure_ascii=False)
    )
    (artifacts_dir / "corpus.json").write_text(
        json.dumps(corpus.model_dump(mode="json"), indent=2, ensure_ascii=False)
    )
    return corpus


def run_audio(video_path: Path, artifacts_dir: Path, cfg: EngineConfig) -> Transcript:
    from .audio.asr import build_asr_engine, extract_audio

    audio_path = extract_audio(video_path, artifacts_dir)
    engine = build_asr_engine(cfg.audio.backend, cfg.audio)
    transcript = engine.transcribe(audio_path)

    (artifacts_dir / "transcript.json").write_text(
        json.dumps(transcript.model_dump(mode="json"), indent=2, ensure_ascii=False)
    )
    return transcript


# --------------------------------------------------------------------------- #
# Full run                                                                     #
# --------------------------------------------------------------------------- #
def run_video(
    video_path: Path | str,
    checks: list[Check],
    cfg: EngineConfig,
    out_root: Path | str = "out",
    skip_visual: bool = False,
    skip_audio: bool = False,
    stub: bool = False,
) -> VideoReport:
    video_path = Path(video_path)
    video_id = _video_id(video_path)
    artifacts_dir = Path(out_root) / video_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if stub:
        # Scaffold mode: no ML deps, no API. Everything is uncertain (fail-safe).
        return _stub_report(video_id, checks, cfg)

    corpus: Optional[VisualCorpus] = None
    transcript: Optional[Transcript] = None
    visual_duration = 0.0

    # The visual and audio pipelines are independent and both release the GIL
    # during native inference, so overlap them — wall-clock becomes max(visual,
    # audio) instead of the sum. Each writes its own disjoint artifacts.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        visual_future = (
            pool.submit(run_visual, video_path, artifacts_dir, cfg)
            if not skip_visual else None
        )
        audio_future = (
            pool.submit(run_audio, video_path, artifacts_dir, cfg)
            if not skip_audio else None
        )
        if visual_future is not None:
            corpus, visual_duration = visual_future.result()
        if audio_future is not None:
            transcript = audio_future.result()

    duration = visual_duration
    if transcript is not None and transcript.segments:
        duration = max(duration, max(s.end for s in transcript.segments))

    from .claude_client import ClaudeClient
    from .fusion.evaluate import evaluate_all

    client = ClaudeClient(model=cfg.model, max_tokens=cfg.max_tokens)
    results = evaluate_all(
        checks, corpus, transcript, client,
        max_workers=cfg.fusion.max_parallel_checks,
    )

    return route(
        video_id, duration, results,
        policy_version=cfg.policy.version,
        policy_source=cfg.policy.source_file,
        checks_hash=checks_hash(),
    )


def _stub_report(
    video_id: str,
    checks: list[Check],
    cfg: EngineConfig | None = None,
) -> VideoReport:
    results = [
        CheckResult(
            check_id=c.id,
            status=CheckStatus.uncertain,
            severity=c.severity,
            confidence=0.0,
            surfaces_evaluated=(["visual", "audio"] if c.surface.value == "both" else [c.surface.value]),
            reasoning="STUB: pipelines not run (scaffold mode). Fail-safe default is uncertain.",
            evidence=[],
            policy_ref=c.policy_ref,
            low_confidence_inputs=True,
        )
        for c in checks
    ]
    return route(
        video_id, 0.0, results,
        policy_version=cfg.policy.version if cfg else None,
        policy_source=cfg.policy.source_file if cfg else None,
        checks_hash=checks_hash() if cfg else None,
    )
