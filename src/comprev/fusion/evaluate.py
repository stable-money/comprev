"""Per-check evaluation: fuse the surfaces and produce a CheckResult.

Two evaluation paths:
  * ``method: vision``  — perception question via the Claude vision API.
  * ``method: text``    — claim reasoning over the OCR/transcript corpora with
    OR-across-surfaces for 'both'-surface checks.

The ``applies_when`` gate decides whether a check runs at all (e.g.
``performance_shown`` only when performance content is detected).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..claude_client import ClaudeClient
from ..schemas import (
    Check,
    CheckResult,
    CheckStatus,
    Evidence,
    Severity,
    Transcript,
    VisualCorpus,
)
from ..visual.vision import ask_visual_question
from .prompts import CLAIM_SYSTEM, build_claim_prompt, _fmt_timestamp

# Lightweight detector for whether performance figures appear (gates
# performance_shown checks). Conservative: any percentage or these keywords.
_PERF_PATTERNS = [
    re.compile(r"\d+(\.\d+)?\s?%"),
    re.compile(r"\b(returns?|cagr|annualou?s?ed|p\.?a\.?|past performance|nav growth|xirr)\b", re.I),
]

# Gates `future_returns_shown` checks (illustrative/projected returns, SIP growth).
_FUTURE_RETURN_PATTERNS = [
    re.compile(r"\b(projection|projected|illustrat|assumed|expected|estimat|future)\b", re.I),
    re.compile(r"\bsip\b", re.I),
    re.compile(r"\b(grow|growth)\s+to\b", re.I),
    re.compile(r"8\.84\s?%"),
]


def _surfaces_for(check: Check) -> list[str]:
    if check.surface.value == "both":
        return ["visual", "audio"]
    return [check.surface.value]


def _available_surfaces(
    corpus: VisualCorpus | None, transcript: Transcript | None
) -> set[str]:
    """Surfaces whose pipeline actually ran for this upload.

    ``None`` means the pipeline was skipped (image => no audio, audio-only => no
    visual, or ``--skip-*``). An empty-but-present corpus/transcript still counts
    as available — the surface was inspected and simply held nothing.
    """
    available: set[str] = set()
    if corpus is not None:
        available.add("visual")
    if transcript is not None:
        available.add("audio")
    return available


def _detect_performance(corpus: VisualCorpus | None, transcript: Transcript | None) -> bool:
    blobs: list[str] = []
    if corpus:
        blobs.extend(a.text for a in corpus.appearances)
    if transcript:
        blobs.extend(s.text for s in transcript.segments)
    text = " \n ".join(blobs)
    return any(p.search(text) for p in _PERF_PATTERNS)


def _detect_future_returns(corpus: VisualCorpus | None, transcript: Transcript | None) -> bool:
    blobs: list[str] = []
    if corpus:
        blobs.extend(a.text for a in corpus.appearances)
    if transcript:
        blobs.extend(s.text for s in transcript.segments)
    text = " \n ".join(blobs)
    return any(p.search(text) for p in _FUTURE_RETURN_PATTERNS)


def _applies(check: Check, corpus, transcript) -> bool:
    cond = check.applies_when
    if cond == "always":
        return True
    if cond == "future_returns_shown":
        return _detect_future_returns(corpus, transcript)
    if cond == "performance_shown":
        return _detect_performance(corpus, transcript)
    # PHASE 2: add more named conditions as compliance defines them.
    # Unknown condition => conservatively evaluate (fail-safe: don't skip silently).
    return True


def _timestamp_for_frame(corpus: VisualCorpus | None, frame_index: int | None) -> str | None:
    if corpus is None or frame_index is None:
        return None
    for f in corpus.frames:
        if f.frame_index == frame_index:
            return _fmt_timestamp(f.timestamp_seconds)
    return None


def _not_applicable_result(check: Check, reason: str | None = None) -> CheckResult:
    msg = reason or f"Check does not apply: condition '{check.applies_when}' not met."
    return CheckResult(
        check_id=check.id,
        status=CheckStatus.pass_,  # excluded from scoring via not_applicable
        severity=check.severity,
        confidence=1.0,
        surfaces_evaluated=_surfaces_for(check),
        summary=msg,
        findings=[],
        reasoning=msg,
        evidence=[],
        policy_ref=check.policy_ref,
        low_confidence_inputs=False,
        not_applicable=True,
    )


def _error_result(check: Check, exc: Exception) -> CheckResult:
    """Fail-safe result when a check's evaluation raises (e.g. API error).

    One failing check must never abort the whole review; surface it as
    ``uncertain`` (never ``pass``) with the error in the reasoning.
    """
    return CheckResult(
        check_id=check.id,
        status=CheckStatus.uncertain,
        severity=check.severity,
        confidence=0.0,
        surfaces_evaluated=_surfaces_for(check),
        summary="Couldn’t evaluate this check — treated as uncertain.",
        findings=[f"{type(exc).__name__}: {exc}"],
        reasoning=f"Evaluation error, treated as uncertain: {type(exc).__name__}: {exc}",
        evidence=[],
        policy_ref=check.policy_ref,
        low_confidence_inputs=True,
    )


def _evaluate_vision(check: Check, corpus: VisualCorpus | None, client: ClaudeClient) -> CheckResult:
    if corpus is None or not corpus.frame_paths:
        msg = "Visual pipeline produced no frames to inspect; cannot judge."
        return CheckResult(
            check_id=check.id,
            status=CheckStatus.uncertain,
            severity=check.severity,
            confidence=0.0,
            surfaces_evaluated=["visual"],
            summary=msg,
            findings=[],
            reasoning=msg,
            evidence=[],
            policy_ref=check.policy_ref,
            low_confidence_inputs=True,
        )

    question = f"{check.description} {check.pass_criteria}"
    res = ask_visual_question(client, corpus, question)
    present = res.get("present", "unsure")
    confidence = float(res.get("confidence", 0.0))
    reasoning = res.get("reasoning", "")
    summary = res.get("summary", "")
    findings = [f for f in (res.get("findings", []) or []) if isinstance(f, str)]
    frame_idxs = res.get("frame_indices", []) or []

    # Polarity: a REQUIRED element passes when present; a PROHIBITED element
    # (vision_expect="absent", e.g. a celebrity / unauthorised logo) fails when present.
    prohibited = check.vision_expect == "absent"
    if present == "unsure":
        status = CheckStatus.uncertain
    elif present == "yes":
        status = CheckStatus.fail if prohibited else CheckStatus.pass_
    else:  # "no"
        status = CheckStatus.pass_ if prohibited else CheckStatus.fail

    evidence = [
        Evidence(
            surface="visual",
            frame_index=int(i),
            timestamp=_timestamp_for_frame(corpus, int(i)),
            quote=f"observed in frame {i}",
        )
        for i in frame_idxs[:6]
    ]

    return CheckResult(
        check_id=check.id,
        status=status,
        severity=check.severity,
        confidence=confidence,
        surfaces_evaluated=["visual"],
        summary=summary,
        findings=findings,
        reasoning=reasoning,
        evidence=evidence,
        policy_ref=check.policy_ref,
        low_confidence_inputs=(present == "unsure"),
    )


def _evaluate_text(
    check: Check,
    corpus: VisualCorpus | None,
    transcript: Transcript | None,
    client: ClaudeClient,
) -> CheckResult:
    prompt = build_claim_prompt(check, corpus, transcript)
    res = client.claim_check(CLAIM_SYSTEM, prompt)

    status = CheckStatus(res.get("status", "uncertain"))
    evidence: list[Evidence] = []
    for e in res.get("evidence", []) or []:
        surface = e.get("surface")
        if surface not in ("visual", "audio"):
            continue
        evidence.append(
            Evidence(
                surface=surface,
                timestamp=e.get("timestamp"),
                frame_index=e.get("frame_index"),
                quote=e.get("quote", ""),
            )
        )

    return CheckResult(
        check_id=check.id,
        status=status,
        severity=check.severity,
        confidence=float(res.get("confidence", 0.0)),
        surfaces_evaluated=_surfaces_for(check),
        summary=res.get("summary", ""),
        findings=[f for f in (res.get("findings", []) or []) if isinstance(f, str)],
        reasoning=res.get("reasoning", ""),
        evidence=evidence,
        policy_ref=check.policy_ref,
        low_confidence_inputs=bool(res.get("low_confidence_inputs", False)),
        not_applicable=bool(res.get("not_applicable", False)),
    )


def evaluate_check(
    check: Check,
    corpus: VisualCorpus | None,
    transcript: Transcript | None,
    client: ClaudeClient,
) -> CheckResult:
    # Surface gate: if NONE of the check's required surfaces ran for this upload
    # (e.g. an audio check on a still image), it can't be judged here. Mark it
    # not-applicable — excluded from scoring — without spending a Claude call.
    required = set(_surfaces_for(check))
    available = _available_surfaces(corpus, transcript)
    if not (required & available):
        missing = "/".join(sorted(required - available)) or "/".join(sorted(required))
        return _not_applicable_result(
            check, f"Required surface '{missing}' is not present in this upload."
        )

    if not _applies(check, corpus, transcript):
        return _not_applicable_result(check)
    if check.method == "vision":
        return _evaluate_vision(check, corpus, client)
    return _evaluate_text(check, corpus, transcript, client)


def _safe_evaluate_check(
    check: Check,
    corpus: VisualCorpus | None,
    transcript: Transcript | None,
    client: ClaudeClient,
) -> CheckResult:
    try:
        return evaluate_check(check, corpus, transcript, client)
    except Exception as exc:  # noqa: BLE001 — isolate per-check failures
        return _error_result(check, exc)


def evaluate_all(
    checks: list[Check],
    corpus: VisualCorpus | None,
    transcript: Transcript | None,
    client: ClaudeClient,
    max_workers: int = 9,
) -> list[CheckResult]:
    """Evaluate every check, concurrently.

    The calls are independent and network-bound (the sync Anthropic SDK is
    thread-safe for concurrent ``messages.create``), so we fan them out across a
    thread pool. Results are gathered **by index**, so output order — and thus
    the report — is identical to a serial run. A check that raises degrades to a
    fail-safe ``uncertain`` instead of aborting the whole review.
    """
    if not checks:
        return []
    workers = max(1, min(max_workers, len(checks)))
    if workers == 1:
        return [_safe_evaluate_check(c, corpus, transcript, client) for c in checks]

    results: list[CheckResult | None] = [None] * len(checks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_safe_evaluate_check, c, corpus, transcript, client): i
            for i, c in enumerate(checks)
        }
        for future, i in futures.items():
            results[i] = future.result()
    return results  # type: ignore[return-value]  # all slots filled above
