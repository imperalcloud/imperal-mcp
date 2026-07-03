# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from imperal_sdk.types.identity import UserContext, TenantContext

if TYPE_CHECKING:
    from imperal_sdk.types.models import (
        Document, CompletionResult, LimitsResult, SubscriptionInfo,
        BalanceInfo, FileInfo, HTTPResponse,
    )
    from imperal_sdk.types.pagination import Page


@runtime_checkable
class StoreProtocol(Protocol):
    async def create(self, collection: str, data: dict) -> Document: ...
    async def get(self, collection: str, doc_id: str) -> Document | None: ...
    async def query(self, collection: str, where: dict | None = None, order_by: str | None = None, limit: int = 100, cursor: str | None = None) -> Page[Document]: ...
    async def update(self, collection: str, doc_id: str, data: dict) -> Document: ...
    async def delete(self, collection: str, doc_id: str) -> bool: ...
    async def count(self, collection: str, where: dict | None = None) -> int: ...


@runtime_checkable
class AIProtocol(Protocol):
    async def complete(self, prompt: str, model: str = "", **kwargs) -> CompletionResult: ...


@runtime_checkable
class SkeletonProtocol(Protocol):
    """Read-only skeleton accessor.

    v1.6.0 breaking change: ``update()`` removed. The kernel
    skeleton-save platform execution is the sole writer. Extensions
    return fresh data from their ``@ext.skeleton`` tool.
    """
    async def get(self, section: str) -> Any: ...


@runtime_checkable
class BillingProtocol(Protocol):
    async def check_limits(self) -> LimitsResult: ...
    async def get_subscription(self) -> SubscriptionInfo: ...
    async def track_usage(self, meter: str, quantity: int = 1, user: Any = None) -> bool: ...
    async def get_balance(self) -> BalanceInfo: ...
    async def list_payment_methods(self, user: Any = None) -> list: ...
    async def list_payments(self, user: Any = None, limit: int = 50, offset: int = 0) -> list: ...
    async def create_setup_intent(self, user: Any = None): ...
    async def set_default_payment_method(self, pm_id: str, user: Any = None) -> bool: ...
    async def remove_payment_method(self, pm_id: str, user: Any = None) -> bool: ...
    async def change_plan(self, plan_id: str, period: str = "monthly", user: Any = None): ...
    async def topup(self, tokens: int, price_cents: int, save_payment_method: bool = True, off_session: bool = True, user: Any = None): ...
    async def create_billing_portal_session(self, user: Any = None) -> str: ...
    async def list_plans(self, user: Any = None) -> list: ...
    async def get_auto_topup(self, user: Any = None): ...
    async def set_auto_topup(self, enabled: bool, threshold_pct: int = 10, recharge_tokens: int = 20000, payment_method_id: str = "", user: Any = None) -> bool: ...
    async def cancel_subscription(self, user: Any = None) -> dict: ...
    async def resume_subscription(self, user: Any = None) -> dict: ...
    async def renew_subscription(self, user: Any = None) -> dict: ...
    async def update_billing_profile(self, profile: dict, user: Any = None) -> bool: ...


@runtime_checkable
class NotifyProtocol(Protocol):
    # Preferred invocation: ``await ctx.notify("message", priority="high")``.
    # Matches the concrete NotifyClient.__call__ signature. Every production
    # extension uses this style.
    async def __call__(self, message: str, **kwargs) -> None: ...
    # Alias kept for historical test doc compatibility; NotifyClient forwards
    # this to __call__. Prefer __call__ in new code.
    async def send(self, message: str, channel: str = "in_app", **kwargs) -> None: ...


@runtime_checkable
class StorageProtocol(Protocol):
    async def upload(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> FileInfo: ...
    async def download(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> bool: ...
    async def list(self, prefix: str = "") -> Page[FileInfo]: ...


@runtime_checkable
class HTTPProtocol(Protocol):
    async def get(self, url: str, **kwargs) -> HTTPResponse: ...
    async def post(self, url: str, **kwargs) -> HTTPResponse: ...
    async def put(self, url: str, **kwargs) -> HTTPResponse: ...
    async def patch(self, url: str, **kwargs) -> HTTPResponse: ...
    async def delete(self, url: str, **kwargs) -> HTTPResponse: ...


@runtime_checkable
class ConfigProtocol(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def get_section(self, section: str) -> dict: ...
    def all(self) -> dict: ...


@runtime_checkable
class ExtensionsProtocol(Protocol):
    async def call(self, app_id: str, method: str, **kwargs) -> Any: ...
    async def emit(self, event_type: str, data: dict) -> None: ...


@dataclass
class TimeContext:
    """Kernel-injected time context. Read-only, no network call."""
    timezone: str = "UTC"
    utc_offset: str = "+00:00"
    now_utc: str = ""
    now_local: str = ""
    hour_local: int = 0
    is_business_hours: bool = False


class _SkeletonAccessGuard:
    """Wraps a :class:`SkeletonProtocol` implementation; rejects access outside
    ``@ext.skeleton`` contexts.

    v1.6.0: ``ctx.skeleton`` is the LLM-facts snapshot consumed by the intent
    classifier. Only ``@ext.skeleton`` refresh tools are allowed to read it.
    Panels, regular tools, and chat functions must use ``ctx.cache`` for
    short-lived runtime data or ``ctx.store`` for persistent per-user state.

    Note the absence of an ``update`` method — consistent with
    :class:`SkeletonProtocol` v1.6.0 read-only contract; prevents a bypass
    path being re-introduced.
    """

    __slots__ = ("_client", "_tool_type")

    def __init__(self, client: Any, tool_type: str):
        self._client = client
        self._tool_type = tool_type

    async def get(self, section: str) -> Any:
        if self._tool_type != "skeleton":
            # Local import to avoid a cycle; errors depends on nothing,
            # but keep the indirection minimal for clarity.
            from imperal_sdk.errors import SkeletonAccessForbidden
            raise SkeletonAccessForbidden(
                f"ctx.skeleton.get() called from {self._tool_type!r} context; "
                "only @ext.skeleton tools may access skeleton."
            )
        return await self._client.get(section)


@dataclass
class Context:
    """The context object passed to every extension tool/signal/schedule call."""
    user: "UserContext"
    tenant: "TenantContext | None" = None
    store: StoreProtocol | None = None
    ai: AIProtocol | None = None
    # ``skeleton`` is a raw :class:`SkeletonProtocol` implementation supplied
    # by the kernel. In v1.6.0 it is wrapped by :class:`_SkeletonAccessGuard`
    # when surfaced via the :pyattr:`skeleton` property — direct access to
    # this field is deprecated and reserved for internal construction.
    skeleton: SkeletonProtocol | None = None
    billing: BillingProtocol | None = None
    notify: NotifyProtocol | None = None
    storage: StorageProtocol | None = None
    http: HTTPProtocol | None = None
    config: ConfigProtocol | None = None
    extensions: ExtensionsProtocol | None = None
    time: TimeContext = field(default_factory=TimeContext)
    # Agency tenancy + white-label theming (2026-04-19). agency_id is the
    # data-isolation boundary; agency_theme is the raw dict form of the
    # AgencyTheme payload populated by the kernel on workflow start. Parse
    # via ``imperal_sdk.ui.theme(ctx)`` for a typed accessor.
    agency_id: str | None = None
    agency_theme: dict | None = None
    _extension_id: str = ""
    _metadata: dict = field(default_factory=dict)
    # v1.6.0 skeleton + cache HMAC plumbing. ``_tool_type`` discriminates the
    # dispatch surface (``"skeleton"`` / ``"panel"`` / ``"tool"`` /
    # ``"chat_fn"``); ``_call_token`` is the per-invocation HMAC call-token
    # minted by the kernel and verified by the Auth GW on skeleton/cache
    # endpoints.
    _tool_type: str = "tool"
    _call_token: str = ""
    # Extension instance (for ctx.cache -> cache_model reverse lookup).
    # Populated by the kernel when constructing the Context; ``None`` in
    # minimal mock contexts.
    _extension: Any = None
    # Gateway URL for cache HTTP traffic. When ``""`` (the default) the
    # Context will attempt to derive it from one of the existing clients
    # (skeleton / store / notify) in ``__post_init__``.
    _gateway_url: str = ""
    # Service token for cache HTTP traffic. Same derivation rules as
    # ``_gateway_url``.
    _service_token: str = ""

    def __post_init__(self):
        # Wrap the raw skeleton client in the access guard so that only
        # ``@ext.skeleton`` tool invocations (``_tool_type == "skeleton"``)
        # can read sections. Keep the wrapped client reachable via the
        # ``_raw_skeleton`` attribute for the as_user() rebuild path.
        self._raw_skeleton = self.skeleton
        if self.skeleton is not None:
            self.skeleton = _SkeletonAccessGuard(self.skeleton, self._tool_type)

        # Build ctx.cache if we have enough signal: an Extension reference +
        # a derivable gateway URL. In mock contexts (no extension, no clients
        # with a _gateway_url) we leave ``_cache`` as ``None`` and the cache
        # property raises a clear error on access.
        self._cache = None
        gw = self._gateway_url or self._derive_gateway_url()
        svc = self._service_token or self._derive_service_token()
        if self._extension is not None and gw:
            try:
                from imperal_sdk.cache.client import CacheClient
                self._cache = CacheClient(
                    # 2026-05-13: kernel-authoritative app_id (folder/manifest
                    # name passed by ContextFactory). ext.app_id is the Python
                    # runtime value and can drift from the deployed app_id
                    # (e.g. Extension("spotify-extension") in app.py while
                    # /opt/extensions/spotify/ + Dev Portal row are "spotify"
                    # — auth-gw extcache 401'd every request). Fall back to
                    # ext.app_id only when factory didn't pass _extension_id.
                    app_id=self._extension_id or getattr(self._extension, "app_id", ""),
                    user_id=self.user.imperal_id,
                    gw_url=gw,
                    service_token=svc,
                    call_token=self._call_token,
                    extension=self._extension,
                )
            except Exception:
                # Construction failures (e.g. empty app_id/user_id in exotic
                # mock contexts) should not blow up Context creation — the
                # cache property will surface the problem on first use.
                self._cache = None

    # ------------------------------------------------------------------
    # Gateway URL / service-token derivation for ctx.cache.
    # ------------------------------------------------------------------

    def _derive_gateway_url(self) -> str:
        for candidate in (self._raw_skeleton, self.store, self.notify):
            url = getattr(candidate, "_gateway_url", "") if candidate else ""
            if url:
                return url
        return ""

    def _derive_service_token(self) -> str:
        # SkeletonClient stores the token as _token; StoreClient as _auth_token;
        # NotifyClient as _auth_token. Pick whichever is populated.
        for candidate, attr in (
            (self._raw_skeleton, "_token"),
            (self.store, "_auth_token"),
            (self.notify, "_auth_token"),
        ):
            tok = getattr(candidate, attr, "") if candidate else ""
            if tok:
                return tok
        return ""

    @property
    def cache(self):
        """Short-lived Pydantic-typed per-user cache.

        Access ``ctx.cache.get(key, Model)`` / ``.set(key, value, ttl_seconds=N)``
        inside any tool/panel/chat_fn context. Pydantic model must be
        registered via ``@ext.cache_model(name)`` on the owning Extension.

        Raises :class:`RuntimeError` if the Context was constructed without
        enough state to build a :class:`CacheClient` (no ``_extension`` or
        no derivable ``_gateway_url``) — this happens in minimal mock
        contexts; use real kernel-built contexts in production.
        """
        if self._cache is None:
            raise RuntimeError(
                "ctx.cache is not available in this context; the Context "
                "was constructed without an Extension reference or a "
                "derivable gateway URL. This is typically a test harness "
                "issue — use a real kernel-built Context in production."
            )
        return self._cache

    async def progress(self, percent: float, message: str = "") -> None:
        """Report task progress. May raise TaskCancelled if user cancelled."""
        cb = getattr(self, "_progress_callback", None)
        if cb:
            await cb(percent, message)

    async def background_task(
        self,
        coro,
        *,
        long_running: bool = False,
        name: str = "",
    ) -> str:
        """Spawn a coroutine in the background; return task_id immediately.

        The kernel detaches ``coro`` via ``asyncio.create_task`` and tracks
        it as an explicit-opt-in background task (federal task lifecycle in
        ``util/task_manager.py``). When ``coro`` completes, the kernel
        auto-delivers its returned ``ActionResult`` as a fresh bot message
        in the user's chat via the existing ``_deliver_to_chat`` pipeline.

        Args:
            coro: A coroutine returning ``ActionResult``. Required.
            long_running: ``False`` (default) → 180s federal cap.
                          ``True`` → 1800s cap (``LONG_RUNNING_TASK_S``).
            name: Human-readable name for UI/audit (default ``"background"``).

        Returns:
            task_id (str) — opaque platform task identifier.

        Raises:
            RuntimeError: if ``ctx`` lacks kernel-injected spawn hook
                (e.g. dev mode or non-extension dispatch context).

        Note: ``coro`` MUST return ``ActionResult``; non-ActionResult return
        triggers a critical audit row and delivers a fallback error to chat.
        """
        spawn = getattr(self, "_background_task_spawn", None)
        if spawn is None:
            raise RuntimeError(
                "ctx.background_task not available in this context — the "
                "Context was constructed without a kernel-injected spawn "
                "hook. This is typically a test harness or dev-mode issue."
            )
        return await spawn(coro, long_running=long_running, name=name or "background")

    async def deliver_chat_message(
        self,
        text: str,
        *,
        msg_type: str = "response",
        refresh_panels: list[str] | None = None,
    ) -> None:
        """Inject a bot message into user's chat at any time.

        Mirrors the existing kernel auto-promote chat-injection path
        (``pipeline/task_delivery.py:_deliver_to_chat``) but is callable
        explicitly from extension code. Use cases:
          - Background task multi-stage announcements before final result
          - Webhook acknowledgements ("Spotify connected!")
          - Any one-off bot message that skeleton-alert polling can't model

        Args:
            text: Bot message body (Markdown). Truncated to 64KB if larger.
            msg_type: ``"response"`` (default — bot turn),
                      ``"system"`` (italicized notice),
                      ``"tool_result"`` (formatted as tool execution).
            refresh_panels: optional list of panel_ids to re-render after.

        Note: inject is scoped to ``(ext_id, user_id)``; cross-user inject
        returns 403. Every inject writes an audit row in ``action_ledger``.
        """
        MAX_BYTES = 64 * 1024
        if len(text.encode("utf-8")) > MAX_BYTES:
            text = text.encode("utf-8")[:MAX_BYTES].decode("utf-8", errors="ignore") + "...(truncated)"

        ext_id = getattr(self, "_extension_id", None)
        user_id = getattr(self, "_user_id", None) or getattr(self.user, "imperal_id", None)
        gateway_url = getattr(self, "_gateway_url", None)
        service_token = getattr(self, "_service_token", None)
        if not all([ext_id, user_id, gateway_url, service_token]):
            raise RuntimeError(
                "ctx.deliver_chat_message requires kernel-injected (ext_id, "
                "user_id, gateway_url, service_token). Not available in this "
                "context (likely a test harness or dev-mode dispatch)."
            )

        url = f"{gateway_url.rstrip('/')}/v1/internal/chat/inject"
        body = {
            "ext_id": ext_id,
            "user_id": user_id,
            "text": text,
            "msg_type": msg_type,
        }
        if refresh_panels:
            body["refresh_panels"] = refresh_panels
        headers = {
            "X-Service-Token": service_token,
            "X-Acting-User": user_id,
        }
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(url, json=body, headers=headers)

    async def log(self, message: str, level: str = "info") -> None:
        """Structured log visible in extension dashboard."""
        import logging
        logger = logging.getLogger(f"ext.{self._extension_id}")
        getattr(logger, level, logger.info)(message)

    def webhook_url(self, path: str) -> str:
        """Build the public OAuth/webhook callback URL for this extension.

        Returns the URL the extension author must register in the OAuth
        provider's developer console (Spotify, GitHub, Google, etc.).

        Path is the same string passed to ``@ext.webhook("/path")``. Both
        forms work — leading slash is normalised:

            ctx.webhook_url("/callback")     # → .../webhook/callback
            ctx.webhook_url("callback")      # → .../webhook/callback
            ctx.webhook_url("/oauth/return") # → .../webhook/oauth/return

        Host comes from the ``IMPERAL_PUBLIC_HOST`` env var (default
        ``panel.imperal.io``). Path-component ``{app_id}`` comes from the
        kernel-authoritative ``_extension_id`` (folder/manifest name),
        not from ``ext.app_id`` (Python runtime, can drift).

        Use this instead of hardcoding the URL in ``spotify_config.py``
        et al. — that pattern is what caused the 2026-05-13 Spotify 401
        class (auth-gw never saw the drifted `spotify-extension` row).
        """
        import os as _os_wh
        host = _os_wh.environ.get("IMPERAL_PUBLIC_HOST", "panel.imperal.io")
        clean_path = (path or "").lstrip("/")
        app_id = self._extension_id or getattr(self._extension, "app_id", "")
        if not app_id:
            raise RuntimeError(
                "ctx.webhook_url() called without an extension_id — "
                "kernel must build ctx via ContextFactory."
            )
        return f"https://{host}/v1/ext/{app_id}/webhook/{clean_path}"

    def as_user(self, user_id: str) -> "Context":
        """Return scoped Context for target user_id.

        System-context only. Rewires per-user clients (store, skeleton,
        notify, billing) with new user_id; inherits ai/storage/http/config.

        Guards: system-context required; only ``user.id`` changes —
                extension, tenant, and agency context are preserved.

        Raises:
            RuntimeError: caller is not system-context.
            ValueError: user_id is empty or "__system__".
        """
        if self.user.imperal_id != "__system__":
            raise RuntimeError(
                f"ctx.as_user() requires system context (got {self.user.imperal_id!r})"
            )
        if not user_id or user_id == "__system__":
            raise ValueError(
                f"target user_id must be non-empty, non-system: {user_id!r}"
            )

        new_user = UserContext(
            imperal_id=user_id,
            email=self.user.email,
            tenant_id=self.user.tenant_id,
            agency_id=getattr(self.user, "agency_id", None),
            role=self.user.role,
            scopes=list(self.user.scopes),
            attributes=dict(self.user.attributes, scoped_from="__system__"),
        )

        new_store = self._rebuild_store_for(user_id) if self.store else None
        new_skeleton = self._rebuild_skeleton_for(user_id) if self.skeleton else None
        new_notify = self._rebuild_notify_for(user_id) if self.notify else None
        new_billing = self._rebuild_billing_for(user_id) if self.billing else None

        return Context(
            user=new_user,
            tenant=self.tenant,
            store=new_store,
            skeleton=new_skeleton,
            notify=new_notify,
            billing=new_billing,
            # Reused — not user-scoped
            ai=self.ai,
            storage=self.storage,
            http=self.http,
            config=self.config,
            extensions=self.extensions,
            time=self.time,
            agency_id=self.agency_id,
            agency_theme=self.agency_theme,
            _extension_id=self._extension_id,
            _metadata=dict(self._metadata),
            _tool_type=self._tool_type,
            _call_token=self._call_token,
            _extension=self._extension,
            _gateway_url=self._gateway_url,
            _service_token=self._service_token,
        )

    def _rebuild_store_for(self, user_id: str):
        from imperal_sdk.store.client import StoreClient
        return StoreClient(
            gateway_url=self.store._gateway_url,
            service_token=self.store._auth_token,
            extension_id=self._extension_id,
            user_id=user_id,
            tenant_id=self.user.tenant_id,
        )

    def _rebuild_skeleton_for(self, user_id: str):
        from imperal_sdk.skeleton.client import SkeletonClient
        # Use the raw (unwrapped) client so the new Context can wrap it with
        # its own guard + (possibly different) tool_type. ``_raw_skeleton``
        # is populated in ``__post_init__``. SkeletonClient stores its token
        # as ``_token`` (accepts both auth_token= and service_token=).
        raw = getattr(self, "_raw_skeleton", None) or self.skeleton
        return SkeletonClient(
            gateway_url=raw._gateway_url,
            service_token=raw._token,
            extension_id=self._extension_id,
            user_id=user_id,
            call_token=getattr(raw, "_call_token", ""),
        )

    def _rebuild_notify_for(self, user_id: str):
        from imperal_sdk.notify.client import NotifyClient
        return NotifyClient(
            gateway_url=self.notify._gateway_url,
            service_token=self.notify._auth_token,
            user_id=user_id,
        )

    def _rebuild_billing_for(self, user_id: str):
        try:
            from imperal_sdk.billing.client import BillingClient
        except ImportError:
            return None
        # BillingClient separates service_token and auth_token; preserve both.
        return BillingClient(
            gateway_url=self.billing._gateway_url,
            service_token=getattr(self.billing, "_service_token", ""),
            auth_token=getattr(self.billing, "_auth_token", ""),
            user_id=user_id,
        )
