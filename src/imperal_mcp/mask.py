# Verbatim port of the gateway app/util/pii.py (SOURCE OF TRUTH: imperal_kernel/audit/_pii.py).
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


def _phone_or_keep(m: "re.Match[str]") -> str:
    """<PHONE> unless every whitespace-separated piece of the match is a certain non-phone."""
    pieces = m.group(0).split()
    if pieces and all(_NOT_A_PHONE.fullmatch(p) and not _US_DOTTED_PHONE.fullmatch(p) for p in pieces):
        return m.group(0)
    return "<PHONE>"


_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

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
    masked = _SSN_RE.sub("<SSN>", text)
    masked = _CC_RE.sub("<CARD>", masked)
    masked = _EMAIL_RE.sub("<EMAIL>", masked)
    masked = _PHONE_RE.sub(_phone_or_keep, masked)
    return masked


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
