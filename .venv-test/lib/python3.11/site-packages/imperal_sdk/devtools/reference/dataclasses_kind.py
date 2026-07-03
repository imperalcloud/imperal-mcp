# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""``dataclass`` kind — the result / def types in ``imperal_sdk.__all__``.

Most are ``@dataclass``; ``Page`` is a pydantic model. Both are introspected
into the pinned shape (fields → params; ``returns`` is null). A field with a
``default_factory`` (or a non-JSON default) is non-required with a null default
— the ``required`` flag carries the real "must supply" fact.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from imperal_sdk.devtools.reference._flags import flags_for
from imperal_sdk.devtools.reference._introspect import (
    annotation_str,
    degraded_symbol,
    json_default,
    type_graph,
)

# Result / def types declared in imperal_sdk.__all__ (scope expansion).
_TYPES = (
    "ActionResult", "ToolDef", "ScheduleDef", "WebhookDef", "LifecycleHook",
    "HealthCheckDef", "EventHandlerDef", "TrayDef", "ExposedMethod",
    "SignalDef", "Page", "Document", "HTTPResponse", "ChatResult",
    "FunctionCall", "CompletionResult", "LimitsResult", "SubscriptionInfo",
    "BalanceInfo", "FileInfo", "MeteredEvent", "Event", "WebhookRequest",
    "WebhookResponse", "HealthStatus",
)


def collect() -> dict[str, dict[str, Any]]:
    import imperal_sdk

    symbols: dict[str, dict[str, Any]] = {}
    for name in _TYPES:
        obj = getattr(imperal_sdk, name, None)
        if obj is None:
            symbols[name] = degraded_symbol(
                name, "dataclass", "not exported by imperal_sdk")
        elif dataclasses.is_dataclass(obj):
            symbols[name] = _dataclass_symbol(name, obj)
        elif hasattr(obj, "model_fields"):  # pydantic v2
            symbols[name] = _pydantic_symbol(name, obj)
        else:
            symbols[name] = degraded_symbol(
                name, "dataclass", f"{type(obj).__name__}, neither dataclass nor model")
    return symbols


def _dataclass_symbol(name: str, obj: Any) -> dict[str, Any]:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    params: list[dict[str, Any]] = []
    for f in dataclasses.fields(obj):
        has_factory = f.default_factory is not dataclasses.MISSING
        has_default = f.default is not dataclasses.MISSING
        required = not (has_factory or has_default)
        raw_type = f.type if isinstance(f.type, str) else f.type
        params.append({
            "name": f.name,
            "annotation": f.type if isinstance(f.type, str) else annotation_str(f.type),
            "default": json_default(f.default) if has_default else None,
            "required": required,
            "type": type_graph(raw_type),
        })
    return {"kind": "dataclass", "params": params, "returns": None, "enums": {}, "description": doc, **flags_for(name)}


def _pydantic_symbol(name: str, obj: Any) -> dict[str, Any]:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    params: list[dict[str, Any]] = []
    for fname, field in obj.model_fields.items():
        required = field.is_required()
        default = None if required else json_default(field.default)
        params.append({
            "name": fname,
            "annotation": annotation_str(field.annotation),
            "default": default,
            "required": required,
            "type": type_graph(field.annotation),
        })
    return {"kind": "dataclass", "params": params, "returns": None, "enums": {}, "description": doc, **flags_for(name)}
