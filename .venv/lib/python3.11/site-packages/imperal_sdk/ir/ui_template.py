from __future__ import annotations

from typing import Any

from ..runtime.template import resolve_value
from ..runtime.verbs import eval_conditional


def _resolve_props(props: dict, ctx: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in props.items():
        if isinstance(v, dict) and "$repeat" in v:
            items = resolve_value(v["$repeat"], ctx)
            alias = v.get("as", "item")
            node = v["node"]
            out[k] = [
                resolve_ui_tree(node, {**ctx, alias: it})
                for it in (items if isinstance(items, list) else [])
            ]
        elif isinstance(v, dict) and "$if" in v:
            out[k] = resolve_ui_tree(v, ctx)
        elif isinstance(v, dict) and "type" in v and "props" in v:
            out[k] = resolve_ui_tree(v, ctx)
        else:
            out[k] = resolve_value(v, ctx)
    return out


def resolve_ui_tree(tree: dict, ctx: dict) -> dict:
    """Tier-2: pre-resolve a {type,props} tree against the binding context (server-side).

    Handles:
    - {{binding}} substitution in all prop values
    - $repeat directive: expands a list expression into per-item nodes
    - $if directive: keeps or drops a node based on a condition (D3 grammar:
      {field, eq|neq|gt|lt|in|exists: <val>}); delegates to eval_conditional.
    Nested {type, props} children are resolved recursively.
    """
    if "$if" in tree:
        keep = eval_conditional({"if": tree["$if"], "then": "y", "else": None}, ctx) == "y"
        if not keep:
            return {}
        tree = tree["node"]

    return {"type": tree["type"], "props": _resolve_props(tree.get("props", {}), ctx)}
