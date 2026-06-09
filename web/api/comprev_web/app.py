"""FastAPI application: upload → run → progress → report.

Run from the repo root with the backend package on the path:

    uv run uvicorn comprev_web.app:app --reload --port 8000 --app-dir web/api

``ANTHROPIC_API_KEY`` must be exported in the same shell for non-stub runs
(same mechanism as the CLI).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import jobs
from .models import Health, JobAccepted, JobStatus, ReportSummary

# Allowed file extensions per input kind.
ALLOWED_EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
CHUNK = 1024 * 1024

app = FastAPI(title="comprev web", version="0.1.0")

# Dev convenience: the Next dev server proxies /api, but allow direct CORS too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health / checks                                                              #
# --------------------------------------------------------------------------- #
@app.get("/api/health", response_model=Health)
def health() -> Health:
    ml_present = all(
        importlib.util.find_spec(m) is not None
        for m in ("paddleocr", "faster_whisper")
    )
    return Health(
        anthropic_key_present=bool(os.environ.get("ANTHROPIC_API_KEY")),
        ml_extras_present=ml_present,
    )


@app.get("/api/checks")
def list_checks() -> list[dict]:
    from comprev.config import load_checks

    return [c.model_dump(mode="json") for c in load_checks()]


# --------------------------------------------------------------------------- #
# Policies (the config files that drive every review)                          #
# --------------------------------------------------------------------------- #
def _policy_registry() -> dict[str, dict]:
    """Whitelisted policy source files, keyed by basename.

    The map is the only thing that can be read through ``/api/policies/{name}``,
    so there is no path-traversal surface — an arbitrary ``name`` simply 404s.
    """
    from comprev.config import DEFAULT_CHECKS_PATH, DEFAULT_ENGINE_PATH

    return {
        DEFAULT_CHECKS_PATH.name: {
            "path": DEFAULT_CHECKS_PATH,
            "title": "Compliance check library",
            "description": "The editable library of checks evaluated against every video.",
        },
        DEFAULT_ENGINE_PATH.name: {
            "path": DEFAULT_ENGINE_PATH,
            "title": "Engine configuration",
            "description": "Runtime knobs — model, sampling, OCR/ASR thresholds.",
        },
    }


@app.get("/api/policies")
def list_policies() -> list[dict]:
    from comprev.config import load_checks

    out: list[dict] = []
    for name, meta in _policy_registry().items():
        path: Path = meta["path"]
        if not path.exists():
            continue
        # Only the check library parses into discrete checks; engine.yaml is knobs.
        n_checks: int | None = None
        try:
            n_checks = len(load_checks(path))
        except Exception:
            n_checks = None
        out.append(
            {
                "name": name,
                "title": meta["title"],
                "description": meta["description"],
                "size_bytes": path.stat().st_size,
                "modified_at": path.stat().st_mtime,
                "n_checks": n_checks,
            }
        )
    return out


@app.get("/api/policies/{name}", response_class=PlainTextResponse)
def get_policy_source(name: str) -> str:
    meta = _policy_registry().get(name)
    if meta is None or not meta["path"].exists():
        raise HTTPException(status_code=404, detail=f"Unknown policy file {name!r}")
    return meta["path"].read_text()


# --------------------------------------------------------------------------- #
# Reports                                                                      #
# --------------------------------------------------------------------------- #
def _media_kind(ext: str) -> str | None:
    ext = ext.lower()
    for kind, exts in ALLOWED_EXTENSIONS.items():
        if ext in exts:
            return kind
    return None


def _source_media(video_id: str) -> Path | None:
    """The original upload copied into ``out/<video_id>/source.*`` at run time."""
    artifacts_dir = jobs.OUT_ROOT / video_id
    if not artifacts_dir.is_dir():
        return None
    for path in sorted(artifacts_dir.glob("source.*")):
        return path
    return None


@app.get("/api/reports", response_model=list[ReportSummary])
def list_reports() -> list[ReportSummary]:
    summaries: list[ReportSummary] = []
    for path in jobs.OUT_ROOT.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if "overall_status" not in data:  # skip non-report json
            continue
        video_id = data.get("video_id", path.stem)
        src = _source_media(video_id)
        summaries.append(
            ReportSummary(
                video_id=video_id,
                overall_status=data["overall_status"],
                needs_human_review=data.get("needs_human_review", True),
                duration_seconds=data.get("duration_seconds", 0.0),
                n_checks=len(data.get("checks", [])),
                modified_at=path.stat().st_mtime,
                media_kind=_media_kind(src.suffix) if src else None,
            )
        )
    summaries.sort(key=lambda s: s.modified_at, reverse=True)
    return summaries


@app.get("/api/reports/{video_id}")
def get_report(video_id: str) -> dict:
    path = jobs.report_path(video_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No report for {video_id!r}")
    data = json.loads(path.read_text())
    # Tell the UI whether a source preview exists and how to render it. Computed
    # from disk so the engine-written report JSON stays untouched.
    src = _source_media(video_id)
    data["media_kind"] = _media_kind(src.suffix) if src else None
    return data


def _sanitize_id(raw: str) -> str:
    """Make a user-supplied title safe to use as a report id / filename."""
    s = raw.replace("/", " ").replace("\\", " ")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80]


class RenameRequest(BaseModel):
    new_id: str


@app.post("/api/reports/{video_id}/rename")
def rename_report(video_id: str, req: RenameRequest) -> dict:
    """Rename a report: move every artifact keyed by the old id to the new one."""
    new_id = _sanitize_id(req.new_id)
    if not new_id:
        raise HTTPException(status_code=400, detail="Title cannot be empty.")
    if new_id == video_id:
        return {"video_id": video_id}

    old_json = jobs.report_path(video_id)
    if not old_json.exists():
        raise HTTPException(status_code=404, detail=f"No report for {video_id!r}")
    if jobs.report_path(new_id).exists() or (jobs.OUT_ROOT / new_id).exists():
        raise HTTPException(
            status_code=409, detail=f"A report named {new_id!r} already exists."
        )

    # Move the artifacts dir (carries frames/ and source.* with it).
    old_dir = jobs.OUT_ROOT / video_id
    if old_dir.is_dir():
        old_dir.rename(jobs.OUT_ROOT / new_id)
    # Move the markdown sibling, if any.
    old_md = jobs.OUT_ROOT / f"{video_id}.md"
    if old_md.exists():
        old_md.rename(jobs.OUT_ROOT / f"{new_id}.md")
    # Rewrite the report JSON under the new id (and update its video_id field).
    data = json.loads(old_json.read_text())
    data["video_id"] = new_id
    jobs.report_path(new_id).write_text(json.dumps(data, indent=2))
    old_json.unlink()
    return {"video_id": new_id}


@app.get("/api/reports/{video_id}/media")
def get_report_media(video_id: str) -> FileResponse:
    src = _source_media(video_id)
    if src is None:
        raise HTTPException(
            status_code=404, detail=f"No source media for {video_id!r}"
        )
    # FileResponse handles Range requests, so <video> seeking works.
    return FileResponse(src)


@app.get("/api/reports/{video_id}/markdown", response_class=PlainTextResponse)
def get_report_markdown(video_id: str) -> str:
    path = jobs.OUT_ROOT / f"{video_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No markdown for {video_id!r}")
    return path.read_text()


# --------------------------------------------------------------------------- #
# Jobs                                                                         #
# --------------------------------------------------------------------------- #
@app.get("/api/jobs", response_model=list[JobStatus])
def list_active_jobs() -> list[JobStatus]:
    """In-flight reviews — everything not yet finished (a done job becomes a
    report, an errored one is surfaced on its progress page)."""
    return [
        JobStatus(**state)
        for state in jobs.list_jobs()
        if state.get("stage") not in ("done", "error")
    ]


@app.post("/api/jobs", response_model=JobAccepted, status_code=202)
async def create_job(
    file: UploadFile = File(...),
    kind: str = Form("video"),
    stub: bool = Form(False),
    fast: bool = Form(False),
    overwrite: bool = Form(False),
) -> JobAccepted:
    if kind not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown kind {kind!r}. Expected one of: video, image, audio.",
        )
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS[kind]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {kind} file type {ext!r}. Allowed: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS[kind])),
        )

    video_id = Path(filename).stem
    if not overwrite and jobs.report_exists(video_id):
        # Existing report — let the UI decide (view vs. re-run with overwrite).
        existing = json.loads(jobs.report_path(video_id).read_text())
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"A report for {video_id!r} already exists.",
                "video_id": video_id,
                "existing_report": existing,
            },
        )

    # Stream the upload to disk under a unique dir (never clobbers on disk).
    upload_dir = jobs.UPLOAD_ROOT / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / filename
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File exceeds 500 MB limit.")
            out.write(chunk)

    options = {
        "kind": kind,
        "stub": stub,
        "fast": fast,
    }
    job_id, video_id = jobs.submit_job(dest, options)
    return JobAccepted(job_id=job_id, video_id=video_id)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str) -> JobStatus:
    state = jobs.get_job(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}")
    return JobStatus(**state)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    if jobs.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id!r}")

    async def event_stream():
        last_stage = None
        while True:
            state = jobs.get_job(job_id)
            if state is None:
                break
            stage = state.get("stage")
            if stage != last_stage:
                last_stage = stage
                yield {"event": "stage", "data": json.dumps(state)}
            if stage in ("done", "error"):
                break
            await asyncio.sleep(1.0)

    return EventSourceResponse(event_stream())
