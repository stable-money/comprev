"""API response models for the web backend.

The full report contract already lives in ``comprev.schemas.VideoReport`` and is
served verbatim; these are only the thin envelopes the UI needs for listing and
job tracking.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ReportSummary(BaseModel):
    """One row in the reports list (derived from a stored ``out/<id>.json``)."""

    video_id: str
    overall_status: str
    needs_human_review: bool
    duration_seconds: float
    n_checks: int
    modified_at: float  # epoch seconds, for sorting newest-first
    media_kind: Optional[Literal["video", "image", "audio"]] = None
    product: Optional[str] = None  # "mutual_funds" | "bonds" (None on older reports)


class JobAccepted(BaseModel):
    """Returned by ``POST /api/jobs`` once an upload is queued."""

    job_id: str
    video_id: str


class JobStatus(BaseModel):
    job_id: str
    video_id: str
    kind: Literal["video", "image", "audio"] = "video"
    product: Optional[str] = None
    stage: Literal[
        "queued", "sampling", "transcribing", "evaluating", "routing", "done", "error"
    ]
    report_ready: bool = False
    error: Optional[str] = None


class Health(BaseModel):
    ok: bool = True
    anthropic_key_present: bool
    ml_extras_present: bool
