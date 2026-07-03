# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Typed binding-point schemas for free-dict UI children.

``validate_child(kind, value)`` validates the ``list[dict]`` fields that the
Imperal Panel renderer interprets directly (e.g. ``Tabs.tabs``,
``Accordion.sections``) against their JSON Schemas.

Design note — no jsonschema runtime dependency:
  ``jsonschema`` is a *dev* dependency in this SDK (used in tests/contract only).
  Adding it to runtime ``[project.dependencies]`` would force every extension
  deployer to install a heavy optional package. Instead this module implements a
  lightweight pure-Python validator that covers the subset of JSON Schema
  features the ui_children schemas actually use:
    - top-level ``type: array``
    - per-item ``required`` key list + ``properties`` type checks (str/bool/object)
    - ``if/then/else`` for the menu separator special-case
  All other keywords (``additionalProperties``, ``$schema``, ``$id``, ``title``,
  ``description``) are intentionally ignored — they are metadata for tooling.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _schema(kind: str) -> dict | None:
    """Load and cache a ui_children JSON Schema by kind name.

    Returns ``None`` when no schema file exists for *kind*.
    """
    try:
        text = (
            resources.files("imperal_sdk.schemas.ui_children")
            .joinpath(f"{kind}.json")
            .read_text(encoding="utf-8")
        )
        return json.loads(text)
    except (FileNotFoundError, ModuleNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Lightweight validator
# ---------------------------------------------------------------------------

def _type_ok(value: Any, type_name: str) -> bool:
    """Return True iff ``value`` matches the JSON Schema primitive ``type_name``."""
    mapping = {
        "string": str,
        "boolean": bool,
        "object": dict,
        "array": list,
        "number": (int, float),
        "integer": int,
        "null": type(None),
    }
    py_type = mapping.get(type_name)
    if py_type is None:
        return True  # unknown type — permissive
    # JSON Schema: booleans are NOT integers even though bool subclasses int
    if type_name == "integer" and isinstance(value, bool):
        return False
    if type_name == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


def _check_item(item: Any, item_schema: dict, index: int) -> list[str]:
    """Validate a single array item against *item_schema*. Returns error strings."""
    errors: list[str] = []

    if not isinstance(item, dict):
        errors.append(f"item[{index}]: expected object, got {type(item).__name__}")
        return errors

    # Resolve if/then/else before required/properties checks
    effective_schema = dict(item_schema)
    if_schema = item_schema.get("if")
    then_schema = item_schema.get("then", {})
    else_schema = item_schema.get("else", {})
    if if_schema is not None:
        branch_errors = _check_item_against(item, if_schema, index)
        overlay = then_schema if not branch_errors else else_schema
        # Merge overlay into effective_schema (overlay wins on conflict)
        required_base = list(effective_schema.get("required", []))
        required_overlay = list(overlay.get("required", []))
        # Union required lists (keep all from base + overlay)
        effective_schema["required"] = list(dict.fromkeys(required_base + required_overlay))
        props_base = dict(effective_schema.get("properties", {}))
        props_overlay = dict(overlay.get("properties", {}))
        props_base.update(props_overlay)
        effective_schema["properties"] = props_base

    errors.extend(_check_item_against(item, effective_schema, index))
    return errors


def _check_item_against(item: dict, schema: dict, index: int) -> list[str]:
    """Apply required + properties type checks from *schema* to *item*."""
    errors: list[str] = []

    # required keys
    for key in schema.get("required", []):
        if key not in item:
            errors.append(f"item[{index}]: missing required key '{key}'")

    # per-property type checks
    for prop_name, prop_schema in schema.get("properties", {}).items():
        if prop_name not in item:
            continue  # not present — not required here (already checked above)
        prop_type = prop_schema.get("type")
        prop_const = prop_schema.get("const")
        if prop_type is not None and not _type_ok(item[prop_name], prop_type):
            errors.append(
                f"item[{index}].{prop_name}: expected {prop_type}, "
                f"got {type(item[prop_name]).__name__}"
            )
        if prop_const is not None and item[prop_name] != prop_const:
            errors.append(
                f"item[{index}].{prop_name}: expected const {prop_const!r}, "
                f"got {item[prop_name]!r}"
            )

    return errors


def validate_child(kind: str, value: Any) -> list[str]:
    """Validate a free-dict UI child list against its typed schema.

    Args:
        kind:  Child kind identifier — one of ``tabs``, ``accordion``,
               ``datatable_columns``, ``datatable_rows``, ``select``,
               ``timeline``, ``tree``, ``menu``.
        value: The runtime value to validate (should be ``list[dict]``).

    Returns:
        Empty list when valid; list of human-readable error strings otherwise.
        Never raises.
    """
    schema = _schema(kind)
    if schema is None:
        return [f"unknown child kind '{kind}': no schema found"]

    # Top-level type check — all ui_children schemas are type:array
    if schema.get("type") == "array" and not isinstance(value, list):
        return [f"expected array for '{kind}', got {type(value).__name__}"]

    if not isinstance(value, list):
        return [f"expected array for '{kind}', got {type(value).__name__}"]

    item_schema = schema.get("items", {})
    errors: list[str] = []
    for i, item in enumerate(value):
        errors.extend(_check_item(item, item_schema, i))

    return errors
