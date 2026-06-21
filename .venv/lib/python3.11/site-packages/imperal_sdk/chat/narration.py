# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Federal-Grade Chat Integrity — emit_narration tool contract (P2 Task 18).

Structural foundation for Component 1 (Narration Contract Hybrid). The kernel
injects ``EMIT_NARRATION_TOOL`` into every ChatExtension turn and requires the
LLM to call it to terminate the turn with narrated prose. The LLM cannot
fabricate — every claim made in ``per_call_verdicts`` is structurally
verified against ``_functions_called`` by the kernel before the response
reaches the user.

Spec: ``docs/superpowers/specs/2026-04-23-federal-grade-chat-integrity-design.md``
§3.2 (Narration Contract Hybrid).

----

Relation to ``imperal_sdk/chat/narration_guard.py`` (soft-rule postamble,
v1.5.24): that module appended a natural-language instruction to the system
prompt telling the LLM to stay honest — a *soft* guardrail. This new module
is the *structural* replacement. A tool-call is forced, its shape is
machine-checkable, and the kernel enforces consistency post-hoc regardless of
what the LLM tried to emit in prose. Deprecation of ``narration_guard.py`` is
handled by Task 27 when the handler wires ``emit_narration`` through — this
module does not touch ``narration_guard.py``.

----

**Schema design decision: Option A (keep ``minimum: 0`` on integer fields).**

The spec plan offered Option A (keep ``minimum: 0``, accept OpenAI non-strict
degradation) vs Option B (drop ``minimum: 0`` so both Anthropic and OpenAI
can run strict mode, and enforce ``>= 0`` at the Pydantic layer).

Option A wins here because the schema contains ``identifiers_used`` which is
*intentionally optional* (not in top-level ``required``). The kernel's
``_is_oai_strict_eligible`` (see the platform LLM adapter) requires
that every property be listed in ``required[]`` — so this schema is
**already ineligible** for OpenAI strict mode regardless of whether we keep
``minimum``. Dropping ``minimum`` would surrender a defense-in-depth wire
validation on the Anthropic path and buy nothing on the OpenAI path.

We therefore keep the wire-level ``minimum: 0`` AND enforce ``ge=0`` at the
Pydantic parser layer. Two layers of defense — Anthropic validates at the
provider boundary, kernel validates after parse.

----

Invariants (see spec §3.2):

- ``EMIT_NARRATION_TOOL`` shape is frozen — changes require spec update
  + kernel verifier update.
- ``mode``, ``prose``, ``per_call_verdicts``, ``task_targets`` are
  required; ``identifiers_used`` is optional.
- Verdict status is one of ``{"success", "error", "intercepted"}`` —
  must match the kernel's ``_functions_called[*].status`` vocabulary.
- Parsed ``NarrationEmission`` is immutable (Pydantic ``frozen=True``)
  — no post-parse tampering.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


EMIT_NARRATION_TOOL = {
    "name": "emit_narration",
    "description": (
        "Emit the final user-facing response for this turn. This is the "
        "ONLY way to complete the turn with narrated prose. The kernel "
        "structurally verifies your claims against the tool-call history."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["mode", "prose", "per_call_verdicts", "task_targets"],
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["audit", "narrative"],
                "description": (
                    "Kernel-assigned by classifier. Echo the value from "
                    "system_hint. Cannot be self-selected. SCOPE: this "
                    "field controls ONLY how the prose field below is "
                    "interpreted by the kernel renderer — it is NOT a "
                    "global brevity directive. Other tool calls in this "
                    "turn (create_note, send_email, write_post, etc.) "
                    "MUST contain the FULL user-requested content in "
                    "their own parameter fields, regardless of audit "
                    "vs. narrative mode."
                ),
            },
            "prose": {
                "type": "string",
                "description": (
                    "User-facing text. In audit mode, used ONLY to phrase "
                    "per-call verdicts; kernel composes the overall layout. "
                    "In narrative mode, the full response. CRITICAL: this "
                    "field's brevity rule applies ONLY to this prose field "
                    "— content fields in OTHER tool calls (e.g. "
                    "create_note.content_text, send_email.body) MUST carry "
                    "the full content the user asked for, never "
                    "placeholders like '<essay 200 words>'."
                ),
            },
            "per_call_verdicts": {
                "type": "array",
                "description": (
                    "Structured claim per _functions_called entry. Every "
                    "entry MUST correspond to a real call by (name, status). "
                    "Kernel rejects narration if any verdict lacks a match."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["call_index", "name", "status", "user_phrasing"],
                    "properties": {
                        "call_index": {"type": "integer", "minimum": 0},
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["success", "error", "intercepted"]},
                        "user_phrasing": {
                            "type": "string",
                            "description": (
                                "Short user-facing label for this call, e.g. "
                                "'sent to xmountshadow@gmail.com' or 'validation "
                                "failed — missing body'. In audit mode kernel "
                                "renders this under the call's status badge."
                            ),
                        },
                    },
                },
            },
            "task_targets": {
                "type": "object",
                "additionalProperties": False,
                "required": ["expected", "succeeded"],
                "properties": {
                    "expected": {"type": ["integer", "null"]},
                    "succeeded": {"type": "integer", "minimum": 0},
                },
                "description": (
                    "If classifier extracted task_count_target (e.g. '5 tables'), "
                    "echo expected=N here; count real successes in succeeded. "
                    "Kernel appends a **Note:** if expected != succeeded."
                ),
            },
            "identifiers_used": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Every identifier (table name, email address, URL, id) "
                    "that appears in prose MUST be listed here AND appear in "
                    "at least one _functions_called[*].data snapshot OR in "
                    "user_message haystack. Prevents semantic fabrication "
                    "(P1-1 fake table names)."
                ),
            },
        },
    },
}


class PerCallVerdict(BaseModel):
    """One structured claim per _functions_called entry.

    ``call_index`` is the 0-based position in the kernel's
    ``_functions_called`` list. The kernel rejects narration if any verdict's
    ``(name, status)`` lacks a matching entry at that index.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_index: int = Field(..., ge=0)
    name: str
    status: Literal["success", "error", "intercepted"]
    user_phrasing: str


class TaskTargets(BaseModel):
    """Expected vs. actual task-count target for this turn.

    Populated when the classifier extracted a count ("5 tables",
    "send 3 emails"). The kernel appends a ``**Note:**`` disclosure when
    ``expected != succeeded``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: Optional[int] = Field(default=None)
    succeeded: int = Field(default=0, ge=0)


class NarrationEmission(BaseModel):
    """Typed parse of an ``emit_narration`` tool_use input.

    The LLM cannot mutate this object after parse — ``frozen=True`` enforces
    immutability. ``extra="forbid"`` rejects unknown keys that could smuggle
    fabricated fields past the kernel verifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["audit", "narrative"]
    prose: str
    per_call_verdicts: tuple[PerCallVerdict, ...] = Field(default_factory=tuple)
    task_targets: TaskTargets
    identifiers_used: tuple[str, ...] = Field(default_factory=tuple)


def parse_narration_emission(tool_input: dict) -> NarrationEmission:
    """Parse and validate an ``emit_narration`` tool_use input dict.

    Raises :class:`pydantic.ValidationError` on malformed input.
    """
    return NarrationEmission.model_validate(tool_input)


__all__ = [
    "EMIT_NARRATION_TOOL",
    "NarrationEmission",
    "PerCallVerdict",
    "TaskTargets",
    "parse_narration_emission",
]
