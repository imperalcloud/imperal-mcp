from __future__ import annotations

import re
from typing import Any

# Structural ids that must survive masking (mirror the gateway ALLOWLIST_KEYS).
_ALLOWLIST_KEYS = {"id", "app_id", "imperal_id", "user_id", "tenant_id", "developer_id"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def _scrub_str(s: str) -> str:
    s = _EMAIL.sub("[redacted-email]", s)
    s = _PHONE.sub("[redacted-phone]", s)
    return s


def defensive_scrub(obj: Any) -> Any:
    """Minimal client-side defense-in-depth scrub (the gateway is the authority)."""
    if isinstance(obj, str):
        return _scrub_str(obj)
    if isinstance(obj, list):
        return [defensive_scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {
            k: (v if k in _ALLOWLIST_KEYS else defensive_scrub(v))
            for k, v in obj.items()
        }
    return obj
