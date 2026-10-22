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
# A phone is one of the explicit shapes below, never "digits with dots and dashes": the old
# r"\+?\d[\d\s\-().]{7,}\d" masked IPv4 addresses (104.224.88.155), versions (3.11.15),
# ISO dates (2026-10-12) and port ranges (8000-8080) as <PHONE> (tests/test_mask_pii.py).
# Matches:
# 1) International format with +: e.g. +1 (555) 123-4567, +49 30 123456, +380 99 123 4567
# 2) National format with area code in parens: (555) 123-4567
# 3) US dot-delimited phone: 123.456.7890 (strictly 3.3.4 digits, never 4 octets like IP)
# 4) Standard 10-11 digit phone with spaces/dashes (min 10 digits total)
_PHONE_PATTERN = (
    r"(?:"
    r"\+\d{1,3}[\s\-()]*(?:\d[\s\-()]*){6,13}\d|"  # +Country ...
    r"\(\d{2,4}\)[\s\-]*(?:\d[\s\-]*){6,10}\d|"     # (Area) ...
    r"\b\d{3}\.\d{3}\.\d{4}\b|"                     # 123.456.7890 (strict US 3.3.4 format)
    r"\b(?:\+?1[- ]?)?[1-9]\d{2}[- ]\d{3}[- ]\d{4}\b|" # 555-123-4567 or 1-555-123-4567
    r"\b0\d{1,3}[- ]\d{2,3}[- ]\d{2,4}(?:[- ]\d{2,4})?\b" # National formats (e.g. 099-123-45-67, 044-123-4567)
    r")"
)
_PHONE_RE = re.compile(_PHONE_PATTERN)
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
    masked = _PHONE_RE.sub("<PHONE>", masked)
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
