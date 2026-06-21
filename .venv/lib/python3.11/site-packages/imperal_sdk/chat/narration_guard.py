# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Narration guardrail — language-agnostic anti-fabrication system-prompt postamble.

Context (federal-grade, v1.5.24)
================================

The final narration round of a ChatExtension tool-use loop is an LLM call
that turns the actual ``_functions_called`` list into a user-facing
response. Before v1.5.24, the narration LLM occasionally **fabricated**
actions that never ran — e.g. claiming "I archived 3 emails and deleted
the spam folder" when only ``mail.list`` had actually been invoked. This
is a federal compliance breach (audit-trail divergence from reality).

The fix is **preventive and structural**, not detective:

1. Every narration LLM call carries a strict postamble appended to its
   ``system`` prompt. The postamble states the non-negotiable rule in
   plain language and shows the authoritative ``FUNCTIONS_CALLED`` list
   inline.
2. The rule is language-agnostic — no regex, no vocabulary matching,
   no per-language detection. It works for any user language.
3. The ``_functions_called`` list is the single source of structural
   truth — built by ``_execute_function`` inside ``handler.py`` and
   never written by the narration LLM.

Non-goals
---------
- We do NOT try to *detect* fabrication post-hoc with regex or token
  matching (that path was tried in kernel commit ``d66db64`` and
  reverted — see `docs/superpowers/specs/2026-04-22-chat-ext-inner-truth-gate-design.md`).
- We do NOT mandate a specific output format (plain text, markdown,
  JSON) — just forbid invention.

Exports
-------
- ``STRICT_NARRATION_POSTAMBLE``   : the raw rule text (format-string)
- ``format_functions_called_summary`` : render fc-list → human-readable bullets
- ``augment_system_with_narration_rule`` : returns ``system + postamble``

Invariants
----------
- **I-NARRATION-STRICT-1**: every narration LLM call in SDK goes through
  ``augment_system_with_narration_rule``. No direct system-only call.
- **I-NARRATION-STRICT-2**: postamble text is frozen and identical in
  every language — it describes the rule, never parrots a message back.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = (
    "STRICT_NARRATION_POSTAMBLE",
    "format_functions_called_summary",
    "augment_system_with_narration_rule",
)


STRICT_NARRATION_POSTAMBLE: str = """\
---
STRICT NARRATION RULE (federal-grade, non-negotiable):
You are describing operations in the FUNCTIONS_CALLED list below. You MUST:
1. Describe ONLY operations explicitly present in FUNCTIONS_CALLED.
2. NEVER claim, imply, suggest, or mention any operation that is not in FUNCTIONS_CALLED \
— regardless of the user's request.
3. If an operation is in FUNCTIONS_CALLED with status=error, describe it as failed honestly. \
Do not soften or fabricate success.
4. If FUNCTIONS_CALLED is empty, describe the inability to act — do not invent any actions.
5. This rule applies to every language (English, Russian, Ukrainian, Turkish, Hebrew, \
German, Chinese, Arabic, or any other).
6. Violation of this rule is a federal compliance breach.

FUNCTIONS_CALLED (ground truth — narrate ONLY these):
{functions_called_summary}
"""


def _short(value: Any, limit: int = 200) -> str:
    """Compact repr — trims long strings, keeps shape for dict/list."""
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            s = value
        elif isinstance(value, Mapping):
            s = ", ".join(f"{k}={value[k]}" for k in list(value)[:4])
            if len(value) > 4:
                s += ", ..."
        elif isinstance(value, (list, tuple)):
            s = f"{len(value)} items"
        else:
            s = str(value)
    except Exception:
        s = "<unrenderable>"
    if len(s) > limit:
        s = s[:limit] + "..."
    return s


def _extract_status_and_detail(fc: Mapping[str, Any]) -> tuple[str, str]:
    """Return (status, detail) for a single functions_called entry.

    Status is one of: "SUCCESS", "ERROR", "CONFIRM_REQUIRED".
    Detail is a short human string (summary, error msg, etc.).
    """
    if fc.get("intercepted"):
        return "CONFIRM_REQUIRED", "awaiting user confirmation"
    success = bool(fc.get("success"))
    result = fc.get("result")

    if not success:
        # Error branch
        err = ""
        if result is not None:
            err = getattr(result, "error", "") or ""
            if not err and hasattr(result, "to_dict"):
                try:
                    err = str(result.to_dict().get("error", "")) or ""
                except Exception:
                    err = ""
        return "ERROR", _short(err) if err else "failed"

    # Success branch — prefer summary, then data shape
    summary = ""
    if result is not None:
        summary = getattr(result, "summary", "") or ""
        if not summary:
            data = getattr(result, "data", None)
            if data is not None:
                summary = _short(data)
    return "SUCCESS", summary


def format_functions_called_summary(
    functions_called: Sequence[Mapping[str, Any]] | None,
) -> str:
    """Render the ``_functions_called`` list as a plain-text bulleted summary.

    Output shape (example)::

        - mail.read_email — ERROR: Message not found
        - notes.create — SUCCESS: id=abc123
        (2 operations total: 1 succeeded, 1 failed)

    Empty list returns a single sentinel line used by the postamble so the
    narration LLM can see "nothing happened" explicitly.

    Args:
        functions_called: the ``ChatExtension._functions_called`` list (or None).

    Returns:
        A plain-text summary — safe for direct substitution into the postamble.
    """
    if not functions_called:
        return "(no operations were performed)"

    lines: list[str] = []
    n_success = 0
    n_error = 0
    n_confirm = 0
    for fc in functions_called:
        name = fc.get("name") or "(unknown)"
        status, detail = _extract_status_and_detail(fc)
        if status == "SUCCESS":
            n_success += 1
        elif status == "ERROR":
            n_error += 1
        else:
            n_confirm += 1
        if detail:
            lines.append(f"- {name} — {status}: {detail}")
        else:
            lines.append(f"- {name} — {status}")

    total = len(functions_called)
    tail = f"({total} operation{'s' if total != 1 else ''} total: {n_success} succeeded, {n_error} failed"
    if n_confirm:
        tail += f", {n_confirm} awaiting confirmation"
    tail += ")"
    lines.append(tail)
    return "\n".join(lines)


def augment_system_with_narration_rule(
    system_prompt: str,
    functions_called: Sequence[Mapping[str, Any]] | None,
) -> str:
    """Return ``system_prompt`` with the strict narration postamble appended.

    Safe to call on any string — including empty. The postamble always
    lands at the end of the prompt, so the narration LLM sees it as the
    final instruction before the user turn.

    Args:
        system_prompt: the composed system prompt string (pre-postamble).
        functions_called: the ``_functions_called`` list to render inline.

    Returns:
        ``system_prompt + "\\n\\n" + formatted_postamble``
    """
    summary = format_functions_called_summary(functions_called)
    postamble = STRICT_NARRATION_POSTAMBLE.format(functions_called_summary=summary)
    base = system_prompt or ""
    if base and not base.endswith("\n"):
        base = base + "\n"
    return base + "\n" + postamble
