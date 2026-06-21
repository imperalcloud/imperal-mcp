"""Imperal SDK Runtime — LocalDevEngine: in-process, no-Temporal execution engine.

Engine-neutral: no temporalio, no kernel imports. Suitable for local dev and
unit tests. Prod execution parity for the declarative path is proven by the
conformance test suite via the KernelEngine SPI.
"""
from __future__ import annotations

import importlib
from typing import Any

from .engine import KernelEngine
from .interpreter import run_steps


class LocalDevEngine(KernelEngine):
    """In-process engine for local development and testing.

    Executes IR functions without any Temporal/kernel infrastructure.
    Both dispatch paths are supported:

    - ``declarative`` — runs ``impl["steps"]`` via the non-Turing interpreter.
    - ``code`` — imports ``impl["module"]``, resolves ``impl["entry"]``, and
      calls ``await fn(ctx, params)`` directly in the current process.
    """

    async def run_function(
        self,
        ir_function: dict[str, Any],
        params: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any]:
        """Execute one IR function in-process and return its result envelope."""
        impl = ir_function["impl"]
        kind = impl["kind"]

        if kind == "declarative":
            return await run_steps(impl["steps"], ctx, event=params)

        if kind == "code":
            mod = importlib.import_module(impl["module"])
            fn = getattr(mod, impl["entry"])
            result = await fn(ctx, params)
            return result if isinstance(result, dict) else {"status": "success", "data": result}

        raise ValueError(f"LocalDevEngine: unknown impl kind {kind!r}")
