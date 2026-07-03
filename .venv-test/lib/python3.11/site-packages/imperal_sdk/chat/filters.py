# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Output filtering pipeline for ChatExtension responses.

Enforces OS identity, response style, Markdown hygiene, and tool result
size limits. Public functions are called by the kernel's typed-dispatch
layer after each extension function invocation.
"""
from __future__ import annotations
import json
import logging

log = logging.getLogger(__name__)


# ── OS Identity ───────────────────────────────────────────────────────────

# Redirect patterns — LLM tells user to "go to another extension"
_REDIRECT_PATTERNS = (
    "gmail extension", "notes extension", "admin extension",
    "sharelock extension", "mail extension", "case extension",
    "gmail app", "notes app", "another extension", "other extension",
    "separate extension", "different extension",
    "другое расширение", "другом расширении",
)

# Self-identification patterns — LLM says "I am the X assistant"
_SELF_ID_PATTERNS = (
    "i'm the notes", "i am the notes", "i'm a notes",
    "i'm the mail", "i am the mail", "i'm a mail",
    "i'm the admin", "i am the admin", "i'm an admin",
    "i'm the sql", "i am the sql", "i'm a sql", "i am a sql",
    "i'm the database", "i am the database", "i'm a database",
    "i'm the developer", "i am the developer",
    "i'm the web", "i am the web",
    "i'm the microsoft", "i am the microsoft",
    "i'm the automation", "i am the automation", "i'm an automation",
    "i'm the billing", "i am the billing",
    "as the notes assistant", "as a notes assistant",
    "as the mail client", "as a mail client",
    "as the admin assistant", "as an admin assistant",
    "as the sql assistant", "as a sql assistant",
    "as the database assistant", "as a database assistant",
    "as the developer assistant", "as a developer assistant",
    "as your notes", "as your mail", "as your admin",
    "as your sql", "as your database", "as your developer",
    "я — ассистент", "я ассистент заметок", "я почтовый",
    "я админ-ассистент", "я помощник по заметкам",
    "я помощник по почте", "я помощник базы данных",
)

_ALL_IDENTITY_PATTERNS = _REDIRECT_PATTERNS + _SELF_ID_PATTERNS


def enforce_os_identity(text: str) -> str:
    """Kernel-level OS identity enforcement.

    Removes any sentences where the LLM:
    1. Redirects user to other extensions
    2. Identifies itself as a specific extension/app/assistant
    Extensions are internal implementation — user sees only Imperal Cloud / Webbee.
    """
    if not text:
        return text

    text_lower = text.lower()
    has_identity_leak = any(p in text_lower for p in _ALL_IDENTITY_PATTERNS)
    if not has_identity_leak:
        return text

    # Remove offending sentences
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    cleaned = []
    any_stripped = False
    for s in sentences:
        s_lower = s.lower()
        if any(p in s_lower for p in _ALL_IDENTITY_PATTERNS):
            log.info(f"OS Identity: stripped sentence: {s[:80]}")
            any_stripped = True
            continue
        cleaned.append(s)

    result = " ".join(cleaned).strip()
    if result:
        return result
    # All content was identity leaks (single-sentence or all-leak response).
    # Never return the leak verbatim — fall back to neutral acknowledgement.
    # Russian fallback when original text contained Cyrillic, else English.
    if any_stripped:
        has_cyrillic = any('\u0400' <= ch <= '\u04FF' for ch in text)
        return "Чем могу помочь?" if has_cyrillic else "How can I help?"
    return text


# ── Response Style ────────────────────────────────────────────────────────

_FILLER_PHRASES = (
    "дайте знать", "let me know", "feel free to",
    "если вы хотите", "if you want to", "if you need",
    "ваши данные", "your data", "остаются сохранен",
    "в любой момент", "at any time", "anytime",
    "вы сможете снова", "you can re-enable", "you can always",
    "могу ещё чем-то помочь", "anything else",
    "что-то ещё", "чем-то помочь", "нужна ли", "нужно ли",
)


def enforce_response_style(text: str) -> str:
    """Kernel-level response style enforcement. CODE, not prompt.

    1. Strips Unicode emojis (no extension should use them)
    2. Strips known filler/reassurance phrases
    3. Collapses excessive whitespace
    """
    if not text:
        return text
    import re
    # 1. Strip emojis (Unicode emoji ranges, expanded to catch keycaps and misc)
    text = re.sub(
        r'[\U0001F300-\U0001F9FF\u2600-\u27BF\uFE00-\uFE0F'
        r'\u200D\u2702-\u27B0\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF'
        r'\u2B50\u26A0\u2B06\u2194-\u21AA'
        r'\u20E3\u2139\u2328\u23CF\u23E9-\u23F3\u23F8-\u23FA'
        r'\U000E0020-\U000E007F\u200B-\u200F\u2028-\u202F'
        r'\u2066-\u2069\uFFFC\uFFFD]+', '', text
    )
    # Also strip keycap sequences: digit + U+FE0F + U+20E3 (e.g. 1️⃣)
    text = re.sub(r'[\d#*]\uFE0F?\u20E3', '', text)
    # 2. Strip known filler phrases (case-insensitive line removal)
    lines = text.split("\n")
    non_empty_lines = [line for line in lines if line.strip()]
    # Only strip filler if there are OTHER non-filler lines to keep.
    # Never strip ALL lines — that results in empty response.
    cleaned = []
    for line in lines:
        line_lower = line.strip().lower()
        if not line_lower:
            cleaned.append(line)
            continue
        if any(f in line_lower for f in _FILLER_PHRASES):
            # Check: would removing this leave us with zero content?
            remaining = [
                l for l in non_empty_lines
                if l.strip().lower() != line_lower
                and not any(f in l.strip().lower() for f in _FILLER_PHRASES)
            ]
            if remaining:
                log.info(f"Response style: stripped filler: {line.strip()[:80]}")
                continue
            # else: this is the only meaningful line, keep it
        cleaned.append(line)
    text = "\n".join(cleaned)
    # 3. Collapse excessive blank lines (max 1)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Markdown Normalizer (Layer 2 of MD rendering hygiene, 2026-04-21) ───

_BOLD_WS_FIX = None  # lazily compiled on first call


def normalize_markdown(text: str) -> str:
    """Fix common LLM-emitted Markdown glitches that break the Panel renderer.

    Current fixes (regex-only, idempotent, safe to call multiple times):
      1. Whitespace inside bold markers — ``** text **`` / ``** text**`` /
         ``**text **`` → ``**text**``. CommonMark requires the ``**``
         emphasis run to have no leading/trailing whitespace inside;
         otherwise markers render as literal characters.

    Layer 1 (prompt ``kernel_formatting_rule.txt``) teaches the LLM to
    emit correct markup up-front; this layer cleans up residual glitches
    when the model slips. Every LLM output on the chat delivery path
    passes through here.

    Pure function, no state, idempotent. ``normalize_markdown(
    normalize_markdown(x)) == normalize_markdown(x)``.

    Edge cases:
      - Empty bold (``** **``) collapses to empty string.
      - Bolds with internal single-spaces between words (``**a b c**``)
        are preserved verbatim — only leading/trailing whitespace trimmed.
      - Nested markers and code spans inside bold are not unwrapped.
    """
    if not text or "**" not in text:
        return text
    import re
    global _BOLD_WS_FIX
    if _BOLD_WS_FIX is None:
        # Lazy match content between ** markers, no embedded * or newline.
        _BOLD_WS_FIX = re.compile(r"\*\*([^*\n]*?)\*\*")

    def _trim(m):
        inner = m.group(1).strip()
        if not inner:
            return ""
        return "**" + inner + "**"

    return _BOLD_WS_FIX.sub(_trim, text)


# ── Tool Result Trimmer ───────────────────────────────────────────────────

_KEEP_FIELDS = frozenset({
    "id", "message_id", "thread_id", "note_id", "from", "to", "cc", "bcc",
    "subject", "name", "email", "status", "RESULT", "error",
    "success", "sent", "archived", "deleted", "folder", "account",
    "note_id", "folder_id", "tag", "tags",
})
_TRIM_FIELDS = frozenset({
    "body", "content", "text", "html", "snippet", "preview",
    "description", "analysis", "summary", "message", "plain",
})


def _truncate_deep(obj, list_max: int = 5, str_max: int = 500):
    """Recursively truncate lists and long string fields. Private — used only by trim_tool_result."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        if len(obj) > list_max:
            trimmed = [_truncate_deep(item, list_max, str_max) for item in obj[:list_max]]
            trimmed.append(f"[...{len(obj) - list_max} more items]")
            return trimmed
        return [_truncate_deep(item, list_max, str_max) for item in obj]
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k in _KEEP_FIELDS:
                result[k] = v
            elif k in _TRIM_FIELDS and isinstance(v, str) and len(v) > str_max:
                result[k] = v[:str_max] + f"... [{len(v)} chars total]"
            else:
                result[k] = _truncate_deep(v, list_max, str_max)
        return result
    return obj


def trim_tool_result(content: str, max_tokens: int = 3000,
                     list_max: int = 5, str_max: int = 500) -> str:
    """Trim oversized tool result content to fit within token budget.

    Attempts to parse as JSON and truncate intelligently; falls back to
    hard character truncation for non-JSON content.
    """
    estimated_tokens = len(content) / 3
    if estimated_tokens <= max_tokens:
        return content
    max_chars = max_tokens * 3
    try:
        data = json.loads(content)
        trimmed = _truncate_deep(data, list_max, str_max)
        result = json.dumps(trimmed, ensure_ascii=False)
        if len(result) > max_chars:
            return result[:max_chars] + f"\n[...truncated, {len(content)} chars total]"
        return result
    except (json.JSONDecodeError, TypeError):
        pass
    return content[:max_chars] + f"\n[...truncated, {len(content)} chars total]"
