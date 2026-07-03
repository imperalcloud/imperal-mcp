from __future__ import annotations

from typing import Any

from .template import resolve_value, MISSING


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def eval_conditional(spec: dict, ctx: dict) -> str | None:
    """Evaluate a conditional verb spec and return the next step id or None.

    Comparators (static, non-Turing): eq, neq, gt, lt, in, exists.
    field is resolved via resolve_value; gt/lt coerce to float via _num.
    """
    cond = spec["if"]
    actual = resolve_value(cond["field"], ctx)
    result = False
    if "eq" in cond:
        result = str(actual) == str(cond["eq"])
    elif "neq" in cond:
        result = str(actual) != str(cond["neq"])
    elif "gt" in cond:
        a, b = _num(actual), _num(cond["gt"])
        result = a is not None and b is not None and a > b
    elif "lt" in cond:
        a, b = _num(actual), _num(cond["lt"])
        result = a is not None and b is not None and a < b
    elif "in" in cond:
        result = cond["in"] in actual if isinstance(actual, (list, str, dict)) else False
    elif "exists" in cond:
        present = actual is not MISSING and actual not in ("", None)
        result = present if cond["exists"] else not present
    return spec.get("then") if result else spec.get("else")


async def run_store(op: str, args: dict, store) -> dict:
    """Execute a store.* step against a StoreProtocol-compatible object.

    Supported ops: get / list / create / update / delete.
    Step args: kind (collection), where, ids, id, set, data, limit.
    list maps to store.query; bulk update/delete loop per id (no native bulk).
    """
    coll = args.get("kind", "")
    if op == "create":
        doc = await store.create(coll, args["data"])
        doc_id = doc.get("id") if isinstance(doc, dict) else getattr(doc, "id", None)
        return {"id": doc_id}
    if op == "get":
        doc = await store.get(coll, args.get("id"))
        return {"doc": doc}
    if op == "list":
        page = await store.query(coll, where=args.get("where"), limit=args.get("limit", 100))
        # Page (types/pagination.py) exposes .data and is iterable; legacy code read a
        # non-existent .items, so store.list silently returned count=0. Read .data,
        # falling back to iterating any list-like.
        items = list(page.data) if hasattr(page, "data") else list(page or [])
        ids = [
            (it.get("id") if isinstance(it, dict) else getattr(it, "id", None))
            for it in items
        ]
        return {"docs": items, "ids": ids, "count": len(items)}
    if op == "update":
        ids = args.get("ids") or ([args["id"]] if "id" in args else [])
        for doc_id in ids:
            await store.update(coll, doc_id, args.get("set", {}))
        return {"ids": list(ids), "count": len(ids)}
    if op == "delete":
        ids = args.get("ids") or ([args["id"]] if "id" in args else [])
        n = 0
        for doc_id in ids:
            if await store.delete(coll, doc_id):
                n += 1
        return {"count": n}
    raise ValueError(f"Unknown store op {op!r}")


async def run_ai(args: dict, ai) -> dict:
    """Execute an ai.complete step against an AIProtocol-compatible object.

    args: prompt (required), model (optional, default "").
    Returns {"text": <completion text>}.
    """
    res = await ai.complete(args["prompt"], model=args.get("model", ""))
    return {"text": getattr(res, "text", "")}


async def run_call(args: dict, extensions, current_app_id: str) -> dict:
    """Route a call.* step through ExtensionsProtocol.call — never the kernel activity.

    args: function (required), app_id (optional, defaults to current_app_id), params (optional).
    Returns whatever the extension returns.
    """
    app_id = args.get("app_id", current_app_id)
    method = args["function"]
    params = args.get("params", {})
    return await extensions.call(app_id, method, **params)


def make_directive(op: str, args: dict) -> dict:
    """Build a terminal client directive dict (navigate / send / open).

    Mirrors UIAction.to_dict(): {"action": op, **args}.
    """
    return {"action": op, **args}
