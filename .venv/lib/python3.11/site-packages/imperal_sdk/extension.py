# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from imperal_sdk.types.contributions import ALLOWED_PANEL_SLOTS

@dataclass
class ToolDef:
    name: str
    func: Callable
    scopes: list[str] = field(default_factory=list)
    description: str = ""

@dataclass
class SignalDef:
    name: str
    func: Callable

@dataclass
class ScheduleDef:
    name: str
    func: Callable
    cron: str

@dataclass
class LifecycleHook:
    name: str
    func: Callable
    version: str = ""  # only for on_upgrade

@dataclass
class HealthCheckDef:
    func: Callable

@dataclass
class WebhookDef:
    path: str
    func: Callable
    method: str = "POST"
    secret_header: str = ""

    def to_manifest(self) -> dict:
        return {
            "path": self.path,
            "method": self.method,
            "secret_header": self.secret_header,
        }

@dataclass
class EventHandlerDef:
    event_type: str
    func: Callable

    def to_manifest(self) -> dict:
        return {"type": self.event_type, "handler": self.func.__name__}


@dataclass
class EmitsDef:
    event_type: str
    schema_ref: str | None = None

    def to_manifest(self) -> dict:
        out: dict = {"type": self.event_type}
        if self.schema_ref is not None:
            out["schema_ref"] = self.schema_ref
        return out

@dataclass
class ExposedMethod:
    name: str
    func: Callable
    action_type: str = "read"

    def to_manifest(self) -> dict:
        return {"name": self.name, "action_type": self.action_type}

@dataclass
class TrayDef:
    """System tray item — icon + badge + optional dropdown panel in the OS top bar."""
    tray_id: str
    func: Callable
    icon: str = "Circle"
    tooltip: str = ""

    def to_manifest(self) -> dict:
        return {"tray_id": self.tray_id, "icon": self.icon, "tooltip": self.tooltip}

class Extension:
    """Imperal Cloud Extension.

    Federal v4.0.0 contract — every extension MUST declare:
      - ``display_name`` — human-readable name shown in Webbee's capability list
      - ``description`` — federal-grade plain-language description (≥40 chars)
      - ``icon`` — SVG file path (≤100KB, with ``<svg>`` root + ``viewBox``)
      - ``actions_explicit=True`` — every ``action_type="write"|"destructive"``
        tool is ``chain_callable=True`` so the kernel issues typed calls
        deterministically without delegating to the extension's LLM router

    Validators V14, V15, V19, V21 enforce these at SDK + Dev Portal level.
    """

    def __init__(
        self,
        app_id: str,
        version: str = "0.1.0",
        capabilities: list[str] | None = None,
        migrations_dir: str | None = None,
        config_defaults: dict | None = None,
        *,
        display_name: str = "",
        description: str = "",
        icon: str = "",
        actions_explicit: bool = True,
        system: bool = False,
    ):
        self.app_id = app_id
        self.version = version
        self.display_name = display_name
        self.description = description
        self.icon = icon
        self.actions_explicit = actions_explicit
        self.system = system
        self.capabilities = capabilities or []
        self.migrations_dir = migrations_dir
        self._tools: dict[str, ToolDef] = {}
        self._signals: dict[str, SignalDef] = {}
        self._schedules: dict[str, ScheduleDef] = {}
        self.config_defaults = config_defaults or {}
        self._lifecycle: dict[str, LifecycleHook] = {}
        self._health_check: HealthCheckDef | None = None
        self._webhooks: dict[str, WebhookDef] = {}
        self._event_handlers: list[EventHandlerDef] = []
        self._declared_emits: list[EmitsDef] = []
        self._exposed: dict[str, ExposedMethod] = {}
        self._panels: dict[str, dict] = {}
        self._tray: dict[str, "TrayDef"] = {}
        self._cache_models: dict[str, type] = {}
        # EXT-SECRETS-V1 (v4.2.2) — declared secrets emitted into manifest.secrets[]
        self._secrets: dict[str, "SecretSpec"] = {}

        # v5.0.1 UX fix: synthetic 'secrets' panel is now registered LAZILY
        # — only when the extension calls @ext.secret(...) for the first
        # time. Previously the panel was added unconditionally to every
        # Extension and appeared as an empty placeholder in the right slot
        # of every chat session even for extensions that declare zero
        # secrets. Lazy registration happens in ``secret()`` below; the
        # synthetic Secrets panel UI is identical when the extension
        # actually has secrets to show.

    def _auto_register_secrets_panel(self) -> None:
        """Register the platform-provided 'secrets' panel.

        Idempotent — only registers once per Extension instance. Slot
        defaults to 'right' (least-used by typical extensions, lowest
        collision risk with deploy-sync logic that keeps one panel per slot).
        """
        if "secrets" in self._panels:
            return
        try:
            from imperal_sdk.secrets.panel_handler import (
                builtin_secrets_panel_handler,
            )
        except Exception:
            # If secrets package import fails, don't break Extension init.
            return
        self.panel(
            "secrets",
            slot="right",
            title="Secrets",
            icon="KeyRound",
            refresh="manual",
        )(builtin_secrets_panel_handler)

    def secret(
        self,
        name: str,
        description: str,
        *,
        required: bool = False,
        write_mode: str = "user",
        max_bytes: int = 4096,
        rotation_hint_days: int | None = None,
    ):
        """Declare a secret the extension needs.

        Federal EXT-SECRETS-V1 contract — manifest.secrets[] is the single
        source of truth for what an extension may touch via ``ctx.secrets``.

        Usage::

            ext.secret(
                name="spotify_api_key",
                description="Your Spotify API key (from developer.spotify.com)",
                required=True,
                write_mode="user",       # user pastes in Panel UI
                max_bytes=200,
            )(lambda: None)

            # OAuth refresh tokens are written by the ext after authorize
            ext.secret(
                name="spotify_refresh_token",
                description="OAuth refresh token written by ext after authorize",
                write_mode="extension",
                rotation_hint_days=30,
            )(lambda: None)

        Returns an identity decorator — the wrapped target is unchanged.
        The call itself registers the SecretSpec on the Extension.
        """
        from imperal_sdk.secrets.spec import SecretSpec
        from imperal_sdk.secrets.exceptions import SecretDeclarationConflict

        spec = SecretSpec(
            name=name,
            description=description,
            required=required,
            write_mode=write_mode,
            max_bytes=max_bytes,
            rotation_hint_days=rotation_hint_days,
        )
        if name in self._secrets:
            raise SecretDeclarationConflict(
                f"@ext.secret name={name!r} declared twice on app_id={self.app_id!r}"
            )
        self._secrets[name] = spec

        # EXT-SECRETS-V1 (v4.2.4): synthetic Secrets panel is now registered
        # unconditionally in Extension.__init__ via _auto_register_secrets_panel.
        # This call site is a no-op safety net for older bytecode paths.
        self._auto_register_secrets_panel()

        def _decorator(target):
            return target  # syntactic anchor only — decorator is a no-op wrapper

        return _decorator

    @property
    def secrets(self) -> dict[str, "SecretSpec"]:
        """Read-only view of declared secrets keyed by name."""
        return dict(self._secrets)

    def tool(self, name: str, scopes: list[str] | None = None, description: str = ""):
        """Register a tool that the AI assistant can call."""
        def decorator(func: Callable) -> Callable:
            self._tools[name] = ToolDef(
                name=name,
                func=func,
                scopes=scopes or [],
                description=description or func.__doc__ or "",
            )
            return func
        return decorator

    def signal(self, name: str):
        """Register a signal handler for platform events."""
        def decorator(func: Callable) -> Callable:
            self._signals[name] = SignalDef(name=name, func=func)
            return func
        return decorator

    def schedule(self, name: str, cron: str):
        """Register a scheduled task."""
        def decorator(func: Callable) -> Callable:
            self._schedules[name] = ScheduleDef(name=name, func=func, cron=cron)
            return func
        return decorator

    def skeleton(
        self,
        section_name: str,
        *,
        alert: bool = False,
        ttl: int = 300,
        description: str = "",
    ):
        """Register a skeleton refresh tool by section name (recommended DX).

        Sugar over :meth:`tool` that applies the platform's naming convention:

        - The decorated function is registered as ``skeleton_refresh_<section_name>``.
        - When ``alert=True``, a paired ``skeleton_alert_<section_name>`` tool is
          also expected (register it separately with ``@ext.tool`` OR the kernel
          will simply skip change alerts if absent).
        - ``ttl`` is a hint to platform operators — the authoritative TTL lives
          in the Registry row (or the kernel's auto-derive default of 300s).

        The platform discovers this section automatically via
        the ``skeleton_refresh_<X>`` naming convention — no Registry migration
        required. See `imperal_sdk/docs/skeleton.md` §"Skeleton Refresh Tools"
        for the end-to-end contract and invariants.

        Return contract: refresh function MUST return ``{"response": <dict>}``
        where the dict surfaces scalar fields (counts, flags, short strings) at
        the top level so the intent classifier can read them directly from the
        user's envelope. Idempotent — safe to run on every tick.

        Example::

            @ext.skeleton("monitors", alert=True, ttl=300)
            async def refresh_monitors(ctx) -> dict:
                items = await ctx.store.query("wt_monitors", where={"owner_id": ctx.user.id})
                critical = sum(1 for m in items.data if m.data.get("status") == "critical")
                return {"response": {
                    "total":    len(items.data),
                    "critical": critical,
                    "warning":  sum(1 for m in items.data if m.data.get("status") == "warning"),
                    "ok":       sum(1 for m in items.data if m.data.get("status") == "ok"),
                }}
        """
        if not section_name or not isinstance(section_name, str):
            raise ValueError("skeleton: section_name must be a non-empty string")
        # Keep section_name flat (no colons, wildcards, or separators) — the
        # platform's purge helper rejects these characters defence-in-depth, and
        # they would break the platform state store's section key path.
        if any(c in section_name for c in "*?[]:/"):
            raise ValueError(
                f"skeleton: section_name {section_name!r} must not contain "
                "wildcard/separator characters (* ? [ ] : /)"
            )
        tool_name = f"skeleton_refresh_{section_name}"
        desc = description or f"Skeleton refresh: {section_name}"

        def decorator(func: Callable) -> Callable:
            self._tools[tool_name] = ToolDef(
                name=tool_name,
                func=func,
                scopes=[],  # skeleton refresh runs with system scopes ["*"]
                description=desc,
            )
            # Stash convention metadata for the validator + tooling.
            # Private attribute; extensions MUST NOT read this directly.
            ttl_val = int(ttl) if ttl else 300
            self._tools[tool_name]._skeleton = {  # type: ignore[attr-defined]
                "section_name": section_name,
                "alert_on_change": bool(alert),
                "ttl": ttl_val,
            }
            return func
        return decorator

    def cache_model(self, name: str):
        """Register a Pydantic model as a ``ctx.cache`` value shape.

        The model name is scoped to this :class:`Extension` instance — the
        same name in different extensions refers to different classes.
        ``ctx.cache.set(key, value, ttl_seconds=60)`` will reverse-lookup the
        class of ``value`` in this registry and refuse to persist anything
        whose type is not registered.

        Constraints:

        - ``cls`` must subclass ``pydantic.BaseModel`` — raises ``TypeError``.
        - ``name`` must be unique within the extension — duplicates raise
          ``ValueError``.

        Example::

            from pydantic import BaseModel

            class InboxSummary(BaseModel):
                unread: int
                latest_subject: str

            @ext.cache_model("inbox_summary")
            class _InboxSummary(InboxSummary):
                pass

        """
        from pydantic import BaseModel

        def decorator(cls):
            if not isinstance(cls, type) or not issubclass(cls, BaseModel):
                raise TypeError(
                    f"@{self.app_id}.cache_model: {getattr(cls, '__name__', cls)!r}"
                    " must be a Pydantic BaseModel subclass"
                )
            if name in self._cache_models:
                raise ValueError(
                    f"cache model {name!r} already registered for {self.app_id!r}"
                )
            self._cache_models[name] = cls
            return cls

        return decorator

    def _resolve_cache_model_name(self, cls) -> str | None:
        """Reverse-lookup the registered name for a Pydantic class.

        Returns the registered name if ``cls`` was registered via
        :meth:`cache_model`, else ``None``. Used by
        :class:`imperal_sdk.cache.CacheClient` to compute the platform state
        store key prefix before a set/get round-trip.
        """
        for model_name, registered_cls in self._cache_models.items():
            if registered_cls is cls:
                return model_name
        return None

    def on_install(self, func: Callable) -> Callable:
        """Register install hook. Called once when user installs extension."""
        self._lifecycle["on_install"] = LifecycleHook(name="on_install", func=func)
        return func

    def on_upgrade(self, version: str):
        """Register version-specific upgrade hook."""
        def decorator(func: Callable) -> Callable:
            self._lifecycle[f"on_upgrade:{version}"] = LifecycleHook(
                name="on_upgrade", func=func, version=version,
            )
            return func
        return decorator

    def on_uninstall(self, func: Callable) -> Callable:
        """Register uninstall hook. Clean up user data."""
        self._lifecycle["on_uninstall"] = LifecycleHook(name="on_uninstall", func=func)
        return func

    def on_enable(self, func: Callable) -> Callable:
        """Register enable hook. Called when admin enables for user/tenant."""
        self._lifecycle["on_enable"] = LifecycleHook(name="on_enable", func=func)
        return func

    def on_disable(self, func: Callable) -> Callable:
        """Register disable hook."""
        self._lifecycle["on_disable"] = LifecycleHook(name="on_disable", func=func)
        return func

    def health_check(self, func: Callable) -> Callable:
        """Register health check. Called every 60s by kernel."""
        self._health_check = HealthCheckDef(func=func)
        return func

    def _build_lifecycle_section(self) -> dict:
        """Aggregate _lifecycle hooks + health_check into the manifest lifecycle dict."""
        lc: dict = {}
        # Simple boolean hooks
        for simple_key in ("on_install", "on_uninstall", "on_enable", "on_disable"):
            if simple_key in self._lifecycle:
                lc[simple_key] = True
        # on_upgrade: extract versions from keys like "on_upgrade:2.0.0"
        upgrade_versions = sorted(
            hook.version
            for key, hook in self._lifecycle.items()
            if key.startswith("on_upgrade:")
        )
        if upgrade_versions:
            lc["on_upgrade"] = upgrade_versions
        # health_check
        if self._health_check is not None:
            lc["health_check"] = {"interval_sec": 60}
        return lc

    def webhook(self, path: str, method: str = "POST", secret_header: str = ""):
        """Register webhook endpoint. Routes POST /v1/ext/{app_id}/webhook/{path}.

        Also registers __webhook__{path} as a ToolDef so the platform runtime
        can dispatch it without LLM routing. The handler receives:
            ctx       — minimal context (user_id="__webhook__")
            headers   — dict of request headers (hop-by-hop stripped)
            body      — raw request body as string
            query_params — dict of URL query parameters

        Secret verification must be done inside the handler using secret_header.
        """
        def decorator(func: Callable) -> Callable:
            self._webhooks[path] = WebhookDef(
                path=path, func=func, method=method, secret_header=secret_header,
            )
            # Register as a ToolDef so DirectCallWorkflow can dispatch via /call
            tool_name = f"__webhook__{path}"
            self._tools[tool_name] = ToolDef(
                name=tool_name,
                func=func,
                description=f"Webhook handler for path: {path}",
            )
            return func
        return decorator

    def on_event(self, event_type: str):
        """Subscribe to a platform event."""
        def decorator(func: Callable) -> Callable:
            self._event_handlers.append(EventHandlerDef(event_type=event_type, func=func))
            return func
        return decorator

    def emits(self, event_type: str, *, schema_ref: str | None = None):
        """Declare an event this extension emits. Powers manifest emits[] section.

        Enforces federal cross-namespace block: event_type MUST be prefixed with
        this extension's app_id (e.g. ``"billing.topup_completed"`` for app_id
        ``"billing"``). Cross-namespace declarations raise ValueError immediately.
        """
        if "." not in event_type:
            raise ValueError(
                f"@ext.emits: event_type must be dotted, got {event_type!r}"
            )
        if not event_type.startswith(self.app_id + "."):
            raise ValueError(
                f"@ext.emits: event_type {event_type!r} must be prefixed by app_id "
                f"{self.app_id!r} (federal cross-namespace block)"
            )
        def decorator(func: Callable) -> Callable:
            self._declared_emits.append(EmitsDef(event_type=event_type, schema_ref=schema_ref))
            return func
        return decorator

    def expose(self, name: str, action_type: str = "read"):
        """Expose a method for inter-extension calls via ctx.extensions.call()."""
        def decorator(func: Callable) -> Callable:
            self._exposed[name] = ExposedMethod(name=name, func=func, action_type=action_type)
            return func
        return decorator

    def tray(self, tray_id: str, icon: str = "Circle", tooltip: str = ""):
        """Declare a system tray item in the OS top bar.

        The handler returns a UINode tree with badge and optional dropdown panel.
        Called via /call endpoint as __tray__{tray_id}.

        Example::

            @ext.tray("unread", icon="Mail", tooltip="Unread messages")
            async def tray_unread(ctx, **kwargs):
                count = await ctx.store.count("messages", where={"read": False})
                return ui.Stack([
                    ui.Badge(str(count), color="red" if count > 0 else "gray"),
                ])
        """
        def decorator(func: Callable) -> Callable:
            async def wrapper(ctx, **params):
                result = await func(ctx, **params)
                if hasattr(result, 'to_dict'):
                    return {"ui": result.to_dict(), "tray_id": tray_id, "icon": icon}
                return result
            self._tools[f"__tray__{tray_id}"] = ToolDef(
                name=f"__tray__{tray_id}", func=wrapper,
                description=f"Tray: {tooltip or tray_id}",
            )
            self._tray[tray_id] = TrayDef(
                tray_id=tray_id, func=wrapper, icon=icon, tooltip=tooltip,
            )
            return func
        return decorator

    def panel(self, panel_id: str, slot: str = "center", title: str = "",
              icon: str = "", refresh: str = "manual",
              center_overlay: bool = False, **kwargs):
        """Declare a UI panel. Handler returns UINode tree.
        Panel fetched via /call endpoint with function __panel__{panel_id}.

        `slot` must be one of ALLOWED_PANEL_SLOTS — `"center"` (default,
        middle content area), `"left"` / `"right"` (sidebars), or one of
        the less-common `"overlay"` / `"bottom"` / `"chat-sidebar"`.
        Unknown values raise ValueError at decoration time. The `"main"`
        value was removed in SDK 3.4.0 — use `"center"` instead.

        `center_overlay=True` (federal v4.1.8+) replaces the legacy
        hardcoded TS allowlist in the Imperal Panel host. When set,
        the kernel publishes ``center_overlay: true`` into the panel's
        unified_config entry; the frontend's ``isCenterOverlay`` reads
        the flag declaratively instead of consulting a hardcoded list of
        panel_id literals. Pair with ``slot="center"`` for the modal
        center-overlay surface (chat collapses to 380 px right rail).
        """
        if slot not in ALLOWED_PANEL_SLOTS:
            raise ValueError(
                f"@ext.panel({panel_id!r}, slot={slot!r}): unknown slot. "
                f"Must be one of {sorted(ALLOWED_PANEL_SLOTS)}. "
                "Note: 'main' was removed in SDK 3.4.0; use 'center' instead."
            )
        def decorator(func: Callable) -> Callable:
            async def wrapper(ctx, **params):
                result = await func(ctx, **params)
                if hasattr(result, 'to_dict'):
                    return {"ui": result.to_dict(), "panel_id": panel_id}
                return result
            self._tools[f"__panel__{panel_id}"] = ToolDef(
                name=f"__panel__{panel_id}", func=wrapper,
                description=f"Panel: {title or panel_id}",
            )
            self._panels[panel_id] = {
                "slot": slot, "title": title, "icon": icon,
                "refresh": refresh, "center_overlay": center_overlay,
                **kwargs,
            }
            return func
        return decorator

    def widget(self, widget_id: str, slot: str = "dashboard.stats",
               label: str = "", icon: str = "", **kwargs):
        """Declare a UI widget for injection points."""
        def decorator(func: Callable) -> Callable:
            async def wrapper(ctx, **params):
                result = await func(ctx, **params)
                if hasattr(result, 'to_dict'):
                    return {"ui": result.to_dict(), "widget_id": widget_id}
                return result
            self._tools[f"__widget__{widget_id}"] = ToolDef(
                name=f"__widget__{widget_id}", func=wrapper,
                description=f"Widget: {label or widget_id}",
            )
            return func
        return decorator

    @property
    def tools(self) -> dict[str, ToolDef]:
        return self._tools

    @property
    def signals(self) -> dict[str, SignalDef]:
        return self._signals

    @property
    def schedules(self) -> dict[str, ScheduleDef]:
        return self._schedules

    @property
    def lifecycle(self) -> dict[str, LifecycleHook]:
        return self._lifecycle

    @property
    def webhooks(self) -> dict[str, WebhookDef]:
        return self._webhooks

    @property
    def event_handlers(self) -> list[EventHandlerDef]:
        return self._event_handlers

    @property
    def declared_emits(self) -> list[EmitsDef]:
        return self._declared_emits

    @property
    def exposed(self) -> dict[str, ExposedMethod]:
        return self._exposed

    @property
    def tray_items(self) -> dict[str, "TrayDef"]:
        return self._tray

    @property
    def panels(self) -> dict[str, dict]:
        return self._panels

    async def call_tool(self, name: str, ctx: Any, **kwargs) -> Any:
        """Call a registered tool with context."""
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return await self._tools[name].func(ctx, **kwargs)

    async def call_signal(self, name: str, ctx: Any, **kwargs) -> Any:
        """Call a registered signal handler."""
        if name not in self._signals:
            raise ValueError(f"Unknown signal: {name}")
        return await self._signals[name].func(ctx, **kwargs)
