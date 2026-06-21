"""Imperal SDK Runtime — KernelEngine abstract execution engine SPI."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KernelEngine(ABC):
    """Abstract execution engine SPI.

    Concrete engines implement ``run_function`` to execute a single IR function.
    The interpreter routes declarative functions through itself; code functions
    are dispatched to the host's code execution layer.  Both paths share this
    single contract so conformance testing can drive any engine identically.
    """

    @abstractmethod
    async def run_function(
        self,
        ir_function: dict[str, Any],
        params: dict[str, Any],
        ctx: Any,
    ) -> dict[str, Any]:
        """Execute one IR function and return its result envelope.

        Args:
            ir_function: Validated IR function node (``impl`` key determines
                dispatch: ``declarative`` → interpreter; ``code`` → host).
            params:      Resolved call parameters for this invocation.
            ctx:         Execution context (engine-defined; carries auth,
                         session, and platform access).

        Returns:
            Result envelope dict — shape is engine-defined but must carry
            at minimum ``{"ok": bool}``.
        """
        raise NotImplementedError
