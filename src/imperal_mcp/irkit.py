from __future__ import annotations

from typing import Any

from imperal_sdk.ir.validator import validate_ir_dict
from imperal_sdk.ir.actions import validate_step


def _issue(rule: str, level: str, message: str) -> dict:
    return {"rule": rule, "level": level, "message": message}


def validate_ir(app_ir: dict) -> dict:
    """Full local validation: envelope structure (validate_ir_dict) + every
    declarative step (validate_step). No network. valid == no ERROR issues."""
    issues: list[dict] = [
        _issue(i.rule, i.level, i.message) for i in validate_ir_dict(app_ir)
    ]
    # Per-step validation for declarative function impls.
    for fn in (app_ir.get("app", {}) or {}).get("functions", []) or []:
        impl = fn.get("impl") or {}
        for idx, step in enumerate(impl.get("steps", []) or []):
            for msg in validate_step(step):
                issues.append(
                    _issue("STEP", "ERROR", f"{fn.get('name', '?')}[{idx}]: {msg}")
                )
    valid = not any(i["level"] == "ERROR" for i in issues)
    return {"valid": valid, "issues": issues}
