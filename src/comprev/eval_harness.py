"""Eval harness — the other half of the deliverable.

Phase 1 exists to measure whether the engine is accurate enough to trust, so we
quantify two things over a labeled folder:

  ACCURACY (headline):
    * recall on SERIOUS violations  = catch rate on real breaches
    * count of SERIOUS false negatives (a serious breach predicted 'pass') — must trend to ~0
    * false-positive rate
  EFFICIENCY:
    * 'uncertain' rate, split into:
        - correctly escalated (truth = fail)  -> safe
        - lost efficiency    (truth = pass)   -> a human looked for nothing

A predicted 'uncertain' on a truth-'fail' is treated as correctly escalated (safe),
NOT as a catch — only a predicted 'fail' counts toward recall.

Labels: ``labels.jsonl`` — one JSON object per line:
  {"video_id": "...",
   "expected_checks": {"check_id": "pass|fail", ...},
   "breaches_present": ["check_id", ...]}
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import DEFAULT_CHECKS_PATH, DEFAULT_ENGINE_PATH, load_checks, load_engine_config
from .engine import run_video

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@dataclass
class Pair:
    video_id: str
    check_id: str
    severity: str
    expected: str   # pass | fail
    predicted: str  # pass | fail | uncertain | not_applicable | missing


@dataclass
class Metrics:
    pairs: list[Pair] = field(default_factory=list)

    def _filter(self, **kw):
        out = self.pairs
        for k, v in kw.items():
            out = [p for p in out if getattr(p, k) == v]
        return out

    # ----- headline accuracy ------------------------------------------------ #
    def serious_recall(self) -> tuple[int, int]:
        relevant = [p for p in self.pairs if p.severity == "serious" and p.expected == "fail"]
        caught = [p for p in relevant if p.predicted == "fail"]
        return len(caught), len(relevant)

    def serious_false_negatives(self) -> list[Pair]:
        return [
            p for p in self.pairs
            if p.severity == "serious" and p.expected == "fail" and p.predicted == "pass"
        ]

    def all_false_negatives(self) -> list[Pair]:
        return [p for p in self.pairs if p.expected == "fail" and p.predicted == "pass"]

    def false_positives(self) -> list[Pair]:
        return [p for p in self.pairs if p.expected == "pass" and p.predicted == "fail"]

    def expected_pass_total(self) -> int:
        return len([p for p in self.pairs if p.expected == "pass"])

    # ----- efficiency ------------------------------------------------------- #
    def uncertain(self) -> list[Pair]:
        return [p for p in self.pairs if p.predicted == "uncertain"]

    def uncertain_escalated(self) -> list[Pair]:
        return [p for p in self.uncertain() if p.expected == "fail"]

    def uncertain_lost(self) -> list[Pair]:
        return [p for p in self.uncertain() if p.expected == "pass"]

    def scored_total(self) -> int:
        return len([p for p in self.pairs if p.predicted in ("pass", "fail", "uncertain")])


def _load_labels(labels_path: Path) -> list[dict]:
    rows = []
    for line in labels_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _find_video(folder: Path, video_id: str) -> Optional[Path]:
    for ext in _VIDEO_EXTS:
        cand = folder / f"{video_id}{ext}"
        if cand.exists():
            return cand
    # Fallback: any file whose stem matches.
    for p in folder.iterdir():
        if p.stem == video_id and p.suffix.lower() in _VIDEO_EXTS:
            return p
    return None


def run_eval(
    folder: Path,
    labels_path: Optional[Path] = None,
    out_root: Path = Path("out"),
    report_path: Path = Path("eval/report.md"),
    checks_path: Path = DEFAULT_CHECKS_PATH,
    engine_path: Path = DEFAULT_ENGINE_PATH,
    stub: bool = False,
) -> str:
    folder = Path(folder)
    labels_path = labels_path or (folder / "labels.jsonl")
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_path}")

    checks = load_checks(checks_path)
    cfg = load_engine_config(engine_path)
    severity_by_id = {c.id: c.severity.value for c in checks}

    rows = _load_labels(labels_path)
    metrics = Metrics()
    skipped: list[str] = []

    for row in rows:
        video_id = row["video_id"]
        video = _find_video(folder, video_id)
        if video is None:
            skipped.append(video_id)
            continue

        report = run_video(video, checks, cfg, out_root=out_root, stub=stub)
        pred_by_id = {
            c.check_id: ("not_applicable" if c.not_applicable else c.status.value)
            for c in report.checks
        }

        for check_id, expected in row.get("expected_checks", {}).items():
            predicted = pred_by_id.get(check_id, "missing")
            if predicted in ("not_applicable", "missing"):
                # Not scored, but recorded for the report footer.
                continue
            metrics.pairs.append(
                Pair(
                    video_id=video_id,
                    check_id=check_id,
                    severity=severity_by_id.get(check_id, "normal"),
                    expected=expected,
                    predicted=predicted,
                )
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    md = _render_eval_report(metrics, n_videos=len(rows), skipped=skipped, stub=stub)
    report_path.write_text(md)
    return _render_summary(metrics, skipped)


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #
def _pct(num: int, den: int) -> str:
    return f"{(100.0 * num / den):.1f}%" if den else "n/a"


def _render_summary(m: Metrics, skipped: list[str]) -> str:
    caught, total = m.serious_recall()
    fns = m.serious_false_negatives()
    lines = [
        "Eval summary:",
        f"  Serious-violation recall (catch rate): {caught}/{total} ({_pct(caught, total)})",
        f"  Serious FALSE NEGATIVES (must -> 0):    {len(fns)}",
        f"  False positives:                        {len(m.false_positives())}/{m.expected_pass_total()} ({_pct(len(m.false_positives()), m.expected_pass_total())})",
        f"  Uncertain rate:                         {len(m.uncertain())}/{m.scored_total()} ({_pct(len(m.uncertain()), m.scored_total())})",
    ]
    if skipped:
        lines.append(f"  Skipped (no video found): {', '.join(skipped)}")
    return "\n".join(lines)


def _render_eval_report(m: Metrics, n_videos: int, skipped: list[str], stub: bool) -> str:
    caught, total = m.serious_recall()
    fns = m.serious_false_negatives()
    fps = m.false_positives()
    L: list[str] = ["# Eval report — MF Video Compliance Engine (Phase 1)", ""]
    if stub:
        L += ["> ⚠️ Generated in **--stub** mode (pipelines/API not run). Numbers are not meaningful.", ""]

    L += [
        "## Headline",
        "",
        f"- **Videos labeled:** {n_videos}  ·  **scored (check,video) pairs:** {m.scored_total()}",
        f"- **Serious-violation recall (catch rate):** {caught}/{total} = **{_pct(caught, total)}**",
        f"- **Serious false negatives (drive to ~0):** **{len(fns)}**",
        f"- **All false negatives:** {len(m.all_false_negatives())}",
        f"- **False-positive rate:** {len(fps)}/{m.expected_pass_total()} = {_pct(len(fps), m.expected_pass_total())}",
        f"- **Uncertain rate:** {len(m.uncertain())}/{m.scored_total()} = {_pct(len(m.uncertain()), m.scored_total())}",
        f"    - correctly escalated (truth=fail): {len(m.uncertain_escalated())}",
        f"    - lost efficiency (truth=pass): {len(m.uncertain_lost())}",
        "",
    ]

    # Overall confusion matrix.
    L += ["## Confusion matrix (overall)", "", "| expected \\ predicted | pass | fail | uncertain |", "|---|---|---|---|"]
    for exp in ("pass", "fail"):
        cells = [len([p for p in m.pairs if p.expected == exp and p.predicted == pred]) for pred in ("pass", "fail", "uncertain")]
        L.append(f"| **{exp}** | {cells[0]} | {cells[1]} | {cells[2]} |")
    L.append("")

    # Per-check breakdown.
    L += ["## Per-check breakdown", "", "| check | severity | recall (fail caught) | false neg | false pos | uncertain |", "|---|---|---|---|---|---|"]
    by_check: dict[str, list[Pair]] = defaultdict(list)
    for p in m.pairs:
        by_check[p.check_id].append(p)
    for check_id in sorted(by_check):
        ps = by_check[check_id]
        sev = ps[0].severity
        fail_exp = [p for p in ps if p.expected == "fail"]
        caught_c = len([p for p in fail_exp if p.predicted == "fail"])
        fn_c = len([p for p in fail_exp if p.predicted == "pass"])
        fp_c = len([p for p in ps if p.expected == "pass" and p.predicted == "fail"])
        unc_c = len([p for p in ps if p.predicted == "uncertain"])
        L.append(
            f"| `{check_id}` | {sev} | {caught_c}/{len(fail_exp)} ({_pct(caught_c, len(fail_exp))}) "
            f"| {fn_c} | {fp_c} | {unc_c} |"
        )
    L.append("")

    # Serious FN detail — the dangerous misses.
    if fns:
        L += ["## ⚠️ Serious false negatives (real breaches passed)", ""]
        for p in fns:
            L.append(f"- `{p.video_id}` / `{p.check_id}` — predicted **pass**, truth **fail**")
        L.append("")

    if skipped:
        L += ["## Skipped (no matching video file found)", "", ", ".join(f"`{s}`" for s in skipped), ""]

    return "\n".join(L)
