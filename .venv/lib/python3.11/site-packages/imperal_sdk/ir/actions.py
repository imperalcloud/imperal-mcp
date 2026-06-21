# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Per-verb declarative step JSON Schemas + pure-Python validate_step.

Design note — no jsonschema at runtime:
  ``jsonschema`` is a *dev* dependency (tests/contract only). This module
  implements a lightweight pure-Python validator that covers the subset of
  JSON Schema features the action schemas actually use:
    - top-level ``type: object``
    - ``required`` key list
    - ``properties`` type checks (string, integer, number, boolean, object, array, null)
  All other keywords (``$schema``, ``$id``, ``title``, ``description``,
  ``additionalProperties``, ``items``) are ignored — they are metadata for
  tooling (e.g. jsonschema in contract tests) and editors.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any

# ---------------------------------------------------------------------------
# Canonical verb list — every declarative step op must appear here.
# ---------------------------------------------------------------------------

_VERBS: list[str] = [
    "call",
    "navigate",
    "send",
    "open",
    "store.get",
    "store.list",
    "store.create",
    "store.update",
    "store.delete",
    "ai.complete",
    "conditional",
]

# Mapping from verb to the schema filename stem (dots → underscores).
_VERB_TO_FILE: dict[str, str] = {v: v.replace(".", "_") for v in _VERBS}


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load_schema(verb: str) -> dict:
    fname = _VERB_TO_FILE[verb] + ".json"
    text = (
        resources.files("imperal_sdk.schemas.actions")
        .joinpath(fname)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


# Eagerly load all schemas at import time — errors surface early.
ACTION_SCHEMAS: dict[str, dict] = {v: _load_schema(v) for v in _VERBS}


# ---------------------------------------------------------------------------
# Lightweight pure-Python validator (no jsonschema import)
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type | tuple] = {
    "string":  str,
    "boolean": bool,
    "object":  dict,
    "array":   list,
    "number":  (int, float),
    "integer": int,
    "null":    type(None),
}


def _type_ok(value: Any, type_name: str) -> bool:
    """Return True iff *value* matches the JSON Schema primitive *type_name*."""
    py_type = _TYPE_MAP.get(type_name)
    if py_type is None:
        return True  # unknown type — permissive
    # JSON Schema: booleans are NOT integers / numbers even though bool subclasses int
    if type_name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


# A whole-match binding-DSL token ({{ path.to.value }}) resolves at runtime to
# the raw referenced object (any type), so its static type is unknowable here.
# Mirrors runtime/template.py:_WHOLE. Interpolated strings ("...{{x}}...") are
# NOT whole-match — they always resolve to str and still type-check as string.
_WHOLE_BINDING = re.compile(r"^\s*\{\{\s*[\w.]+\s*\}\}\s*$")


def _validate_object(value: Any, schema: dict) -> list[str]:
    """Validate *value* against a ``type:object`` schema fragment.

    Covers: required key list, per-property type checks.
    Returns a list of human-readable error strings (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(value, dict):
        return [f"expected object, got {type(value).__name__}"]

    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"missing required property '{key}'")

    for prop_name, prop_schema in schema.get("properties", {}).items():
        if prop_name not in value:
            continue
        val = value[prop_name]
        # Deferred binding-DSL value — type resolved at runtime; accept statically.
        if isinstance(val, str) and _WHOLE_BINDING.match(val):
            continue
        prop_type = prop_schema.get("type")
        if prop_type is not None and not _type_ok(val, prop_type):
            errors.append(
                f"'{prop_name}': expected {prop_type}, "
                f"got {type(val).__name__}"
            )

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_step(step: dict) -> list[str]:
    """Validate a single declarative step dict against its verb's arg schema.

    Args:
        step: A declarative step mapping — must contain at least ``op`` and
              ``args`` keys (or, for ``conditional``, ``if``/``then``/``else``
              at the step root).

    Returns:
        Empty list when the step is valid; list of human-readable error
        strings otherwise. Never raises.
    """
    op = step.get("op")
    if op not in ACTION_SCHEMAS:
        return [f"unknown op {op!r}; valid verbs: {sorted(ACTION_SCHEMAS)}"]

    if op == "conditional":
        # conditional is pure control-flow — its fields (if/then/else) live at
        # the step ROOT, not under args. Validate the step dict itself.
        return _validate_object(step, ACTION_SCHEMAS["conditional"])

    args = step.get("args", {})
    return _validate_object(args, ACTION_SCHEMAS[op])
