"""Imperal SDK Runtime — HostedClient (server-side IR dispatch)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from .engine import KernelEngine


class HostedClient(KernelEngine):
    """Runs IR functions on the cloud kernel via an injected transport.

    The transport callable is injected at construction time, keeping the SDK
    engine-neutral and testable without a live kernel connection.  For hosted
    deployments the platform injects a dispatch shim that forwards the IR
    function and params over the internal RPC channel; for tests a simple async
    callable suffices.
    """

    def __init__(self, dispatch: Callable[[dict, dict], Awaitable[dict]]):
        self._dispatch = dispatch

    async def run_function(
        self,
        ir_function: dict[str, Any],
        params: dict[str, Any],
        ctx: Any = None,
    ) -> dict[str, Any]:
        """Delegate execution to the injected transport and return its result."""
        return await self._dispatch(ir_function, params)
