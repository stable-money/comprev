"""Fusion wiring with a mocked Claude client.

Verifies the logic that does NOT depend on the live API: applies_when gating,
text-claim evidence mapping, vision present->status mapping, and the
OR-across-surfaces surfaces_evaluated for 'both' checks.
"""

from comprev.fusion.evaluate import evaluate_check
from comprev.schemas import (
    Check,
    CheckStatus,
    Severity,
    Surface,
    TextAppearance,
    Transcript,
    TranscriptSegment,
    VisualCorpus,
)


class FakeClient:
    """Stand-in for ClaudeClient returning canned tool payloads."""

    def __init__(self, claim=None, vision=None):
        self._claim = claim or {}
        self._vision = vision or {}

    def claim_check(self, system, user_text):
        return self._claim

    def vision_check(self, system, question, frame_paths):
        return self._vision


def _corpus(strings):
    return VisualCorpus(
        sample_interval_seconds=2.0,
        frames=[],
        appearances=[
            TextAppearance(
                text=s, frame_indices=[0], timestamps=[0.0], on_screen_seconds=4.0,
                min_height_ratio=0.03, max_height_ratio=0.03, min_contrast=5.0,
                min_ocr_confidence=0.95, low_confidence=False,
            )
            for s in strings
        ],
        frame_paths={0: "/tmp/x.jpg"},
    )


def _transcript(texts):
    return Transcript(
        segments=[
            TranscriptSegment(start=i, end=i + 1, text=t, avg_logprob=-0.2, no_speech_prob=0.1)
            for i, t in enumerate(texts)
        ],
        audio_path="/tmp/a.wav",
        language="en",
    )


def _check(cid, surface="both", applies="always", method="text", severity="serious"):
    return Check(
        id=cid, description="d", surface=Surface(surface), severity=Severity(severity),
        applies_when=applies, method=method, policy_ref="ref", pass_criteria="pc",
    )


def test_performance_check_not_applicable_when_no_performance():
    chk = _check("perf", applies="performance_shown")
    res = evaluate_check(chk, _corpus(["scheme name"]), _transcript(["welcome"]), FakeClient())
    assert res.not_applicable is True


def test_performance_check_applies_when_percentage_present():
    chk = _check("perf", applies="performance_shown")
    client = FakeClient(claim={"status": "pass", "confidence": 0.8, "reasoning": "ok", "low_confidence_inputs": False, "evidence": []})
    res = evaluate_check(chk, _corpus(["returns of 15% last year"]), _transcript([]), client)
    assert res.not_applicable is False
    assert res.status == CheckStatus.pass_


def test_both_surface_check_records_both_surfaces():
    chk = _check("guar", surface="both")
    client = FakeClient(claim={
        "status": "fail", "confidence": 0.95, "reasoning": "assured returns claimed",
        "low_confidence_inputs": False,
        "evidence": [{"surface": "audio", "timestamp": "00:01-00:02", "quote": "guaranteed 9%"}],
    })
    res = evaluate_check(chk, _corpus(["x"]), _transcript(["guaranteed 9 percent"]), client)
    assert res.status == CheckStatus.fail
    assert set(res.surfaces_evaluated) == {"visual", "audio"}
    assert res.evidence and res.evidence[0].surface == "audio"


def test_vision_present_maps_to_pass():
    chk = _check("riskometer", surface="visual", method="vision")
    client = FakeClient(vision={"present": "yes", "confidence": 0.9, "reasoning": "seen", "frame_indices": [0]})
    res = evaluate_check(chk, _corpus(["x"]), None, client)
    assert res.status == CheckStatus.pass_


def test_vision_absent_maps_to_fail():
    chk = _check("riskometer", surface="visual", method="vision")
    client = FakeClient(vision={"present": "no", "confidence": 0.9, "reasoning": "absent", "frame_indices": []})
    res = evaluate_check(chk, _corpus(["x"]), None, client)
    assert res.status == CheckStatus.fail


def test_vision_unsure_maps_to_uncertain():
    chk = _check("riskometer", surface="visual", method="vision")
    client = FakeClient(vision={"present": "unsure", "confidence": 0.2, "reasoning": "blurry", "frame_indices": []})
    res = evaluate_check(chk, _corpus(["x"]), None, client)
    assert res.status == CheckStatus.uncertain
    assert res.low_confidence_inputs is True
