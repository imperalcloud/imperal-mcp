# imperal_sdk/chat/refusal.py
"""ICNLI v7 — extension-side refusal primitive.

When an extension's internal LLM decides it cannot complete the user's
request, it invokes the emit_refusal tool instead of free-text refusal
like "in this mode you can't..." Kernel receives the structured refusal
and renders a typed Refusal template.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExtensionRefusalReason = Literal[
    "no_scope",
    "missing_params",
    "already_done",
    "tool_unavailable",
    "external_error",
]


EMIT_REFUSAL_TOOL = {
    "name": "emit_refusal",
    "description": (
        "Emit a typed refusal when you cannot complete the user's request. "
        "Use this INSTEAD of free-text refusal. Kernel will render a "
        "localised, honest response with next-step suggestions. "
        "Do NOT emit refusals via plain text — use this tool."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["reason", "user_message"],
        "properties": {
            "reason": {
                "type": "string",
                "enum": [
                    "no_scope", "missing_params", "already_done",
                    "tool_unavailable", "external_error",
                ],
                "description": "Typed reason for refusal.",
            },
            "user_message": {
                "type": "string",
                "maxLength": 500,
                "description": "Explanation for the user (translated by kernel if needed).",
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string", "maxLength": 200},
                "maxItems": 3,
                "description": "Optional suggestions the user can try.",
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class RefusalEmission:
    reason: ExtensionRefusalReason
    user_message: str
    next_steps: tuple[str, ...] = ()


def parse_refusal_tool_use(tool_use_input: dict) -> RefusalEmission:
    """Convert a tool_use input dict to typed RefusalEmission."""
    return RefusalEmission(
        reason=tool_use_input.get("reason", "external_error"),
        user_message=tool_use_input.get("user_message", ""),
        next_steps=tuple(tool_use_input.get("next_steps") or ()),
    )
