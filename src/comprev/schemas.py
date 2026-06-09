"""Pydantic data contracts for the MF compliance engine.

These schemas are the source of truth for quality: the check library, the
intermediate artifacts (OCR, transcript, corpus), and the final per-video
report all flow through here. Get them exactly right.

Posture: the engine is advisory and *fail-safe*. A check is ``pass`` ONLY with
positive evidence of compliance AND no low-confidence input. Otherwise the
verdict trends to ``uncertain`` — never silently ``pass``.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enumerations                                                                 #
# --------------------------------------------------------------------------- #
class Surface(str, Enum):
    """Where a check looks for evidence."""

    visual = "visual"
    audio = "audio"
    both = "both"


class Severity(str, Enum):
    """A ``serious`` miss is a regulatory event; ``normal`` is lower stakes."""

    serious = "serious"
    normal = "normal"


class CheckStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    uncertain = "uncertain"


class OverallStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    needs_review = "needs_review"


# --------------------------------------------------------------------------- #
# Check library (mirrors config/checks_mf.yaml)                                #
# --------------------------------------------------------------------------- #
class Check(BaseModel):
    """One compliance check, loaded from YAML and editable by non-engineers.

    Every regulatory specific (exact wording, durations, VO pace) lives here as
    a config field — never hardcoded in Python — and is to be confirmed by
    compliance against the cited ``policy_ref``.
    """

    id: str
    description: str
    surface: Surface
    severity: Severity
    applies_when: str = "always"  # "always" | "performance_shown" | other named condition
    # How the check is evaluated: "text" reads the OCR/transcript corpora and
    # reasons via Claude; "vision" sends frames to the Claude vision API for a
    # perception judgment (e.g. "is a Riskometer graphic present").
    method: Literal["text", "vision"] = "text"
    required_text: Optional[str] = None
    min_on_screen_seconds: Optional[float] = None
    policy_ref: str
    pass_criteria: str

    # Free-form extra hints the prompt may use (e.g. banned phrases). Kept open
    # so compliance can add nuance in YAML without a code change.
    notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# Visual artifacts                                                             #
# --------------------------------------------------------------------------- #
class BoundingBox(BaseModel):
    """Pixel coordinates of a detected text region (top-left origin)."""

    x: float
    y: float
    width: float
    height: float


class OcrDetection(BaseModel):
    """One OCR text detection on one frame, with audit detail."""

    text: str
    confidence: float
    box: BoundingBox
    # Legibility proxies, computed against the frame the detection came from.
    height_ratio: float = Field(..., description="box height / frame height")
    contrast: Optional[float] = Field(
        None, description="luminance contrast of text box vs surrounding background, if computed"
    )


class FrameOcr(BaseModel):
    """All detections for a single sampled frame."""

    frame_index: int
    timestamp_seconds: float
    is_scene_cut: bool = False
    frame_width: int
    frame_height: int
    detections: list[OcrDetection] = Field(default_factory=list)


class TextAppearance(BaseModel):
    """A distinct on-screen string and where/when it appeared.

    ``on_screen_seconds`` lets checks reason about disclaimer dwell time;
    ``min_height_ratio`` / ``min_contrast`` capture worst-case legibility.
    """

    text: str
    frame_indices: list[int]
    timestamps: list[float]
    on_screen_seconds: float
    min_height_ratio: float
    max_height_ratio: float
    min_contrast: Optional[float] = None
    min_ocr_confidence: float
    low_confidence: bool = False


class VisualCorpus(BaseModel):
    """Deduped text-presence-over-time plus the raw per-frame detections."""

    sample_interval_seconds: float
    frames: list[FrameOcr] = Field(default_factory=list)
    appearances: list[TextAppearance] = Field(default_factory=list)
    # Sampled frame paths available for the vision API / human audit.
    frame_paths: dict[int, str] = Field(
        default_factory=dict, description="frame_index -> on-disk path"
    )
    # True for a single still image: there is NO on-screen duration, so
    # on_screen_seconds is not a real dwell time and duration checks don't apply.
    static_image: bool = False


# --------------------------------------------------------------------------- #
# Audio artifacts                                                              #
# --------------------------------------------------------------------------- #
class TranscriptSegment(BaseModel):
    """One ASR segment with timestamps and a confidence proxy.

    ``avg_logprob`` is the confidence proxy; ``no_speech_prob`` is surfaced so a
    reviewer can spot silence/music misfires. ``low_confidence`` is set when the
    segment falls below the configured threshold — and any check relying on a
    low-confidence segment must NOT return ``pass``.
    """

    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    low_confidence: bool = False


class Transcript(BaseModel):
    language: Optional[str] = None
    segments: list[TranscriptSegment] = Field(default_factory=list)
    audio_path: str = Field(..., description="original demuxed audio kept for human spot-check")
    model: str = ""


# --------------------------------------------------------------------------- #
# Verdict contracts                                                            #
# --------------------------------------------------------------------------- #
class Evidence(BaseModel):
    """The minimum a human needs to overturn a verdict."""

    surface: Literal["visual", "audio"]
    timestamp: Optional[str] = Field(None, description='e.g. "00:12-00:14" or "00:30"')
    frame_index: Optional[int] = None
    quote: str
    ocr_confidence: Optional[float] = None
    asr_confidence: Optional[float] = None


class CheckResult(BaseModel):
    check_id: str
    status: CheckStatus
    severity: Severity
    confidence: float = Field(..., ge=0.0, le=1.0)
    surfaces_evaluated: list[Literal["visual", "audio"]]
    # One-line, plain-language verdict (the headline shown to a reviewer).
    summary: str = ""
    # A few short, discrete observations behind the verdict (decisive one first).
    findings: list[str] = Field(default_factory=list)
    # Full prose reasoning — kept for the audit trail (JSON + markdown).
    reasoning: str
    evidence: list[Evidence] = Field(default_factory=list)
    policy_ref: str
    low_confidence_inputs: bool = False
    # True when a check did not apply (applies_when not met) — reported, not scored.
    not_applicable: bool = False


class VideoReport(BaseModel):
    video_id: str
    product: Literal["mutual_funds"] = "mutual_funds"
    duration_seconds: float = 0.0
    overall_status: OverallStatus
    checks: list[CheckResult] = Field(default_factory=list)
    needs_human_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)

    def model_dump_report(self) -> dict:
        """JSON dump matching the brief's output contract (enum values as strings)."""
        return self.model_dump(mode="json")
