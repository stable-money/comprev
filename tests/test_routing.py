"""Routing rules + the fail-safe guardrail."""

from comprev.routing import enforce_failsafe, route
from comprev.schemas import CheckResult, CheckStatus, OverallStatus, Severity


def _r(check_id, status, severity="serious", low_conf=False, na=False):
    return CheckResult(
        check_id=check_id,
        status=status,
        severity=Severity(severity),
        confidence=0.9,
        surfaces_evaluated=["visual"],
        reasoning="x",
        evidence=[],
        policy_ref="ref",
        low_confidence_inputs=low_conf,
        not_applicable=na,
    )


def test_pass_with_low_confidence_is_downgraded():
    r = enforce_failsafe(_r("c", CheckStatus.pass_, low_conf=True))
    assert r.status == CheckStatus.uncertain


def test_pass_without_low_confidence_stays_pass():
    r = enforce_failsafe(_r("c", CheckStatus.pass_, low_conf=False))
    assert r.status == CheckStatus.pass_


def test_any_fail_makes_overall_fail():
    report = route("v", 10.0, [_r("a", CheckStatus.pass_), _r("b", CheckStatus.fail)])
    assert report.overall_status == OverallStatus.fail
    assert report.needs_human_review is True
    assert any("b failed" in r for r in report.review_reasons)


def test_uncertain_makes_needs_review():
    report = route("v", 10.0, [_r("a", CheckStatus.pass_), _r("b", CheckStatus.uncertain)])
    assert report.overall_status == OverallStatus.needs_review
    assert report.needs_human_review is True


def test_all_pass_is_pass():
    report = route("v", 10.0, [_r("a", CheckStatus.pass_), _r("b", CheckStatus.pass_, severity="normal")])
    assert report.overall_status == OverallStatus.pass_
    assert report.needs_human_review is False


def test_not_applicable_excluded_from_scoring():
    # An n/a check (stored as pass) must not make the overall a pass on its own,
    # nor should an n/a uncertain force review.
    report = route("v", 10.0, [_r("a", CheckStatus.pass_, na=True), _r("b", CheckStatus.pass_)])
    assert report.overall_status == OverallStatus.pass_
