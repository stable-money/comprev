"""Anthropic Claude wrapper: structured-JSON tool calls + retry.

Used for both claim reasoning (fusion) and vision perception checks. We force
a structured response by giving Claude a single tool and requiring a tool_use
reply, so we never have to parse free-form prose into a verdict.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Optional

from .config import get_api_key

# The tool Claude must call to answer a claim check. Mirrors the verdict fields
# the fusion layer needs.
CLAIM_TOOL = {
    "name": "report_check_result",
    "description": (
        "Report the compliance verdict for a single check. Return 'uncertain' "
        "whenever the evidence is ambiguous OR you had to rely on a segment "
        "marked low-confidence. Never return 'pass' without positive evidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "summary": {
                "type": "string",
                "description": (
                    "ONE short plain-language sentence (max ~20 words) stating the "
                    "verdict and the single decisive reason. No jargon, no metrics "
                    "dumps. E.g. 'Fails: the warning is on screen 2s, below the 5s "
                    "minimum, and is small and low-contrast.'"
                ),
            },
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-6 short bullet observations behind the verdict, decisive one "
                    "first. Each is one self-contained point (≤ ~18 words). Put "
                    "concrete numbers here, not in the summary."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "Full prose reasoning for the audit trail.",
            },
            "low_confidence_inputs": {"type": "boolean"},
            "not_applicable": {
                "type": "boolean",
                "description": "True only if the check's applies_when condition is not met.",
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "surface": {"type": "string", "enum": ["visual", "audio"]},
                        "timestamp": {"type": "string"},
                        "frame_index": {"type": "integer"},
                        "quote": {"type": "string"},
                    },
                    "required": ["surface", "quote"],
                },
            },
        },
        "required": [
            "status", "confidence", "summary", "findings", "reasoning",
            "low_confidence_inputs",
        ],
    },
}

VISION_TOOL = {
    "name": "report_visual_finding",
    "description": "Answer the specific visual question about the provided frames.",
    "input_schema": {
        "type": "object",
        "properties": {
            "present": {
                "type": "string",
                "enum": ["yes", "no", "unsure"],
                "description": "Whether the asked-about element is present.",
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "summary": {
                "type": "string",
                "description": (
                    "ONE short plain-language sentence (max ~20 words) stating the "
                    "verdict and the decisive reason."
                ),
            },
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 short bullet observations behind the verdict.",
            },
            "reasoning": {
                "type": "string",
                "description": "Full prose reasoning for the audit trail.",
            },
            "frame_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Indices of frames where the element was observed.",
            },
        },
        "required": ["present", "confidence", "summary", "findings", "reasoning"],
    },
}


class ClaudeClient:
    def __init__(self, model: str, max_tokens: int = 2048, max_retries: int = 3):
        # Imported lazily so the package imports without the SDK installed.
        from anthropic import Anthropic

        self.model = model
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self._client = Anthropic(api_key=get_api_key())

    def _call_tool(
        self,
        system: str,
        content: list[dict[str, Any]],
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        """Send one message forcing a call to ``tool``; return the tool input dict."""
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=[{"role": "user", "content": content}],
                )
                for block in resp.content:
                    if getattr(block, "type", None) == "tool_use":
                        return dict(block.input)
                raise ValueError("Model did not return a tool_use block")
            except Exception as e:  # noqa: BLE001 — retry transient/validation errors
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Claude tool call failed after {self.max_retries} attempts: {last_err}")

    def claim_check(self, system: str, user_text: str) -> dict[str, Any]:
        return self._call_tool(system, [{"type": "text", "text": user_text}], CLAIM_TOOL)

    def vision_check(
        self, system: str, question: str, frame_paths: list[Path]
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": question}]
        for p in frame_paths:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(Path(p).read_bytes()).decode("ascii"),
                    },
                }
            )
        return self._call_tool(system, content, VISION_TOOL)
