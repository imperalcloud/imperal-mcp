"""Non-Turing multi-step declarative interpreter (internal runtime plumbing, not public API).

run_steps — walks steps[] in order (or follows conditional then/else ids),
resolves each step's args via the binding-DSL against the {event, steps, prev}
context, dispatches by op, captures each result under steps[id] and prev.
Returns {"steps": {...}, "prev": {...}}.
"""
from __future__ import annotations

from typing import Any

from .template import resolve_value
from .verbs import eval_conditional, run_store, run_ai, run_call, make_directive


async def run_steps(steps: list[dict], ctx: Any, *, event: dict | None = None) -> dict:
    """Execute a non-Turing declarative steps[] flow. Returns {steps, prev}."""
    # Guard: all steps must have an "id"
    for step in steps:
        if "id" not in step:
            raise ValueError(f"step missing required 'id': {step!r}")
    by_id = {s["id"]: s for s in steps}
    tcx: dict[str, Any] = {"event": event or {}, "steps": {}, "prev": {}}
    # linear walk with conditional jumps
    order = [s["id"] for s in steps]
    budget = max(64, len(steps) * 8)
    executions = 0
    i = 0
    while i < len(order):
        executions += 1
        if executions > budget:
            raise RuntimeError(
                f"declarative flow exceeded step budget ({budget}); possible cycle"
            )
        step = by_id[order[i]]
        sid, op = step["id"], step["op"]
        if op == "conditional":
            nxt = eval_conditional(step, tcx)
            tcx["steps"][sid] = {"next": nxt}
            tcx["prev"] = tcx["steps"][sid]
            if nxt is None:
                break
            if nxt not in by_id:
                raise ValueError(
                    f"conditional step {sid!r} targets unknown step id {nxt!r}"
                )
            i = order.index(nxt)
            continue
        args = resolve_value(step.get("args", {}), tcx)
        if op.startswith("store."):
            result = await run_store(op.split(".", 1)[1], args, ctx.store)
        elif op == "ai.complete":
            result = await run_ai(args, ctx.ai)
        elif op == "call":
            result = await run_call(args, ctx.extensions, getattr(ctx, "current_app_id", ""))
        elif op in ("navigate", "send", "open"):
            result = make_directive(op, args)
        else:
            raise ValueError(f"Unknown step op {op!r}")
        tcx["steps"][sid] = result
        tcx["prev"] = result
        i += 1
    return {"steps": tcx["steps"], "prev": tcx["prev"]}
