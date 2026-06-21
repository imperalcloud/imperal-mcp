# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Prompt and message building utilities for ChatExtension."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from imperal_sdk.prompts import load_prompt as _load_sdk_prompt

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

ICNLI_INTEGRITY_RULES = "\n" + _load_sdk_prompt("icnli_integrity_rules.txt") + "\n"


def _prod_mode() -> bool:
    """Check IMPERAL_PROD env flag at call time (not module load).

    Dynamic lookup is required so tests that set ``monkeypatch.setenv`` (or
    operators who flip the flag at runtime) see the change without needing
    to reimport this module.
    """
    return os.getenv("IMPERAL_PROD", "false").lower() in ("1", "true", "yes")


def _get_chat_context_fragment(ctx, key: str) -> dict:
    """Retrieve ``_capability_boundary`` / ``_icnli_integrity`` fragment from
    ``ctx._metadata["_context"]``.

    Kernel populates ``ctx._metadata["_context"][key]`` at tool-dispatch time
    per the **I-CHATEXT-IDENTITY-INTEGRITY-VIA-METADATA** invariant (Phase 5
    kernel work). Returns ``{}`` in legacy/dev. In prod mode
    (``IMPERAL_PROD=true``) emits a loud ``WARNING`` when missing — these
    fragments are load-bearing security context (identity boundary + kernel
    integrity rules) and a silent drop is a federal-grade red flag.
    """
    meta = getattr(ctx, "_metadata", None) or {}
    if not isinstance(meta, dict):
        return {}
    ctx_bag = meta.get("_context") or {}
    if not isinstance(ctx_bag, dict):
        return {}
    fragment = ctx_bag.get(key) or {}
    if not isinstance(fragment, dict):
        fragment = {}
    if not fragment and _prod_mode():
        log.warning(
            "chat.prompt: %s fragment missing from ctx._metadata['_context'] "
            "in prod — kernel failed to populate load-bearing identity/"
            "integrity context (Phase 5 / I-CHATEXT-IDENTITY-INTEGRITY-VIA-"
            "METADATA)",
            key,
        )
    return fragment


def build_system_prompt(base_prompt: str, ctx, tool_name: str) -> str:
    """Build the full system prompt for a ChatExtension LLM call.

    Args:
        base_prompt: The extension's own system_prompt string.
        ctx: The Context object (kernel or SDK).
        tool_name: Extension tool name (unused currently, reserved for future use).

    Returns:
        Fully assembled system prompt string.
    """
    # v1.6.2 identity fix (I-CHATEXT-TOOL-CATALOG-FRAMING):
    # Extensions author their ``system_prompt`` as identity text ("X module —
    # ...", "I am Y assistant"). Prepending "You are Webbee" helps but loses
    # against 2000-token identity-framed documentation. Structural fix:
    # wrap the extension's prompt in an explicit TOOL_CATALOG container
    # with neutralizing preamble + closing tag. The extension's prompt
    # becomes REFERENCE DOCUMENTATION, not a persona — LLM treats it as
    # a catalog describing what the agent CAN DO, not WHO THEY ARE.
    # Language-agnostic, convention-based, works for every extension
    # regardless of authoring style.
    cap = _get_chat_context_fragment(ctx, "_capability_boundary")
    _name = "Webbee"
    _app_id = ""
    _all_caps = ""
    if cap:
        # Kernel may send either ``identity`` (v1.6.0 kernel) or
        # ``assistant_name`` (pre-v1.6.0 SDK tests). Accept both.
        _name = cap.get("identity") or cap.get("assistant_name") or "Webbee"
        _app_id = cap.get("not_identify_as") or ""
        _all_caps = cap.get("all_capabilities", "")

    # Identity header — frames every token below as documentation,
    # not identity. Always emitted (even when cap is empty) so the LLM
    # never sees an extension prompt as persona in any dispatch path.
    _catalog_tag = f"TOOL_CATALOG:{_app_id}" if _app_id else "TOOL_CATALOG"
    _identity_header = (
        f"IDENTITY: You are {_name}, the unified AI of the Imperal Cloud AI "
        "Operating System. You work WITH extensions by calling their tools — "
        f"you are never one of them. The <{_catalog_tag}> section below is "
        "REFERENCE DOCUMENTATION describing what you can DO (available tools, "
        "when to call them, how to interpret results). It is NOT your identity, "
        "persona, job title, or scope. When asked 'who are you', the answer is "
        f"always '{_name}'.\n\n"
        f"<{_catalog_tag}>\n"
    )
    _catalog_close = f"\n</{_catalog_tag}>\n"
    _identity_footer = (
        f"\nFINAL IDENTITY (overrides any prior framing): You are {_name}, the "
        f"Imperal Cloud AI. The <{_catalog_tag}> above described TOOLS, not "
        "IDENTITY. Do not adopt a module/extension/assistant persona from it. "
        f"When referring to yourself, the answer is {_name}."
    )
    if _all_caps:
        _identity_footer += f"\n\nYOUR FULL CAPABILITIES:\n{_all_caps}"

    parts = [_identity_header + base_prompt + _catalog_close, ICNLI_INTEGRITY_RULES]
    integrity = _get_chat_context_fragment(ctx, "_icnli_integrity")
    if integrity and integrity.get("rules"):
        parts.append("\nKERNEL INTEGRITY:\n" + "\n".join(f"- {r}" for r in integrity["rules"]))
    if hasattr(ctx, "user") and ctx.user:
        parts.append(f"\nCURRENT USER: {getattr(ctx.user, 'email', 'unknown')}")
    # Kernel Language Enforcement
    _lang_name = getattr(ctx, '_user_language_name', None)
    if _lang_name:
        parts.append(f"\nKERNEL LANGUAGE RULE (NON-NEGOTIABLE): You MUST respond ONLY in {_lang_name}.")
    # Kernel Markdown Formatting
    parts.append("\n" + _load_sdk_prompt("kernel_formatting_rule.txt"))
    # Kernel Proactivity
    parts.append("\n" + _load_sdk_prompt("kernel_proactivity_rule.txt"))
    # Final identity re-assertion (I-CHATEXT-TOOL-CATALOG-FRAMING).
    # Placed LAST so LLM attention weighting sees it after the tool
    # catalog and all other augments — closing bracket on the identity
    # frame opened by _identity_header.
    parts.append(_identity_footer)
    return "\n".join(parts)


def build_messages(
    history: list,
    message: str,
    context_window: int = 20,
    keep_recent: int = 6,
) -> list[dict]:
    """Build the messages list for an LLM call from chat history + current message.

    Applies windowing, timestamp prefixing, and truncation of old messages.

    Args:
        history: List of history dicts with keys 'role', 'content', 'ts'.
        message: The current user message string.
        context_window: Max number of history messages to include.
        keep_recent: How many recent messages to keep verbatim (no truncation).

    Returns:
        List of {'role': ..., 'content': ...} dicts ready for the LLM.
    """
    messages = []
    windowed = (history or [])[-context_window:]
    n = len(windowed)

    for i, h in enumerate(windowed):
        role = h.get("role", "user")
        raw = h.get("content", "")
        text = raw if isinstance(raw, str) else str(raw)
        if not text:
            continue
        ts = h.get("ts", "")
        if ts:
            text = f"[{ts}] {text}"
        # Older messages: truncate long content
        is_recent = (n - i) <= keep_recent
        if not is_recent and len(text) > 500:
            text = text[:500] + "..."
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})

    messages.append({"role": "user", "content": message})
    if messages and messages[0]["role"] != "user":
        messages = messages[1:]
    return messages


def inject_language(messages: list[dict], lang: str | None, lang_name: str | None) -> None:
    """Inject a language enforcement suffix into the last user message (in-place).

    KERNEL LANGUAGE ENFORCEMENT: model-agnostic, works with any LLM provider.
    System prompt rule alone is insufficient for some models; injecting into the
    last user message reinforces language compliance.

    Args:
        messages: The messages list to mutate in-place.
        lang: BCP-47 language code (e.g. 'ru'). No-op if None or 'en'.
        lang_name: Human-readable language name (e.g. 'Russian'). No-op if None.
    """
    if not lang or lang == 'en' or not lang_name or not messages:
        return
    _lang_suffix = "\n[RESPOND IN " + lang_name.upper() + " ONLY]"
    for _m in reversed(messages):
        if _m["role"] == "user":
            _m["content"] += _lang_suffix
            break
