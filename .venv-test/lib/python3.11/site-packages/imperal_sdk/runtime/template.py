"""Typed binding-DSL resolver (internal runtime plumbing, not public API).

resolve_path  — walks a dot-path through the context dict; returns MISSING on miss.
resolve_value — whole-string "{{path}}" → raw object; interpolated → str; recurses dict/list.
"""
from __future__ import annotations

import re
from typing import Any

MISSING = object()

_WHOLE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")
_TOKEN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def resolve_path(ctx: dict, path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return MISSING
    return cur


def resolve_value(value: Any, ctx: dict) -> Any:
    if isinstance(value, str):
        whole = _WHOLE.match(value)
        if whole:
            got = resolve_path(ctx, whole.group(1))
            return "" if got is MISSING else got
        def _sub(mo: re.Match) -> str:
            got = resolve_path(ctx, mo.group(1))
            return "" if got is MISSING else str(got)
        return _TOKEN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: resolve_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, ctx) for v in value]
    return value
