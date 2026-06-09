"""Prompt construction for claim-reasoning checks.

The reasoning core gets: the check definition, plus the relevant corpus/corpora
(visual text-over-time and/or the transcript), each segment/appearance tagged
with its timestamp and a low-confidence flag. The model is required to call the
structured tool and to return ``uncertain`` when evidence is ambiguous or when
it had to lean on a low-confidence segment.
"""

from __future__ import annotations

from ..schemas import Check, Transcript, VisualCorpus

CLAIM_SYSTEM = (
    "You are a SEBI/AMFI mutual-fund advertising compliance reviewer. You assess "
    "ONE check at a time against evidence extracted from a marketing video.\n\n"
    "Posture — the system is advisory and FAIL-SAFE:\n"
    "  * Return 'fail' ONLY on clear evidence of a violation.\n"
    "  * Return 'pass' ONLY when there is positive evidence of compliance AND no "
    "low-confidence input fed your decision.\n"
    "  * Otherwise return 'uncertain'. When in doubt, choose 'uncertain', never 'pass'.\n"
    "  * Low ASR/OCR confidence on the evidence you relied on is itself a reason "
    "to return 'uncertain' — set low_confidence_inputs=true. Inability to "
    "hear/read a region is NOT evidence of compliance.\n\n"
    "For 'both'-surface checks, a violation appearing on EITHER the on-screen "
    "text OR the spoken audio is a violation — cite which surface and the "
    "timestamp/frame. Always ground every evidence quote in the supplied "
    "evidence; do not invent quotes. The regulatory specifics in the check "
    "(exact wording, durations) are placeholders to be confirmed — reason "
    "against what is given.\n\n"
    "Write for a busy human reviewer who needs to grasp the verdict in seconds:\n"
    "  * summary — ONE plain-language sentence with the verdict and the single "
    "decisive reason (no metric dumps).\n"
    "  * findings — 3-6 short bullets, the decisive one FIRST; put concrete "
    "numbers here. Each bullet is one self-contained point.\n"
    "  * reasoning — the full prose, for the audit trail.\n\n"
    "Always reply by calling the report_check_result tool."
)


def _fmt_timestamp(start: float, end: float | None = None) -> str:
    def mmss(t: float) -> str:
        m, s = divmod(int(t), 60)
        return f"{m:02d}:{s:02d}"

    return f"{mmss(start)}-{mmss(end)}" if end is not None else mmss(start)


def render_visual_evidence(corpus: VisualCorpus, max_items: int = 60) -> str:
    if not corpus.appearances:
        return "ON-SCREEN TEXT: (none detected)"
    # A still image has no on-screen duration — don't present a fabricated one.
    if corpus.static_image:
        lines = [
            "ON-SCREEN TEXT — SINGLE STILL IMAGE (no duration; "
            "text | min height ratio | min contrast | min OCR conf | low-conf):"
        ]
        for a in corpus.appearances[:max_items]:
            contrast = f"{a.min_contrast:.1f}" if a.min_contrast is not None else "n/a"
            lines.append(
                f'  - "{a.text}" | h={a.min_height_ratio:.4f} | '
                f"contrast={contrast} | ocr={a.min_ocr_confidence:.2f} | "
                f"low_conf={a.low_confidence}"
            )
        return "\n".join(lines)

    lines = ["ON-SCREEN TEXT (text | on-screen seconds | min height ratio | min contrast | min OCR conf | low-conf):"]
    for a in corpus.appearances[:max_items]:
        contrast = f"{a.min_contrast:.1f}" if a.min_contrast is not None else "n/a"
        ts = ", ".join(_fmt_timestamp(t) for t in a.timestamps[:6])
        lines.append(
            f'  - "{a.text}" | {a.on_screen_seconds:.1f}s | '
            f"h={a.min_height_ratio:.4f} | contrast={contrast} | "
            f"ocr={a.min_ocr_confidence:.2f} | low_conf={a.low_confidence} | at [{ts}]"
        )
    return "\n".join(lines)


def render_audio_evidence(transcript: Transcript, max_items: int = 200) -> str:
    if not transcript.segments:
        return "SPOKEN AUDIO TRANSCRIPT: (no speech detected)"
    lines = [f"SPOKEN AUDIO TRANSCRIPT (language={transcript.language}):"]
    for s in transcript.segments[:max_items]:
        flag = " [LOW-CONFIDENCE]" if s.low_confidence else ""
        lines.append(
            f'  - [{_fmt_timestamp(s.start, s.end)}]{flag} '
            f"(logprob={s.avg_logprob:.2f}, no_speech={s.no_speech_prob:.2f}) "
            f'"{s.text}"'
        )
    return "\n".join(lines)


def render_check(check: Check) -> str:
    parts = [
        "CHECK TO EVALUATE:",
        f"  id: {check.id}",
        f"  description: {check.description}",
        f"  surface: {check.surface.value}",
        f"  severity: {check.severity.value}",
        f"  applies_when: {check.applies_when}",
        f"  pass_criteria: {check.pass_criteria}",
        f"  policy_ref: {check.policy_ref}",
    ]
    if check.required_text:
        parts.append(f'  required_text (PLACEHOLDER): "{check.required_text}"')
    if check.min_on_screen_seconds is not None:
        parts.append(f"  min_on_screen_seconds (PLACEHOLDER): {check.min_on_screen_seconds}")
    if check.notes:
        parts.append(f"  notes: {check.notes}")
    return "\n".join(parts)


def build_claim_prompt(
    check: Check,
    corpus: VisualCorpus | None,
    transcript: Transcript | None,
) -> str:
    """Assemble the user message for a text-claim check.

    Only the surfaces the check is tagged for are included; for 'both' checks,
    both surfaces are supplied so the OR-across-surfaces logic can apply.
    """
    blocks = []
    if corpus is not None and corpus.static_image:
        blocks.append(
            "INPUT IS A SINGLE STILL IMAGE. There is NO on-screen duration / dwell "
            "time. Do NOT evaluate or fail any check on duration or "
            "time-on-screen grounds (e.g. min_on_screen_seconds does not apply). "
            "Judge only what a still can show: presence, wording, and legibility "
            "(text size / contrast). If a check's criteria are purely about "
            "duration, treat that part as not applicable and base the verdict on "
            "the legibility/presence it CAN assess (or 'uncertain' if it can't).\n"
        )
    blocks += [render_check(check), ""]
    surface = check.surface.value

    if surface in ("visual", "both"):
        blocks.append(render_visual_evidence(corpus) if corpus else "ON-SCREEN TEXT: (visual pipeline not run)")
        blocks.append("")
    if surface in ("audio", "both"):
        blocks.append(render_audio_evidence(transcript) if transcript else "SPOKEN AUDIO TRANSCRIPT: (audio pipeline not run)")
        blocks.append("")

    blocks.append(
        "Evaluate the check against the evidence above and call "
        "report_check_result. Provide a one-line summary, decisive-first findings "
        "bullets, and full reasoning. Set surfaces you actually consulted via the "
        "evidence you cite. Remember the fail-safe posture."
    )
    return "\n".join(blocks)
