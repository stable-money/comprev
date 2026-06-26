"""Job runner: run the slow engine off the request thread, track coarse stages.

The engine (``comprev.engine.run_video``) is synchronous and multi-minute, and
PaddleOCR / faster-whisper are GIL-bound — so we run each job in a
``ProcessPoolExecutor`` (one worker, runs serialized) rather than a thread.

The engine exposes no progress callbacks, so the worker *replicates*
``run_video``'s body by calling its individually-importable sub-functions and
pushing the current stage into a ``multiprocessing.Manager`` dict between each.
Finished reports persist to ``out/`` (shared with the CLI); the in-memory job
registry is intentionally volatile — losing it on restart only loses live
progress, never a verdict.
"""

from __future__ import annotations

import multiprocessing as mp
import shutil
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Optional

# web/api/comprev_web/jobs.py -> repo root is parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_ROOT = REPO_ROOT / "out"
UPLOAD_ROOT = REPO_ROOT / "uploads"

# Process-pool runtime, created lazily in the parent (never at import, so the
# spawned worker re-importing this module does not build its own pool/manager).
_ctx = mp.get_context("spawn")
_manager: Optional[Any] = None
_jobs: Optional[Any] = None  # manager dict: job_id -> JobState dict
_pool: Optional[ProcessPoolExecutor] = None


def _ensure_runtime() -> tuple[Any, ProcessPoolExecutor]:
    global _manager, _jobs, _pool
    if _pool is None:
        _manager = _ctx.Manager()
        _jobs = _manager.dict()
        _pool = ProcessPoolExecutor(max_workers=1, mp_context=_ctx)
    return _jobs, _pool


def _set(jobs: Any, job_id: str, **changes: Any) -> None:
    """Reassign the whole value — manager dicts don't track nested mutation."""
    state = dict(jobs.get(job_id, {}))
    state.update(changes)
    jobs[job_id] = state


# --------------------------------------------------------------------------- #
# Worker (runs in a separate process)                                          #
# --------------------------------------------------------------------------- #
def _run_job(job_id: str, jobs: Any, video_path_str: str, out_root_str: str,
             options: dict) -> None:
    from comprev.config import (
        checks_hash,
        checks_path_for,
        load_checks,
        load_engine_config,
        resolve_product,
    )
    from comprev.engine import run_audio, run_image, run_visual, _stub_report
    from comprev.report import write_report
    from comprev.routing import route

    media_path = Path(video_path_str)
    out_root = Path(out_root_str)
    video_id = media_path.stem
    kind = options.get("kind", "video")  # "video" | "image" | "audio"
    product = options.get("product", "mutual_funds")

    try:
        cfg = load_engine_config()
        pc = resolve_product(cfg, product)
        checks_file = checks_path_for(pc)
        checks = load_checks(checks_file)
        if options.get("fast"):
            # Speed overrides mirror CLI --fast (lower fidelity).
            cfg.visual.ocr_detection_model = "PP-OCRv5_mobile_det"
            cfg.visual.ocr_max_width = 720
            cfg.audio.model = "medium"

        # CPU-thread budget: cap each PaddleOCR predictor's native (OpenMP)
        # threads so a pool of OCR engines running concurrently with Whisper
        # doesn't oversubscribe the cores. Must be set BEFORE the native libs
        # are imported (they read these once), i.e. before the pipeline runs.
        import os
        os.environ["OMP_NUM_THREADS"] = str(cfg.visual.ocr_cpu_threads)
        os.environ["MKL_NUM_THREADS"] = str(cfg.visual.ocr_cpu_threads)

        artifacts_dir = out_root / video_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Keep the original upload alongside the artifacts so the report page can
        # play/show what was reviewed. Named ``source<ext>`` (stable, keyed by
        # video_id) since the upload itself lives under a throwaway uuid dir.
        source_copy = artifacts_dir / f"source{media_path.suffix.lower()}"
        try:
            if media_path.resolve() != source_copy.resolve():
                shutil.copy2(media_path, source_copy)
        except OSError:
            pass  # preview is best-effort; never fail a run over it

        if options.get("stub"):
            report = _stub_report(video_id, checks, cfg, product=product)
            write_report(report, out_root)
            _set(jobs, job_id, stage="done", report_ready=True)
            return

        corpus = None
        transcript = None
        duration = 0.0

        # Dispatch by input kind. Image runs only the visual pipeline (on a
        # single still); audio runs only transcription; video runs both. Checks
        # tied to an absent surface degrade to "uncertain" (fail-safe).
        if kind == "image":
            _set(jobs, job_id, stage="sampling")
            corpus = run_image(media_path, artifacts_dir, cfg)
        elif kind == "audio":
            _set(jobs, job_id, stage="transcribing")
            transcript = run_audio(media_path, artifacts_dir, cfg)
            if transcript.segments:
                duration = max(s.end for s in transcript.segments)
        else:  # video — overlap the independent visual + audio pipelines
            from concurrent.futures import ThreadPoolExecutor

            _set(jobs, job_id, stage="sampling")
            with ThreadPoolExecutor(max_workers=2) as pipelines:
                visual_future = pipelines.submit(run_visual, media_path, artifacts_dir, cfg)
                audio_future = pipelines.submit(run_audio, media_path, artifacts_dir, cfg)
                corpus, duration = visual_future.result()
                transcript = audio_future.result()
            if transcript.segments:
                duration = max(duration, max(s.end for s in transcript.segments))

        _set(jobs, job_id, stage="evaluating")
        from comprev.claude_client import ClaudeClient
        from comprev.fusion.evaluate import evaluate_all

        client = ClaudeClient(model=cfg.model, max_tokens=cfg.max_tokens)
        results = evaluate_all(
            checks, corpus, transcript, client,
            max_workers=cfg.fusion.max_parallel_checks,
        )

        _set(jobs, job_id, stage="routing")
        report = route(
            video_id, duration, results,
            product=product,
            policy_version=pc.policy.version,
            policy_source=pc.policy.source_file,
            checks_hash=checks_hash(checks_file),
        )
        write_report(report, out_root)
        _set(jobs, job_id, stage="done", report_ready=True)
    except Exception as exc:  # noqa: BLE001 — surface any failure as job error
        _set(jobs, job_id, stage="error", error=f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Parent-side API                                                              #
# --------------------------------------------------------------------------- #
def submit_job(video_path: Path, options: dict) -> tuple[str, str]:
    jobs, pool = _ensure_runtime()
    job_id = uuid.uuid4().hex
    video_id = video_path.stem
    jobs[job_id] = {
        "job_id": job_id,
        "video_id": video_id,
        "kind": options.get("kind", "video"),
        "product": options.get("product", "mutual_funds"),
        "stage": "queued",
        "report_ready": False,
        "error": None,
    }
    pool.submit(_run_job, job_id, jobs, str(video_path), str(OUT_ROOT), options)
    return job_id, video_id


def get_job(job_id: str) -> Optional[dict]:
    jobs, _ = _ensure_runtime()
    state = jobs.get(job_id)
    return dict(state) if state is not None else None


def list_jobs() -> list[dict]:
    """All jobs currently in the volatile registry."""
    jobs, _ = _ensure_runtime()
    return [dict(state) for state in jobs.values()]


def report_path(video_id: str) -> Path:
    return OUT_ROOT / f"{video_id}.json"


def report_exists(video_id: str) -> bool:
    return report_path(video_id).exists()
