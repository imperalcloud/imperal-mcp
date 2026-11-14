# Port of the gateway app/util/pii.py (SOURCE OF TRUTH: imperal_kernel/audit/_pii.py).
# Keep regexes + ALLOWLIST_KEYS IN SYNC with the gateway/kernel — drift hazard.
from __future__ import annotations

import re
from enum import Enum
from typing import Any


class PIIRedactionLevel(str, Enum):
    NONE = "none"
    MASK_PII = "mask_pii"
    FULL_REDACT = "full_redact"


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A phone is anything number-like (the broad matcher: international, national, dotted, bare digit
# runs), MINUS the shapes that are certainly not a phone. Those used to be masked too -- IPv4
# addresses (104.224.88.155, with a port), versions (3.11.15), ISO dates (2026-10-12), port
# ranges (8000-8080). An explicit list of phone shapes instead would let unformatted and foreign
# numbers through (380991234567, 030 12345678): when unsure, mask. tests/test_mask_pii.py.
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_NOT_A_PHONE = re.compile(
    r"(?:\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?"   # IPv4, optionally with a port
    r"|\d+(?:\.\d+){1,3}"                       # version / dotted number (not 3.3.4 phone below)
    r"|\d{4}-\d{2}-\d{2}"                        # ISO date
    r"|\d{2,5}-\d{2,5})"                         # port range
)
_US_DOTTED_PHONE = re.compile(r"\d{3}\.\d{3}\.\d{4}")
_CELL_GAP = re.compile(r" {2,}|\t|\n")      # columns of a table (two spaces or more, a tab, a line): never one number
# a date-time stamp ("20261025-094552", "20261025T094552" -- a release directory's name) is neither phone nor card
# only the separated shape (date, -/_/T, time) -- a bare or grouped number keeps every card check (security review)
_STAMP = re.compile(r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[-_T](?:[01]\d|2[0-3])[0-5]\d[0-5]\d")


def _separate_numbers(text: str, rx: "re.Pattern[str]", judge) -> "str | None":
    """Numbers of six digits or more side by side ("3846252 3846258": two process ids) are separate numbers, each judged
    on its own -- None when ``text`` is not that (live 2026-11-14: `kill 3846252 3846258` reached the kernel as
    `kill <CARD>`, then `kill <PHONE>`). A phone or card number is written in shorter groups (+1 415 555 2671, 4111 1111
    1111 1111) or unbroken, so it is still masked."""
    words = text.split(" ")
    if len(words) < 2 or not all(w.isdigit() and len(w) >= 6 for w in words):
        return None
    return " ".join(rx.sub(judge, w) for w in words)


def _phone_or_keep(m: "re.Match[str]") -> str:
    """<PHONE> unless every whitespace-separated piece of the match is a certain non-phone."""
    cells = _CELL_GAP.split(m.group(0))
    if len(cells) > 1:
        # a table's columns (`ps`: "3846258       00:55"), never one number (live 2026-11-14: a PID reached the kernel
        # as <PHONE> and the final's check said no output showed it): each cell is judged on its own
        gaps = _CELL_GAP.findall(m.group(0))
        return _PHONE_RE.sub(_phone_or_keep, cells[0]) + "".join(
            gap + _PHONE_RE.sub(_phone_or_keep, cell) for gap, cell in zip(gaps, cells[1:]))
    apart = _separate_numbers(m.group(0), _PHONE_RE, _phone_or_keep)
    if apart is not None:
        return apart
    pieces = m.group(0).split()
    if _STAMP.fullmatch(m.group(0).strip()) or pieces and all(
            _NOT_A_PHONE.fullmatch(p) and not _US_DOTTED_PHONE.fullmatch(p) for p in pieces):
        return m.group(0)
    return "<PHONE>"


_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
# a date-time ("2026-11-07 12:15:12", git %ci, every log line) and a hex id with a letter (a commit "573a3a63") are
# never a phone: live 2026-11-07 "573a3a63 2026-11-07 12:15:12" reached the kernel as "573a3a<PHONE>:15:12" -- every
# git date of a session lost, and the kernel's claim check called a commit time the agent truly read invented
_NEVER_PII_RE = re.compile(r"\b(?:19|20)\d\d-[01]\d-[0-3]\d[ T][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?\b"
                           r"|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# every 13-19 digit run is masked (fail-closed: this is the client's own layer, the gateway checks again) -- except
# the exact date-time stamp shape: "rel-20261025-094552" went into the vault as "rel-<CARD>" (live 2026-10-25)
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _card_or_keep(m: "re.Match[str]") -> str:
    if _STAMP.fullmatch(m.group(0).strip(" -")):
        return m.group(0)
    core = m.group(0).rstrip(" -")
    tail = m.group(0)[len(core):]        # the separator after the number is the text's, never the card's
    apart = _separate_numbers(core, _CC_RE, _card_or_keep)
    return ("<CARD>" if apart is None else apart) + tail


ALLOWLIST_KEYS = frozenset({
    "id", "app_id", "imperal_id", "user_id", "tenant_id", "owner_id",
    "developer_id", "agency_id", "commit_sha", "sha", "version",
    "created_at", "updated_at", "timestamp", "ts",
    "request_id", "trace_id", "message_id", "task_id",
})


def apply_pii_redaction(text: str | None, level: PIIRedactionLevel) -> str | None:
    if text is None:
        return None
    if not text:
        return text
    if level == PIIRedactionLevel.NONE:
        return text
    if level == PIIRedactionLevel.FULL_REDACT:
        return "<redacted>"
    # a UUID is a structural id, never PII: shielded before the digit passes, as the kernel's _pii does (live 10-26: a
    # panel connection id came into the frame as "ssh:0f09e3ed-78eb-4c<PHONE>e4e1254bd84" -- a second, broken target)
    ids: list[str] = []

    def _shield(m: "re.Match[str]") -> str:
        ids.append(m.group(0))
        return f"\x00UUID{len(ids) - 1}\x00"
    masked = _NEVER_PII_RE.sub(_shield, _UUID_RE.sub(_shield, text))
    masked = _SSN_RE.sub("<SSN>", masked)
    masked = _CC_RE.sub(_card_or_keep, masked)
    masked = _EMAIL_RE.sub("<EMAIL>", masked)
    masked = _PHONE_RE.sub(_phone_or_keep, masked)
    return re.sub(r"\x00UUID(\d+)\x00", lambda m: ids[int(m.group(1))], masked) if ids else masked


def mask_pii_in_obj(obj: Any, level: PIIRedactionLevel = PIIRedactionLevel.MASK_PII) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and k in ALLOWLIST_KEYS:
                out[k] = v
            else:
                out[k] = mask_pii_in_obj(v, level)
        return out
    if isinstance(obj, list):
        return [mask_pii_in_obj(v, level) for v in obj]
    if isinstance(obj, str):
        return apply_pii_redaction(obj, level)
    return obj


# Back-compat alias — server.py applies the masker via this name on every read egress.
defensive_scrub = mask_pii_in_obj
