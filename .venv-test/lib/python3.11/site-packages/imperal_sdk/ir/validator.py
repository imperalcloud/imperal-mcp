# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""IR envelope validator.

``validate_ir_dict`` validates a raw IR envelope dict against the ``IREnvelope``
Pydantic schema and returns a list of :class:`~imperal_sdk.validator.ValidationIssue`
objects. It **never raises** — callers always receive a list (empty = valid).
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..validator import ValidationIssue
from .schema import IREnvelope


def validate_ir_dict(data: Any) -> list[ValidationIssue]:
    """Validate an IR envelope dict. Returns a list of issues (never raises).

    Note: validates ENVELOPE STRUCTURE only (Pydantic). Does NOT deep-validate
    declarative ``steps[]`` args — per-verb step validation is a separate check
    performed by :func:`~imperal_sdk.ir.actions.validate_step`.

    Args:
        data: Any value. Must be a ``dict`` shaped as an :class:`IREnvelope`.

    Returns:
        ``[]`` when the IR is structurally valid; one
        :class:`~imperal_sdk.validator.ValidationIssue` per problem otherwise.
        Level is always ``"ERROR"`` — IR issues are fatal (the kernel cannot
        execute a malformed envelope).
    """
    if not isinstance(data, dict):
        return [ValidationIssue(rule="IR0", level="ERROR",
                                message="IR root must be an object")]
    try:
        IREnvelope.model_validate(data)
    except ValidationError as exc:
        issues: list[ValidationIssue] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            issues.append(ValidationIssue(
                rule="IR1",
                level="ERROR",
                message=f"{loc}: {err.get('msg', 'invalid')}",
            ))
        return issues
    return []
