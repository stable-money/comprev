"""Configuration loading and validation.

Two config files:
  * ``config/checks_mf.yaml``  — the editable compliance check library.
  * ``config/engine.yaml``     — runtime knobs (model, sampling, thresholds).

Both are validated into typed objects on load so a malformed YAML fails loudly
at startup rather than midway through a video.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from .schemas import Check

# Repo-root-relative default config locations.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKS_PATH = _REPO_ROOT / "config" / "checks_mf.yaml"
DEFAULT_ENGINE_PATH = _REPO_ROOT / "config" / "engine.yaml"


# --------------------------------------------------------------------------- #
# Engine config schema                                                         #
# --------------------------------------------------------------------------- #
class VisualConfig(BaseModel):
    backend: str = "paddleocr"
    sample_interval_seconds: float = 2.0
    scene_detect: bool = True
    scene_threshold: float = 27.0
    ocr_languages: list[str] = Field(default_factory=lambda: ["en", "hi"])
    ocr_low_confidence: float = 0.6
    # Optional speed knobs. Default (None) uses PaddleOCR's accurate "server"
    # detector at full resolution. Set a mobile detector and/or a max frame
    # width to trade some accuracy for a large speed-up (see CLI --fast).
    ocr_detection_model: Optional[str] = None
    # Cap the frame width fed to OCR. Aspect-preserving downscale only kicks in
    # above this width, so typical <=1440p frames are untouched (quality-neutral)
    # while multi-megapixel stills are bounded. None restores full resolution.
    ocr_max_width: Optional[int] = 2560
    min_legible_height_ratio: float = 0.015
    min_legible_contrast: float = 3.0
    # Latency knobs (quality-neutral). OCR frames are read concurrently across a
    # pool of `ocr_max_workers` engines; each engine's native thread count is
    # capped to `ocr_cpu_threads` so concurrent OCR + ASR don't oversubscribe the
    # CPU. Frame extraction subprocesses run `frame_extract_workers` at a time.
    ocr_max_workers: int = 2
    ocr_cpu_threads: int = 3
    frame_extract_workers: int = 4


class AudioConfig(BaseModel):
    backend: str = "faster_whisper"
    model: str = "large-v3"
    compute_type: str = "int8"
    language: Optional[str] = None
    low_confidence_logprob: float = -1.0
    max_no_speech_prob: float = 0.6
    # Native CPU threads for transcription. Budgeted with the visual knobs so
    # overlapping OCR + ASR keep `ocr_max_workers*ocr_cpu_threads + cpu_threads`
    # near the core count.
    cpu_threads: int = 4


class FusionConfig(BaseModel):
    # Max Claude check-evaluations to run concurrently (calls are independent and
    # network-bound). Defaults to the check-library size.
    max_parallel_checks: int = 9


class PolicyConfig(BaseModel):
    """Identifies the active policy a review is judged under (stamped on reports)."""

    name: str = "Mutual Funds"
    version: str = "unspecified"
    effective_date: Optional[str] = None
    # Source policy document, relative to the repo root (for audit / download).
    source_file: Optional[str] = None


class ProductConfig(BaseModel):
    """One reviewable product line: its check library + the policy it operationalizes."""

    label: str
    checks_file: str
    policy: PolicyConfig = Field(default_factory=PolicyConfig)


class EngineConfig(BaseModel):
    model: str = "claude-opus-4-8"
    max_tokens: int = 2048
    visual: VisualConfig = Field(default_factory=VisualConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    # Legacy single-product policy (the mutual_funds default). New products live
    # under ``products`` below; this stays as the fallback for mutual_funds.
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    # Product registry: product key -> its checks file + policy. Shared ML/runtime
    # knobs above are product-agnostic; only checks + policy differ per product.
    products: dict[str, ProductConfig] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Loaders                                                                      #
# --------------------------------------------------------------------------- #
def load_engine_config(path: Path | str | None = None) -> EngineConfig:
    path = Path(path) if path else DEFAULT_ENGINE_PATH
    if not path.exists():
        # Defaults are sane; missing engine.yaml is non-fatal.
        return EngineConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return EngineConfig.model_validate(data)


def resolve_product(cfg: EngineConfig, product: str) -> ProductConfig:
    """Resolve a product key to its checks file + policy.

    Prefers the ``products`` registry in engine.yaml. Falls back to the legacy
    top-level ``policy`` block for ``mutual_funds`` so an older engine.yaml (no
    ``products``) still works. Unknown products raise.
    """
    if product in cfg.products:
        return cfg.products[product]
    if product == "mutual_funds":
        return ProductConfig(
            label="Mutual Funds",
            checks_file=str(DEFAULT_CHECKS_PATH.relative_to(_REPO_ROOT)),
            policy=cfg.policy,
        )
    raise ValueError(
        f"Unknown product: {product!r}. Configure it under 'products' in engine.yaml."
    )


def checks_path_for(pc: ProductConfig) -> Path:
    """Absolute path to a product's checks file (resolved against the repo root)."""
    p = Path(pc.checks_file)
    return p if p.is_absolute() else _REPO_ROOT / p


def checks_hash(path: Path | str | None = None) -> str:
    """Short content hash of the check library — stamped on reports so a verdict
    is traceable to the exact rules that produced it."""
    import hashlib

    path = Path(path) if path else DEFAULT_CHECKS_PATH
    if not path.exists():
        return "unknown"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def load_checks(path: Path | str | None = None) -> list[Check]:
    path = Path(path) if path else DEFAULT_CHECKS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Check library not found: {path}")
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a YAML list of check entries")
    checks = [Check.model_validate(entry) for entry in data]
    _validate_unique_ids(checks)
    return checks


def _validate_unique_ids(checks: list[Check]) -> None:
    seen: set[str] = set()
    for c in checks:
        if c.id in seen:
            raise ValueError(f"Duplicate check id in check library: {c.id}")
        seen.add(c.id)


def get_api_key() -> str:
    """Fetch the Anthropic API key from the environment ONLY.

    Hard constraint: keys never come from config files or the command line.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it in your shell before running "
            "claim reasoning / vision steps. Keys come from the environment only."
        )
    return key
