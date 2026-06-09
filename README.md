# comprev — MF Video Compliance Engine (Phase 1)

A standalone, runnable CLI that reviews a **single mutual-fund marketing video**
against a configurable compliance check library and returns a **per-check
verdict** — `pass` / `fail` / `uncertain` — each with reasoning, evidence
(timestamp / frame), and the policy clause it maps to. Ships with an **eval
harness** that measures the two numbers this phase exists to produce: the
**catch rate on real breaches** and the **`uncertain` rate** (review efficiency).

> **Posture: advisory and fail-safe.** A false negative (passing a real breach)
> is a regulatory event; a false positive is a minor annoyance. So when the
> engine is not confident — including when ASR/OCR confidence on a segment is
> low — the verdict is **`uncertain`, never `pass`**. Inability to hear/read a
> region is *not* evidence of compliance.

This is **Phase 1**. There is intentionally no workflow, Slack, database, web UI,
policy-PDF parser, or any product other than mutual funds. Those are out of scope.

---

## What it does

```
video ──┬─► VISUAL pipeline ─┐
        │                    ├─► FUSION (per-check) ─► ROUTING ─► REPORT (json + md)
        └─► AUDIO pipeline ──┘
```

- **Visual** — sample frames (ffmpeg, 1 frame / 2 s + scene cuts via PySceneDetect)
  → OCR with bounding boxes + confidence (PaddleOCR, Latin + Devanagari) →
  a *text-presence-over-time* corpus (per string: when it appeared, how long it
  was on screen, legibility) → Claude vision for perception checks (e.g. "is a
  Riskometer present").
- **Audio** — transcribe with faster-whisper (Hindi/Hinglish), producing
  segment text + timestamps + a confidence proxy (`avg_logprob`, `no_speech_prob`).
  Low-confidence segments are flagged; the original audio is kept for spot-checks.
- **Fusion** — for each check, evaluate against the surface(s) it is tagged for.
  `both`-surface checks read the on-screen text **AND** the transcript and flag a
  violation if it appears in **either** (OR-across-surfaces), citing the surface
  and timestamp/frame. Reasoning runs through the Claude API with a **strict
  structured JSON** response.
- **Routing** — fail-safe rules turn raw results into the final verdict.

Every intermediate artifact (sampled frames, `ocr.json`, `corpus.json`,
`transcript.json`) is written under `out/<video_id>/` so any verdict is auditable.

---

## Install

Requires **Python 3.11+** and **ffmpeg**.

```bash
# macOS
brew install python@3.11 ffmpeg

# from the repo root
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip

# core engine (CLI, schemas, reasoning):
pip install -e .

# heavy ML pipelines (OCR + ASR). On Apple Silicon these can be slow / finicky
# to install — they are optional extras so the CLI works without them:
pip install -e ".[visual]"   # PaddleOCR + PySceneDetect + OpenCV
pip install -e ".[audio]"    # faster-whisper
```

> **No system ffmpeg?** The extras bundle `imageio-ffmpeg`, a static ffmpeg
> binary the engine falls back to automatically — handy on machines where you
> can't write to a shared Homebrew. (Duration probing then falls back to OpenCV,
> since the bundled package ships ffmpeg but not ffprobe.)

### API key (environment only)

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # never commit this; see .env.example
```

The engine reads the key from the environment **only** — never from a config
file or the command line.

---

## Run on one video

```bash
# Full review (needs ffmpeg, the [visual]+[audio] extras, and ANTHROPIC_API_KEY):
comprev run path/to/video.mp4 --product mutual_funds

# Outputs:
#   out/<video_id>.json   — machine-readable verdict (see contract below)
#   out/<video_id>.md     — human-readable summary
#   out/<video_id>/       — sampled frames, ocr.json, corpus.json, transcript.json, audio.wav
```

Useful flags while bringing things up incrementally:

```bash
comprev run video.mp4 --stub          # no ML deps / no API; everything 'uncertain' (scaffold check)
comprev run video.mp4 --skip-audio    # visual pipeline only
comprev run video.mp4 --skip-visual   # audio pipeline only
comprev checks                        # list the loaded check library
```

---

## Run the eval

Put labeled videos in a folder with a `labels.jsonl` (see `eval/labels.jsonl`
for the format), then:

```bash
comprev eval path/to/eval_folder
# writes eval/report.md with:
#   - serious-violation recall (the headline catch rate)
#   - serious false-negative count (must trend to ~0)
#   - false-positive rate
#   - uncertain rate (split: correctly escalated vs lost efficiency)
```

---

## Configuration

- **`config/checks_mf.yaml`** — the check library, editable by non-engineers.
  Every regulatory specific (exact disclaimer wording, on-screen durations, VO
  pace) is a field marked `# PLACEHOLDER` with a `policy_ref` to be **confirmed
  by compliance**. None are hardcoded in Python, and none are authoritative yet.
- **`config/engine.yaml`** — runtime knobs: Claude model, frame sample interval,
  scene-detection threshold, OCR languages, and the ASR/OCR confidence
  thresholds that drive low-confidence flagging.

### Seeded checks (Phase 1)

| id | surface | severity | applies_when |
|---|---|---|---|
| `mf_standard_warning_present` | visual | serious | always |
| `mf_standard_warning_voiced` | audio | serious | always |
| `mf_warning_duration_and_legibility` | visual | serious | always |
| `mf_risk_o_meter_present` | visual | serious | always |
| `mf_no_guaranteed_or_assured_returns` | both | serious | always |
| `mf_no_specific_return_promise_without_basis` | both | serious | always |
| `mf_past_performance_format_and_caveat` | both | normal | performance_shown |
| `mf_superlatives_have_source_and_date` | both | normal | always |
| `mf_scheme_and_amc_disclosed` | visual | normal | always |

---

## Output contract (`out/<video_id>.json`)

```json
{
  "video_id": "string",
  "product": "mutual_funds",
  "duration_seconds": 0,
  "overall_status": "pass | fail | needs_review",
  "checks": [
    {
      "check_id": "mf_no_guaranteed_or_assured_returns",
      "status": "pass | fail | uncertain",
      "severity": "serious | normal",
      "confidence": 0.0,
      "surfaces_evaluated": ["visual", "audio"],
      "reasoning": "Why this verdict.",
      "evidence": [{"surface": "audio", "timestamp": "00:12-00:14", "quote": "guaranteed 9% returns"}],
      "policy_ref": "string",
      "low_confidence_inputs": false
    }
  ],
  "needs_human_review": true,
  "review_reasons": ["mf_no_guaranteed_or_assured_returns failed", "2 checks uncertain"]
}
```

### Routing rules
- `fail` only on clear evidence of a violation.
- `pass` only with positive evidence of compliance **and** no low-confidence input.
- otherwise → `uncertain`.
- `overall_status`: `fail` if any check failed; else `needs_review` if any
  uncertain; else `pass`. `needs_human_review` is true whenever overall ≠ `pass`.

---

## Architecture / where things live

| Path | Responsibility |
|---|---|
| `src/comprev/schemas.py` | Pydantic contracts (Check, CheckResult, Evidence, VideoReport, corpora) |
| `src/comprev/config.py` | Load + validate `checks_mf.yaml` / `engine.yaml`; env API key |
| `src/comprev/visual/` | `sampling`, `ocr` (interface + PaddleOCR), `corpus`, `vision` |
| `src/comprev/audio/asr.py` | ASR interface + faster-whisper; low-confidence flagging |
| `src/comprev/fusion/` | `prompts` + `evaluate` (claim reasoning, OR-across-surfaces) |
| `src/comprev/routing.py` | Fail-safe routing to the final verdict |
| `src/comprev/report.py` | JSON + markdown report writers |
| `src/comprev/engine.py` | End-to-end orchestration + artifact dumping |
| `src/comprev/eval_harness.py` | Accuracy / efficiency metrics over a labeled folder |

OCR, ASR, and vision sit behind interfaces so backends can be swapped without
touching fusion or routing.

## Tests

```bash
pip install -e ".[dev]"
pytest -q        # routing rules + fusion wiring (Claude client mocked, no API key needed)
```

## Troubleshooting

- **`No models are available for the language 'devanagari'`** — PaddleOCR 3.x
  uses `hi` for the Devanagari script; `config/engine.yaml` already defaults to
  `["en", "hi"]`. An unavailable language is skipped with a warning rather than
  crashing the run.
- **`Class AVF... is implemented in both ...cv2... and ...av...` on stderr** —
  a harmless dylib-name clash because OpenCV and PyAV (used by faster-whisper)
  each bundle libav. It has not caused failures here; it's noise.
- **Apple Silicon** — `paddlepaddle`/`paddleocr` 3.x install and run on arm64
  (verified), but first run downloads OCR models to `~/.paddlex`. Whisper
  `large-v3` is large/slow on CPU; drop `audio.model` in `engine.yaml` to
  `medium`/`small` for faster iteration.

## Phase-2 boundaries
No Slack, DB, web UI, PDF policy parsing, or non-MF products in this phase.
Extension points are marked with `# PHASE 2:` comments in the code.
