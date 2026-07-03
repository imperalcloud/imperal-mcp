# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Security guards for the ChatExtension tool-use loop.

Intent guard, target-scope guard, write-arg-bleed guard, and 2-step
confirmation guard. All guards return a JSON content string when
blocking/intercepting, or None when the tool_use should proceed to
execution.
"""
from __future__ import annotations
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from imperal_sdk.chat.extension import ChatExtension

# Target scope guard (kernel-only, graceful fallback in SDK-only mode)
try:
    from imperal_sdk.runtime.executor import _check_target_scope
except ImportError:
    import logging as _log_tsc
    _log_tsc.getLogger(__name__).error(
        "CRITICAL: _check_target_scope import failed — all cross-user actions will be BLOCKED"
    )
    def _check_target_scope(**kwargs):
        return {"allowed": False, "cross_user": True, "error": "target_scope_unavailable"}

# Canonical error-code taxonomy (P2 Task 19 → imperal_sdk.chat.error_codes.ERROR_TAXONOMY).
# Import with fallback mirroring the exact 9 keys — so a missing/broken
# Task 19 module still leaves the bleed guard operational on the canonical set.
try:
    from imperal_sdk.chat.error_codes import ERROR_TAXONOMY, FABRICATED_ID_SHAPE  # type: ignore
except ImportError:  # pragma: no cover — defensive
    FABRICATED_ID_SHAPE = "FABRICATED_ID_SHAPE"  # type: ignore[assignment]
    ERROR_TAXONOMY = frozenset({
        "VALIDATION_MISSING_FIELD",
        "VALIDATION_TYPE_ERROR",
        "UNKNOWN_TOOL",
        "UNKNOWN_SUB_FUNCTION",
        "PERMISSION_DENIED",
        "BACKEND_TIMEOUT",
        "BACKEND_5XX",
        "RATE_LIMITED",
        "INTERNAL",
    })

log = logging.getLogger(__name__)


def _get_connected_emails(ctx) -> list[str]:
    """Retrieve connected-email list from ``ctx._metadata``.

    Kernel populates ``ctx._metadata["connected_emails"]`` at tool-dispatch
    time per the **I-CONNECTED-EMAILS-VIA-METADATA** invariant (see Phase 5
    kernel work). Returns ``[]`` in legacy/dev contexts where metadata is
    not yet populated — this is **fail-SAFE** (empty list narrows
    target-scope authorisation, does not widen; a non-owner caller with
    an empty connected-email set cannot match foreign addresses and so
    cross-user writes stay blocked by the target-scope guard).
    """
    meta = getattr(ctx, "_metadata", None) or {}
    if not isinstance(meta, dict):
        return []
    val = meta.get("connected_emails", [])
    if not isinstance(val, list):
        return []
    # Keep only string entries, filter empties
    return [e for e in val if isinstance(e, str) and e]


def check_guards(
    chat_ext: ChatExtension,
    ctx,
    tu,
    action_type: str,
    confirmation_required: bool,
) -> str | None:
    """Run all security guards for a single tool_use block.

    Returns a JSON content string if the call should be blocked or intercepted,
    or None if the call should proceed to execution.
    """
    # ── Intent guard ──────────────────────────────────────────────
    _ctx_intent = getattr(ctx, "_intent_type", None) or "read"
    if _ctx_intent in ("chain", "automation"):
        pass  # Bypass: function's own action_type is the source of truth
    elif _ctx_intent == "read" and action_type == "write":
        # Escalate: when the extension LLM confidently picks a write tool
        # under a read-classified turn, trust the tool choice (LLM is
        # authoritative over classifier heuristics) and promote _intent_type
        # to "write". The extension then proceeds to execute. Destructive
        # actions do NOT escalate — they still require 2-step confirmation,
        # so the old BLOCK path covers them below.
        log.info(
            f"ChatExtension {chat_ext.tool_name}: ESCALATE {tu.name} "
            f"action=write; classifier said read but extension LLM chose write — trusting LLM"
        )
        ctx._intent_type = "write"
        # Do not append to _functions_called; do not return a verdict — fall
        # through to target_scope + confirmation guards below.
    elif _ctx_intent == "read" and action_type == "destructive":
        # Escalate: classifier returns intent=read for many ambiguous
        # "delete X" phrasings; trust the extension LLM's destructive tool
        # choice and let the confirmation_gate below issue the 2-step
        # intercept. The old BLOCK path produced a prose-loop because the
        # LLM kept getting "ask user to confirm" feedback and re-asking via
        # prose without ever reaching confirmation_gate. confirmation_gate
        # is the authoritative 2-step authority — it must see destructive
        # calls. Symmetric with the write-escalate branch above.
        log.info(
            f"ChatExtension {chat_ext.tool_name}: ESCALATE {tu.name} "
            f"action=destructive; classifier said read but extension LLM chose "
            f"destructive — trusting LLM, confirmation_gate handles 2-step"
        )
        ctx._intent_type = "destructive"
        # Do not append to _functions_called; do not return a verdict — fall
        # through to target_scope + confirmation guards below.

    # ── Placeholder-args guard (I-PARAMS-NO-PLACEHOLDER-VALUES) ───
    # Defence-in-depth: reject ANY tool call whose arg values are LLM-emitted
    # placeholder sentinels (`<UNKNOWN>`, `<TODO>`, `<MISSING>`, etc).
    # Runs BEFORE write-arg-bleed + target-scope + confirmation guards so
    # we fail fast on poisoned inputs and never waste a billing-charged
    # dispatch or pollute the audit ledger with `target=<UNKNOWN>` rows.
    # See federal invariant **I-PARAMS-NO-PLACEHOLDER-VALUES**.
    placeholder_reason = check_placeholder_args(tu, action_type)
    if placeholder_reason is not None:
        chat_ext._functions_called.append({
            "name": tu.name, "params": tu.input,
            "action_type": action_type, "success": False, "intercepted": False,
            "event": "", "result": None,
        })
        return json.dumps({"RESULT": "BLOCKED", "error": placeholder_reason})

    # ── Write-arg-bleed guard (I-WRITE-ARG-NO-BLEED) ──────────────
    # Defence-in-depth: reject any write/destructive call whose args contain
    # substrings of prior ERROR_TAXONOMY codes, even if the LLM paraphrased
    # an error_code into user-visible text. Runs BEFORE target_scope so we
    # fail fast on poisoned inputs without wasting cycles on scope checks.
    bleed = check_write_arg_bleed(tu, chat_ext._functions_called, action_type)
    if bleed is not None:
        chat_ext._functions_called.append({
            "name": tu.name, "params": tu.input,
            "action_type": action_type, "success": False, "intercepted": False,
            "event": "", "result": None,
        })
        return json.dumps({"RESULT": "BLOCKED", "error": bleed})

    # ── Target scope guard ────────────────────────────────────────
    blocked = _check_target_scope_guard(chat_ext, ctx, tu, action_type, confirmation_required)
    if blocked is not None:
        return blocked

    # ── 2-step confirmation guard ─────────────────────────────────
    intercepted = _check_confirmation_guard(chat_ext, ctx, tu, action_type, confirmation_required)
    if intercepted is not None:
        return intercepted

    return None


# Federal invariant **I-PARAMS-NO-PLACEHOLDER-VALUES** sentinel pattern.
# Matches LLM-emitted placeholder values of the form `<NAME>` where NAME is
# uppercase ASCII + digits + underscores (e.g. `<UNKNOWN>`, `<TODO>`,
# `<MISSING>`, `<EMAIL>`, `<PASSWORD>`, `<USER_ID>`). The pattern is
# deliberately tight — narrow false-positive surface — and only flags values
# that are EXACTLY one sentinel token after `.strip()`. Real prose containing
# `<UNKNOWN>` as a substring (e.g. error messages, comments) does NOT match.
_PLACEHOLDER_RE = re.compile(r"^<[A-Z][A-Z0-9_]*>$")


def _scan_for_placeholders(value: Any, _path: str = "") -> list[tuple[str, str]]:
    """Recursive scan for placeholder values.

    Returns a list of ``(json-path, matched-value)`` tuples; empty list when
    nothing matched. Recurses into dict values and list/tuple items. Caps
    recursion depth implicitly via JSON shape (no cycles in tool_use input).
    """
    hits: list[tuple[str, str]] = []
    if isinstance(value, str):
        s = value.strip()
        if _PLACEHOLDER_RE.match(s):
            hits.append((_path or "$", s))
    elif isinstance(value, dict):
        for k, v in value.items():
            hits.extend(_scan_for_placeholders(v, f"{_path}.{k}" if _path else str(k)))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            hits.extend(_scan_for_placeholders(v, f"{_path}[{i}]"))
    return hits


def check_placeholder_args(tu, action_type: str) -> str | None:
    """Reject any tool call whose arg values look like LLM-emitted placeholder
    sentinels (e.g. ``<UNKNOWN>``, ``<TODO>``, ``<MISSING>``).

    Federal invariant **I-PARAMS-NO-PLACEHOLDER-VALUES**: when the LLM does
    not have a real value for a required field, it sometimes substitutes a
    placeholder token instead of asking the user. The downstream anti-fab
    layer catches the drift on the response side (``server did not reflect
    'email': requested '<UNKNOWN>', got None``), but by then the dispatch has
    already wasted billing tokens, polluted the audit ledger with
    ``target=<UNKNOWN>`` rows, and produced an opaque user-visible failure.
    This guard fails fast on the request side and surfaces a friendly ask
    back to the LLM so it can clarify with the user.

    Applies to **all** ``action_type`` values (read/write/destructive) —
    placeholder values are never legitimate.

    Returns
    -------
    str | None
        ``None`` to allow the dispatch through, or a human-readable rejection
        reason that the caller wraps into the standard
        ``{"RESULT": "BLOCKED", "error": ...}`` envelope. The reason is
        deliberately framed as an instruction to the LLM (not the end user)
        because the SDK chat loop feeds it back as a synthetic tool_result so
        the LLM can self-correct and emit a clarifying question.
    """
    payload = getattr(tu, "input", None)
    if not payload:
        return None
    try:
        hits = _scan_for_placeholders(payload)
    except Exception:
        # Defensive — never block on the scanner itself raising on exotic
        # payloads. Real placeholder values are str-scalar and trivially
        # serialisable; if scan blows up it is on something that cannot
        # contain a placeholder anyway.
        return None
    if not hits:
        return None
    field_list = ", ".join(f"`{f}`" for f, _ in hits[:5])
    log.warning(
        f"ChatExtension guard: PLACEHOLDER_ARGS blocked {getattr(tu, 'name', '?')} "
        f"action={action_type} fields={[f for f, _ in hits]}"
    )
    return (
        f"PLACEHOLDER_ARGS rejected: tool call '{getattr(tu, 'name', '?')}' "
        f"contains placeholder value(s) in: {field_list}. The user did not "
        f"provide concrete values for these fields and you emitted sentinel "
        f"tokens (e.g. <UNKNOWN>) instead. Do not dispatch with placeholders. "
        f"Ask the user a clarifying question to obtain the missing values, "
        f"then retry with the real data."
    )


def check_write_arg_bleed(
    tu,
    functions_called: Iterable[dict[str, Any]],
    action_type: str,
) -> str | None:
    """Reject write/destructive calls whose args contain a substring of any
    ERROR_TAXONOMY code when at least one prior tool call recorded an error
    code.

    Invariant I-WRITE-ARG-NO-BLEED — belt-and-suspenders over Task 19
    (structured error_codes) and Task 20 (tool_result hygiene). Even if an
    LLM paraphrases an error_code into prose, catch it before dispatch.

    Design notes:
    * Skips when ``action_type not in ("write", "destructive")`` — read args
      are free to echo error codes.
    * Skips when there is no prior error code — nothing to bleed from.
    * Serialises ``tu.input`` as JSON so nested dict/list values are scanned
      exhaustively.
    * Matching is case-insensitive — LLMs rephrase casing but preserve
      letter order (``validation_missing_field`` still lights up).
    * Scans the full ERROR_TAXONOMY, not just prior-this-turn codes — any
      taxonomy string appearing in a write arg is suspicious by construction.

    Federal discipline: never logs ``tu.input`` (may contain PII). Logs only
    tool name and the matched error code.

    Returns
    -------
    str | None
        ``None`` to allow, or a human-readable rejection reason to block.
        The caller (``check_guards``) wraps this into the standard
        ``{"RESULT": "BLOCKED", "error": ...}`` JSON envelope and appends
        a ``_functions_called`` audit entry.
    """
    if action_type not in ("write", "destructive"):
        return None

    # Only meaningful when there is at least one prior error code on record.
    has_prior_error_code = False
    for fc in functions_called or ():
        if fc.get("success"):
            continue
        result = fc.get("result")
        if isinstance(result, dict) and result.get("error_code"):
            has_prior_error_code = True
            break
    if not has_prior_error_code:
        return None

    # Exhaustive nested scan via JSON serialisation. Defensive fallback on
    # payloads that cannot be serialised (exotic objects) — we allow rather
    # than block, because we cannot prove a bleed on something we could not
    # serialise; failing closed here would be a DoS vector on legitimate calls.
    try:
        payload_lower = json.dumps(
            getattr(tu, "input", {}),
            ensure_ascii=False,
            default=str,
        ).lower()
    except Exception:
        return None

    # Iterating ERROR_TAXONOMY yields the 9 string keys whether it's a
    # ``dict[str, dict]`` (Task 19 shape) or a ``frozenset[str]`` (fallback).
    for code in ERROR_TAXONOMY:
        if code.lower() in payload_lower:
            log.warning(
                f"ChatExtension guard: WRITE_ARG_BLEED blocked {tu.name} "
                f"(matched error_code={code}, action={action_type})"
            )
            return (
                f"WRITE_ARG_BLEED rejected: tool call '{tu.name}' args contain "
                f"error_code substring '{code}'. The LLM appears to be paraphrasing "
                "a prior error into user-visible output. Retry without that text."
            )

    return None


def _check_target_scope_guard(
    chat_ext: ChatExtension,
    ctx,
    tu,
    action_type: str,
    confirmation_required: bool,
) -> str | None:
    """Target scope guard — blocks cross-user actions without proper scopes."""
    _caller_id = str(getattr(ctx.user, 'id', '')) if hasattr(ctx, 'user') and ctx.user else ''
    _caller_email = str(getattr(ctx.user, 'email', '')) if hasattr(ctx, 'user') and ctx.user else ''
    _caller_scopes = getattr(ctx.user, 'scopes', ['*']) if hasattr(ctx, 'user') and ctx.user else ['*']
    # v1.6.0: ``ctx.skeleton_data`` removed. Connected-email enumeration
    # now flows through ``ctx._metadata["connected_emails"]`` populated by
    # the kernel at tool-dispatch time (Phase 5 / I-CONNECTED-EMAILS-VIA-
    # METADATA). Empty list is the fail-SAFE default for legacy/dev
    # contexts — narrows target-scope authorisation, does not widen.
    _connected_emails: list = _get_connected_emails(ctx)

    _tsg = _check_target_scope(
        tool_use_params=tu.input,
        caller_id=_caller_id,
        caller_email=_caller_email,
        caller_scopes=_caller_scopes,
        intent_type=action_type,
        connected_emails=_connected_emails,
    )

    if not _tsg["allowed"]:
        log.warning(
            f"ChatExtension {chat_ext.tool_name}: TARGET_SCOPE BLOCKED "
            f"{tu.name} target={_tsg['target_user_id']}"
        )
        chat_ext._functions_called.append({
            "name": tu.name, "params": tu.input,
            "action_type": action_type, "success": False, "intercepted": False,
            "event": "", "result": None, "_target_scope": _tsg,
        })
        return json.dumps({
            "RESULT": "BLOCKED",
            "error": (
                f"Cross-user action blocked. Required scope: {_tsg['required_scope']}. "
                f"You are operating on user '{_tsg['target_user_id']}' which is not the current user."
            ),
        })

    if _tsg.get("force_confirmation") and not confirmation_required:
        log.info(
            f"ChatExtension {chat_ext.tool_name}: TARGET_SCOPE forcing "
            f"confirmation for {tu.name}"
        )
        chat_ext._functions_called.append({
            "name": tu.name, "params": tu.input,
            "action_type": action_type, "success": False, "intercepted": True,
            "event": "", "result": None, "_target_scope": _tsg,
        })
        return json.dumps({
            "RESULT": "INTERCEPTED",
            "message": (
                f"This destructive action targets another user ({_tsg['target_user_id']}). "
                "Confirmation required."
            ),
            "function": tu.name,
            "params": tu.input,
            "action_type": action_type,
        })

    return None


def _check_confirmation_guard(
    chat_ext: ChatExtension,
    ctx,
    tu,
    action_type: str,
    confirmation_required: bool,
) -> str | None:
    """2-step confirmation guard — intercepts write/destructive when confirmation enabled."""
    if not confirmation_required or action_type not in ("write", "destructive"):
        return None

    _conf_acts = getattr(ctx, "_confirmation_actions", {})
    if isinstance(_conf_acts, dict):
        _should_confirm = _conf_acts.get(action_type, False) or _conf_acts.get("all", False)
    else:
        _should_confirm = action_type in _conf_acts or "all" in _conf_acts

    if not _should_confirm:
        return None

    chat_ext._functions_called.append({
        "name": tu.name, "params": tu.input,
        "action_type": action_type, "success": False, "intercepted": True,
        "event": "", "result": None,
    })
    return json.dumps({
        "RESULT": "INTERCEPTED",
        "message": "Action requires user confirmation before execution.",
        "function": tu.name,
        "params": tu.input,
        "action_type": action_type,
    })


# ── I-AH-1 L3: empirically observed fabricated id shape rejection ─────────
# Federal anti-hallucination invariant. Closes Bug-1 from prod chat test
# 2026-05-01 02:25 UTC where LLM emitted message_id="webhostmost-outlook-1"
# / "ivalik-gmail-4" — slug shapes that don't exist in any provider's ID
# format and aren't anywhere in the codebase. Real Outlook IDs are ~150-char
# base64; real Gmail IDs are 16-char hex; UUIDs and other long opaque IDs
# pass through unchanged.

_FABRICATED_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*-[a-z][a-z0-9]*-\d+$")

# Fields whose values must be provider-native IDs, never invented.
_ID_SHAPE_FIELDS = ("message_id", "thread_id", "email_id", "msg_id")


def check_id_shape_fabrication(params: dict) -> dict | None:
    """Reject empirically observed fabricated message_id slug shapes.

    Returns ``None`` when no fabrication is detected; otherwise a dict
    matching the standard SDK error envelope:

        {"error_code": "FABRICATED_ID_SHAPE", "field": <name>,
         "value": <bad>, "hint": <self-correction guidance>}

    Federal invariant: I-AH-1.
    """
    if not isinstance(params, dict):
        return None
    for field in _ID_SHAPE_FIELDS:
        val = params.get(field)
        if isinstance(val, str) and _FABRICATED_SLUG_RE.match(val):
            return {
                "error_code": FABRICATED_ID_SHAPE,
                "field": field,
                "value": val,
                "hint": (
                    "The supplied id matches a fabrication pattern. "
                    "Real IDs come ONLY from inbox(), search(), folder(), or "
                    "the mail_inbox_summary skeleton. Call one of those first."
                ),
            }
    return None
