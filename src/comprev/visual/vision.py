"""Claude vision perception checks (e.g. 'is a Riskometer graphic present').

For checks that need perception rather than text, we send a curated set of
sampled frames to the Claude vision API and ask the specific structured
question. We do NOT template-match these.
"""

from __future__ import annotations

from pathlib import Path

from ..claude_client import ClaudeClient
from ..schemas import VisualCorpus

# Cap frames per vision call to keep payload/cost bounded; prefer scene-cut
# frames (where graphics tend to change) plus an even spread.
_MAX_FRAMES = 12

_VISION_SYSTEM = (
    "You are a compliance reviewer examining frames from a mutual-fund marketing "
    "video. Answer ONLY the specific visual question asked, using the provided "
    "frames as evidence. If the frames are ambiguous or you cannot tell, answer "
    "'unsure' — do not guess. Inability to see something clearly is not evidence "
    "that it is absent.\n\n"
    "For a busy reviewer: give a one-line plain-language `summary` (verdict + "
    "decisive reason), 2-5 short `findings` bullets (decisive first), and full "
    "`reasoning` for the audit trail."
)


def _select_frames(corpus: VisualCorpus) -> list[tuple[int, Path]]:
    paths = corpus.frame_paths
    if not paths:
        return []
    scene_cut_idxs = {f.frame_index for f in corpus.frames if f.is_scene_cut}
    ordered = sorted(paths.keys())

    chosen: list[int] = [i for i in ordered if i in scene_cut_idxs]
    # Fill the rest with an even spread over remaining frames.
    remaining = [i for i in ordered if i not in scene_cut_idxs]
    if remaining and len(chosen) < _MAX_FRAMES:
        step = max(1, len(remaining) // max(1, _MAX_FRAMES - len(chosen)))
        chosen.extend(remaining[::step])

    chosen = sorted(set(chosen))[:_MAX_FRAMES]
    return [(i, Path(paths[i])) for i in chosen]


def ask_visual_question(
    client: ClaudeClient, corpus: VisualCorpus, question: str
) -> dict:
    """Ask one structured visual question over selected frames.

    Returns the vision tool payload: {present, confidence, reasoning, frame_indices}.
    """
    frames = _select_frames(corpus)
    if not frames:
        return {
            "present": "unsure",
            "confidence": 0.0,
            "summary": "Can't judge — no frames were available to inspect.",
            "findings": [],
            "reasoning": "No frames available to inspect.",
            "frame_indices": [],
        }

    idxs = [i for i, _ in frames]
    paths = [p for _, p in frames]
    prompt = (
        f"{question}\n\n"
        f"You are shown {len(paths)} sampled frames (frame indices: {idxs}). "
        "Report whether the element is present and cite the frame indices where "
        "you saw it."
    )
    return client.vision_check(_VISION_SYSTEM, prompt, paths)
