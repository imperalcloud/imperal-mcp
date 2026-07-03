# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Shared, kind-agnostic introspection helpers for the SDK reference.

These render a callable / dataclass / pydantic model into the pinned
``symbol`` shape. They are intentionally defensive: a symbol that cannot be
introspected degrades to empty params + a ``note`` enum entry rather than
crashing the whole generator (federal: the artifact must always build).
"""
from __future__ import annotations

import inspect
import json
import typing
from typing import Any, Literal, get_args, get_origin

from imperal_sdk.devtools.reference._flags import flags_for

# Sentinels that mean "no value" across inspect, dataclasses, and pydantic.
_EMPTY = inspect.Parameter.empty


def annotation_str(ann: Any) -> str | None:
    """Render an annotation as a stable readable string, or None when absent.

    The introspected modules use ``from __future__ import annotations``, so most
    annotations already arrive as strings (``"dict | None"``). Class objects and
    typing constructs are rendered to their readable form.
    """
    if ann is _EMPTY or ann is inspect.Signature.empty:
        return None
    if ann is None or ann is type(None):
        return "None"
    if isinstance(ann, str):
        return ann
    name = getattr(ann, "__name__", None)
    if name:
        return name
    # typing constructs (e.g. dict[str, str]) — strip the "typing." noise.
    return str(ann).replace("typing.", "")


def json_default(value: Any) -> Any:
    """Coerce a parameter/field default to a JSON-safe value.

    "No default" sentinels and any non-JSON-serializable object collapse to
    ``None``; the ``required`` flag (computed separately) distinguishes
    "no default" from "default is None".
    """
    if value is _EMPTY:
        return None
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return None
    return value


def literal_enum(ann: Any) -> list[str] | None:
    """Return the values of a ``Literal[...]`` annotation, else None.

    Only used for live ``Literal`` params; the resolved (object) annotation is
    required, since string annotations cannot be introspected for args.
    """
    if get_origin(ann) is Literal:
        return [str(v) for v in get_args(ann)]
    return None


def type_graph(annotation: Any) -> dict:
    """Render an annotation as a structured, machine-readable type graph.

    Produces a minimal graph that covers the types actually used by the SDK:
    union / none / list / dict / named-ref / any.  Free-dict children
    (``list[dict]``) are *not* expanded here — that is handled in Phase E.

    This function **never raises**: any annotation it cannot classify degrades
    to ``{"kind": "any"}`` so a bad third-party annotation never breaks the
    whole reference build.
    """
    try:
        # Missing annotation (inspect sentinel)
        if annotation is _EMPTY or annotation is inspect.Parameter.empty:
            return {"kind": "any"}
        # NoneType
        if annotation is type(None):
            return {"kind": "none"}
        # String annotations (PEP 563 forward references) — treat as named ref
        if isinstance(annotation, str):
            return {"ref": annotation}
        origin = get_origin(annotation)
        # Union / Optional
        if origin is typing.Union:
            return {"kind": "union", "of": [type_graph(a) for a in get_args(annotation)]}
        # list / set / tuple generics
        if origin in (list, set, tuple):
            args = get_args(annotation)
            return {"kind": "list", "of": type_graph(args[0]) if args else {"kind": "any"}}
        # dict generics
        if origin is dict:
            return {"kind": "dict"}
        # Named class or built-in (e.g. str, int, MyClass)
        name = getattr(annotation, "__name__", None)
        if name:
            return {"ref": name}
        return {"kind": "any"}
    except Exception:
        # Defensive: never let an exotic annotation propagate
        return {"kind": "any"}


def params_of(func: Any, *, skip_self: bool) -> list[dict[str, Any]]:
    """Introspect a callable's parameters into the pinned param shape.

    ``*args`` / ``**kwargs`` carry no static facts worth pinning and are
    dropped. ``self`` is dropped when ``skip_self`` is set.
    """
    out: list[dict[str, Any]] = []
    for name, p in inspect.signature(func).parameters.items():
        if skip_self and name == "self":
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        out.append({
            "name": name,
            "annotation": annotation_str(p.annotation),
            "default": json_default(p.default),
            "required": p.default is _EMPTY,
            "type": type_graph(p.annotation),
        })
    return out


def enums_from_literals(func: Any) -> dict[str, list[str]]:
    """Best-effort: declared ``Literal[...]`` params → enum sets.

    Resolves annotations via ``get_type_hints`` (needed under PEP 563 string
    annotations). Failure is non-fatal: returns whatever could be resolved.
    """
    enums: dict[str, list[str]] = {}
    try:
        import typing
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}
    for name, p in inspect.signature(func).parameters.items():
        ann = hints.get(name, p.annotation)
        values = literal_enum(ann)
        if values is not None:
            enums[name] = values
    return enums


def callable_symbol(
    func: Any,
    *,
    name: str,
    kind: str,
    skip_self: bool,
    enums: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a callable into the pinned symbol shape, degrading gracefully."""
    doc = (getattr(func, "__doc__", None) or "").strip()
    try:
        params = params_of(func, skip_self=skip_self)
        returns = annotation_str(inspect.signature(func).return_annotation)
    except (TypeError, ValueError) as exc:  # not introspectable
        return {
            "kind": kind,
            "params": [],
            "returns": None,
            "enums": {"_note": [f"uninspectable: {exc}"]},
            "description": "",
            **flags_for(name),
        }
    return {
        "kind": kind,
        "params": params,
        "returns": returns,
        "enums": enums or {},
        "description": doc,
        **flags_for(name),
    }


def degraded_symbol(name: str, kind: str, note: str) -> dict[str, Any]:
    """A placeholder symbol for something present but not introspectable."""
    return {
        "kind": kind,
        "params": [],
        "returns": None,
        "enums": {"_note": [note]},
        "description": "",
        **flags_for(name),
    }
