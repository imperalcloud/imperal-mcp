"""Inter-extension IPC. Direct in-process calls, kernel-mediated.

Extensions call each other via ctx.extensions.call(app_id, method, **params).
Zero HTTP — the kernel loads the target extension in-process and creates
a child context with fork semantics (inherits user, scopes, tenant, time).

Circular call detection prevents A -> B -> A infinite loops.
Scope checking enforces that the caller has permission to invoke the target.
"""
import logging

from imperal_sdk.errors import NotFoundError, AuthError, ExtensionError

log = logging.getLogger(__name__)

# Kernel hub_dispatch depth is admin-tunable (default 6; its depth counter
# EXCLUDES the root, rejecting at depth>=cap, so the default permits 6 nested
# inter-extension calls). This call stack INCLUDES the root (starts at len 1)
# and rejects at len>=MAX_CALL_DEPTH, so the equivalent fallback cap is 7 —
# permitting the same 6 nested calls, matching the kernel's default allowance
# rather than under-cutting it by one hop. This is only a client-side fallback;
# the kernel enforces the real per-tenant cap (hub_dispatch_max_depth, [0,9]).
MAX_CALL_DEPTH = 7


class CircularCallError(ExtensionError):
    """Raised when an inter-extension call creates a cycle."""

    def __init__(self, call_stack: list[str]):
        chain = " -> ".join(call_stack)
        super().__init__(call_stack[-1], f"Circular call detected: {chain}")


class ExtensionsClient:
    """Inter-extension IPC client. Injected as ctx.extensions by ContextFactory."""

    def __init__(
        self,
        loader,
        ctx_factory,
        kctx_dict: dict,
        current_app_id: str,
        call_stack: list[str] | None = None,
    ):
        self._loader = loader
        self._ctx_factory = ctx_factory
        self._kctx_dict = kctx_dict
        self._current = current_app_id
        self._call_stack = call_stack or [current_app_id]

    async def call(self, app_id: str, method: str, **params):
        """Call an exposed method on another extension.

        Args:
            app_id: Target extension id (e.g. "notes", "mail").
            method: Name registered via @ext.expose(name).
            **params: Keyword arguments forwarded to the exposed function.

        Returns:
            Whatever the exposed method returns.

        Raises:
            CircularCallError: If app_id is already in the call stack.
            NotFoundError: If app_id or method not found.
            AuthError: If caller lacks required scope.
            ExtensionError: If call depth exceeds MAX_CALL_DEPTH.
        """
        if app_id in self._call_stack:
            raise CircularCallError(self._call_stack + [app_id])

        if len(self._call_stack) >= MAX_CALL_DEPTH:
            raise ExtensionError(
                app_id, f"Call depth exceeded ({MAX_CALL_DEPTH}): "
                f"{' -> '.join(self._call_stack)} -> {app_id}",
            )

        if self._loader is None:
            raise ExtensionError(app_id, "ExtensionLoader not available")

        ext = self._loader.load(app_id)
        exposed = getattr(ext, "_exposed", {}).get(method)
        if not exposed:
            available = list(getattr(ext, "_exposed", {}).keys())
            raise NotFoundError(
                "method", f"{app_id}.{method} (available: {available})",
            )

        # Scope check: caller needs app_id:{action_type} or extensions:{action_type} or *
        required_scope = f"{app_id}:{exposed.action_type}"
        caller_scopes = self._kctx_dict.get("scopes", ["*"])
        if "*" not in caller_scopes and required_scope not in caller_scopes:
            meta_scope = f"extensions:{exposed.action_type}"
            if meta_scope not in caller_scopes:
                raise AuthError(f"Missing scope: {required_scope}")

        # Create child context with fork semantics
        child_ctx = self._ctx_factory.create_child(
            parent_kctx=self._kctx_dict,
            target_app_id=app_id,
            call_stack=self._call_stack + [app_id],
        )

        log.info("IPC: %s -> %s.%s(%s)", self._current, app_id, method, list(params.keys()))
        return await exposed.func(child_ctx, **params)

    async def emit(self, event_type: str, data: dict) -> None:
        """Publish an event via the platform audit chokepoint.

        Routes through the platform runtime (user-id integrity + audit row + event,
        one atomic chokepoint). Fire-and-forget: if the platform runtime is
        unavailable (e.g. unit-test rig outside it), falls back to a direct event
        publish. Errors are logged, not raised.
        """
        from ..runtime._platform import record_action_via_chokepoint, publish_event_fallback
        tenant_id = self._kctx_dict.get("tenant_id", "default")
        user_id = self._kctx_dict.get("user_id", "")
        try:
            handled = await record_action_via_chokepoint(
                app_id=self._current, event_type=event_type, data=data,
                kctx_dict=self._kctx_dict,
            )
            if handled:
                log.info("Event emitted via chokepoint: %s from %s", event_type, self._current)
                return
            await publish_event_fallback(
                event_type=event_type, data=data, source_app=self._current,
                user_id=user_id, tenant_id=tenant_id,
            )
        except Exception as e:
            log.error("Fallback emit failed: %s", e)
