"""Emit the per-video report as JSON and human-readable markdown."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import CheckStatus, VideoReport

_STATUS_EMOJI = {
    "pass": "✅",
    "fail": "❌",
    "uncertain": "❓",
    "needs_review": "🔍",
}


def write_report(report: VideoReport, out_dir: Path | str = "out") -> tuple[Path, Path]:
    """Write ``out/<video_id>.json`` and ``out/<video_id>.md``. Returns both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{report.video_id}.json"
    md_path = out_dir / f"{report.video_id}.md"

    json_path.write_text(json.dumps(report.model_dump_report(), indent=2, ensure_ascii=False))
    md_path.write_text(_render_markdown(report))

    return json_path, md_path


def _render_markdown(report: VideoReport) -> str:
    emoji = _STATUS_EMOJI.get(report.overall_status.value, "")
    lines: list[str] = [
        f"# Compliance review — `{report.video_id}`",
        "",
        f"- **Product:** {report.product}",
        f"- **Duration:** {report.duration_seconds:.1f}s",
        f"- **Overall status:** {emoji} **{report.overall_status.value.upper()}**",
        f"- **Needs human review:** {'yes' if report.needs_human_review else 'no'}",
    ]
    if report.review_reasons:
        lines.append("- **Review reasons:**")
        lines.extend(f"  - {r}" for r in report.review_reasons)
    lines += ["", "## Checks", ""]

    for c in report.checks:
        cem = _STATUS_EMOJI.get(c.status.value, "")
        na = " _(not applicable)_" if c.not_applicable else ""
        lines.append(
            f"### {cem} `{c.check_id}` — {c.status.value.upper()}{na}"
        )
        lines.append("")
        lines.append(
            f"- Severity: **{c.severity.value}** · Confidence: {c.confidence:.2f} · "
            f"Surfaces: {', '.join(c.surfaces_evaluated) or '—'} · "
            f"Low-confidence inputs: {'yes' if c.low_confidence_inputs else 'no'}"
        )
        lines.append(f"- Policy ref: {c.policy_ref}")
        if c.summary:
            lines.append(f"- **{c.summary}**")
        if c.findings:
            lines.append("- Findings:")
            lines.extend(f"  - {f}" for f in c.findings)
        lines.append(f"- Reasoning: {c.reasoning}")
        if c.evidence:
            lines.append("- Evidence:")
            for e in c.evidence:
                loc = e.timestamp or (f"frame {e.frame_index}" if e.frame_index is not None else "—")
                conf_bits = []
                if e.ocr_confidence is not None:
                    conf_bits.append(f"ocr={e.ocr_confidence:.2f}")
                if e.asr_confidence is not None:
                    conf_bits.append(f"asr={e.asr_confidence:.2f}")
                conf = f" ({', '.join(conf_bits)})" if conf_bits else ""
                lines.append(f'  - [{e.surface} @ {loc}{conf}] "{e.quote}"')
        lines.append("")

    # Quick tally footer.
    tally = {s: 0 for s in ("pass", "fail", "uncertain")}
    for c in report.checks:
        if not c.not_applicable:
            tally[c.status.value] = tally.get(c.status.value, 0) + 1
    lines.append("---")
    lines.append(
        f"_Tally: {tally.get('pass',0)} pass · {tally.get('fail',0)} fail · "
        f"{tally.get('uncertain',0)} uncertain_"
    )

    return "\n".join(lines) + "\n"
