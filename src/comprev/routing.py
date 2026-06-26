"""Fail-safe routing: turn raw per-check results into the final verdict.

Rules (from the brief):
  * A check is ``fail`` only on clear evidence of violation.
  * A check is ``pass`` only with positive compliance evidence AND no
    low-confidence input fed it. (Enforced here as a guardrail even if an
    upstream reasoner slips: a pass with low_confidence_inputs is downgraded
    to uncertain.)
  * Otherwise => ``uncertain``.
  * overall_status: ``fail`` if any check failed; else ``needs_review`` if any
    check is uncertain; else ``pass``.
  * needs_human_review is true whenever overall is not pass.
"""

from __future__ import annotations

from .schemas import CheckResult, CheckStatus, OverallStatus, VideoReport


def enforce_failsafe(result: CheckResult) -> CheckResult:
    """Guardrail: never let a low-confidence-fed result stand as ``pass``.

    Inability to hear/read a region is not evidence of compliance.
    """
    if result.status == CheckStatus.pass_ and result.low_confidence_inputs:
        result.status = CheckStatus.uncertain
        result.reasoning = (
            "[downgraded to uncertain: pass relied on low-confidence input] "
            + result.reasoning
        )
    return result


def route(
    video_id: str,
    duration_seconds: float,
    results: list[CheckResult],
    product: str = "mutual_funds",
    policy_version: str | None = None,
    policy_source: str | None = None,
    checks_hash: str | None = None,
) -> VideoReport:
    """Assemble the final VideoReport from individual check results."""
    results = [enforce_failsafe(r) for r in results]

    # Not-applicable checks are reported but excluded from status scoring.
    scored = [r for r in results if not r.not_applicable]

    any_fail = any(r.status == CheckStatus.fail for r in scored)
    any_uncertain = any(r.status == CheckStatus.uncertain for r in scored)

    if any_fail:
        overall = OverallStatus.fail
    elif any_uncertain:
        overall = OverallStatus.needs_review
    else:
        overall = OverallStatus.pass_

    review_reasons = _build_review_reasons(scored)
    needs_human_review = overall != OverallStatus.pass_

    return VideoReport(
        video_id=video_id,
        product=product,
        duration_seconds=duration_seconds,
        overall_status=overall,
        checks=results,
        needs_human_review=needs_human_review,
        review_reasons=review_reasons,
        policy_version=policy_version,
        policy_source=policy_source,
        checks_hash=checks_hash,
    )


def _build_review_reasons(scored: list[CheckResult]) -> list[str]:
    reasons: list[str] = []

    failed = [r for r in scored if r.status == CheckStatus.fail]
    for r in failed:
        tag = " (SERIOUS)" if r.severity.value == "serious" else ""
        reasons.append(f"{r.check_id} failed{tag}")

    n_uncertain = sum(1 for r in scored if r.status == CheckStatus.uncertain)
    if n_uncertain:
        reasons.append(
            f"{n_uncertain} check{'s' if n_uncertain != 1 else ''} uncertain"
        )

    return reasons
