# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""JSON Schema + Pydantic contract for `imperal.json`.

Closes the V8 hole in `validator.py` — previously the filesystem manifest
was never validated. This module is the single source of truth for the
shape `generate_manifest()` produces and the Registry consumes.

Public API
----------
- `Manifest`                — Pydantic model (runtime validation)
- `validate_manifest_dict`  — dict -> list[ValidationIssue] for M1–M5; raises ValueError on M6.3/M7.3/M8.2
- `get_schema`              — returns JSON Schema (dict, Draft 2020-12)
- `MANIFEST_SCHEMA`         — same thing, module-level constant

The static JSON Schema file shipped with the package at
`imperal_sdk/schemas/imperal.schema.json` is regenerated from this model.
External tooling (IDE plugins, CI, non-Python services) should reference
that file rather than importing the SDK.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


# === Regex contracts ==================================================

# V1 — same pattern as validator.py:APP_ID_PATTERN
APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

# V2 — semver core; tolerate pre-release / build-metadata suffixes
SEMVER_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+(?:[.-][A-Za-z0-9.-]+)?$"
)

# Scopes observed in production:
#   "*"            — umbrella
#   "ns:*"         — namespace umbrella (post session-28 colon form)
#   "ns:action"    — specific capability
#   "ns.action"    — legacy dot form (still accepted by scope_guard)
# Disallow whitespace, uppercase, or leading/trailing separators.
SCOPE_PATTERN = re.compile(
    r"^(?:\*|[a-z][a-z0-9_-]*(?:[.:][a-z0-9_*-]+)+)$"
)

# 5-field cron or @-keyword (matches croniter / standard unix).
_CRON_5FIELD = re.compile(r"^\S+(?:\s+\S+){4}$")

# V25 — federal: I-MANIFEST-NO-ORCHESTRATOR-TOOL
_ORCH_TOOL_RE = re.compile(r"^tool_.+_chat$")
_CRON_KEYWORD = re.compile(
    r"^@(?:hourly|daily|weekly|monthly|yearly|annually|reboot)$"
)

# Tool parameter `type` field — mirrors `_python_type_to_str` output.
_VALID_PARAM_TYPES = {"string", "integer", "number", "boolean", "array", "object"}

# Python identifier (Registry stores tool names as activity names).
_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# === Leaf models ======================================================

class ToolParam(BaseModel):
    """One `parameters[name]` entry of a tool definition."""

    model_config = ConfigDict(extra="allow")  # description / default / etc.

    type: str
    required: bool

    @field_validator("type")
    @classmethod
    def _type_in_whitelist(cls, v: str) -> str:
        if v not in _VALID_PARAM_TYPES:
            raise ValueError(
                f"parameter type '{v}' must be one of "
                f"{sorted(_VALID_PARAM_TYPES)}"
            )
        return v


class Tool(BaseModel):
    """One entry in `manifest['tools']`.

    Federal v4.0.0 — typed dispatch fields (action_type, chain_callable,
    effects, params_schema, return_schema, event) declared at top level so
    the kernel chain planner can route deterministically without
    re-deriving from extension code.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = ""
    scopes: List[str] = Field(default_factory=list)
    parameters: Dict[str, ToolParam] = Field(default_factory=dict)

    # Federal v4.0.0 typed dispatch fields (optional for v1/v2 backward compat)
    action_type: Optional[str] = None  # "read", "write", "destructive"
    chain_callable: Optional[bool] = None
    effects: List[str] = Field(default_factory=list)
    params_schema: Optional[Dict[str, Any]] = None
    return_schema: Optional[Dict[str, Any]] = None
    # LONGRUN-V1 Component D (v4.2.13+) — declarative background-task sugar.
    # When background=True, the SDK chat handler auto-wraps invocations of
    # this tool in ctx.background_task(). long_running=True raises the
    # federal 180s cap to 1800s.
    background: Optional[bool] = None
    long_running: Optional[bool] = None
    event: Optional[str] = None
    owner_chat_tool: Optional[str] = None
    synthetic: Optional[bool] = None

    # Federal v4.1.2 — declared params field that carries the resolved
    # target id when the tool runs as a downstream chain step. Must be
    # accepted in the schema since the manifest emitter writes it (see
    # FunctionDef.id_projection in chat/extension.py).
    id_projection: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_is_identifier(cls, v: str) -> str:
        if not _TOOL_NAME_PATTERN.match(v):
            raise ValueError(
                f"tool name '{v}' must be a valid identifier "
                f"(letters/digits/underscore, not starting with digit)"
            )
        return v

    @field_validator("scopes")
    @classmethod
    def _scopes_valid(cls, v: List[str]) -> List[str]:
        for s in v:
            if not SCOPE_PATTERN.match(s):
                raise ValueError(
                    f"scope '{s}' must be '*', 'ns:action', 'ns:*', "
                    f"or legacy 'ns.action'"
                )
        return v


class Signal(BaseModel):
    """One entry in `manifest['signals']`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: Optional[str] = None


class Schedule(BaseModel):
    """One entry in `manifest['schedules']`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    cron: str
    description: Optional[str] = None

    @field_validator("cron")
    @classmethod
    def _cron_valid(cls, v: str) -> str:
        if not (_CRON_5FIELD.match(v) or _CRON_KEYWORD.match(v)):
            raise ValueError(
                f"cron '{v}' must be 5-field unix cron "
                f"(e.g. '0 9 * * *') or @keyword (@hourly, @daily, ...)"
            )
        return v


class Webhook(BaseModel):
    """One entry in `manifest['webhooks']` (M6)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., pattern=r"^/[a-z0-9_/-]+$")
    method: Literal["POST", "GET", "PUT", "DELETE"] = "POST"
    secret_header: str = ""


class EventSubscription(BaseModel):
    """One entry in `manifest['events']['subscribes']` (M7)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., min_length=1)
    handler: str


class EventEmit(BaseModel):
    """One entry in `manifest['events']['emits']` (M7)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., min_length=1)
    schema_ref: Optional[str] = None


class Events(BaseModel):
    """The `manifest['events']` section (M7)."""

    model_config = ConfigDict(extra="forbid")

    subscribes: List[EventSubscription] = Field(default_factory=list)
    emits: List[EventEmit] = Field(default_factory=list)


class ExposedDecl(BaseModel):
    """One entry in `manifest['exposed']` (M8)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action_type: Literal["read", "write"]


class HealthCheckDecl(BaseModel):
    """The `health_check` sub-object in `manifest['lifecycle']` (M9)."""

    model_config = ConfigDict(extra="forbid")

    interval_sec: int = Field(default=60, ge=30)


class LifecycleDecl(BaseModel):
    """The `manifest['lifecycle']` section (M9)."""

    model_config = ConfigDict(extra="forbid")

    on_install: Optional[bool] = None
    on_uninstall: Optional[bool] = None
    on_enable: Optional[bool] = None
    on_disable: Optional[bool] = None
    on_upgrade: Optional[List[str]] = None  # semver list
    health_check: Optional[HealthCheckDecl] = None


class TrayDecl(BaseModel):
    """One entry in `manifest['tray']` (M10)."""

    model_config = ConfigDict(extra="forbid")

    tray_id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]+$")
    icon: Optional[str] = None
    tooltip: Optional[str] = None


class SecretDecl(BaseModel):
    """One entry in `manifest['secrets']` — EXT-SECRETS-V1 (v4.2.2+).

    Mirrors :class:`imperal_sdk.secrets.spec.SecretSpec` after
    ``to_manifest_dict()``. The Pydantic model exists so
    :func:`validate_manifest_dict` round-trips the emitted shape — closes
    the `I-MANIFEST-EMITTER-SCHEMA-SYMMETRIC` drift gap that lived
    silently from v4.2.2 → v4.2.7.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,62}$")
    description: str = Field(..., min_length=1)
    required: bool = False
    write_mode: Literal["user", "extension", "both"] = "user"
    max_bytes: int = Field(default=4096, ge=1, le=65536)
    rotation_hint_days: Optional[int] = Field(default=None, ge=1)


# === UI surface (Ф2 — ui.* inside the contract) =======================
# Factored into a sibling module to respect the 300-line god-file rule
# (this file is already ≥300 lines). Imported here so callers can use
# ``from imperal_sdk.manifest_schema import UINode, Panel`` as advertised.
from imperal_sdk.manifest_schema_ui import Panel, UINode  # noqa: F401 (re-export)


# === Root model =======================================================

class Manifest(BaseModel):
    """Schema for `imperal.json`.

    Base fields (produced by `generate_manifest`) are required; marketplace
    fields merged from disk are optional. Unknown top-level keys are
    rejected — typos like `"schedule"` (singular) would otherwise silently
    disable scheduled tasks.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Base (always present) ---
    manifest_schema_version: Optional[Literal[1, 2, 3]] = None
    # SDK contract version emitted by `generate_manifest`; consumed by
    # validator_v1_6_0.SDK-VERSION-1 to detect extensions that pre-date
    # the v1.6.0 cache + skeleton contract.
    # Federal I-LOADER-REJECTS-LEGACY-LLM-ROUTER: kernel rejects loads
    # with sdk_version < 5.0.0 (unified-chain minimum).
    sdk_version: Optional[str] = None
    app_id: str
    version: str
    capabilities: List[str] = Field(default_factory=list)
    tools: List[Tool] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)
    schedules: List[Schedule] = Field(default_factory=list)
    required_scopes: List[str] = Field(default_factory=list)

    # --- SDK-optional ---
    migrations_dir: Optional[str] = None
    config_defaults: Optional[Dict[str, Any]] = None
    webhooks: Optional[List[Webhook]] = None
    events: Optional[Events] = None
    exposed: Optional[List[ExposedDecl]] = None
    lifecycle: Optional[LifecycleDecl] = None
    tray: Optional[List[TrayDecl]] = None

    # --- Federal v4.0.0 (manifest_schema_version=3) ---
    # Federal contract surface — kernel reads these to dispatch deterministically.
    # All optional for v1/v2 backward compat; validator.py V14-V24 enforces at
    # publish time via Dev Portal hook.
    actions_explicit: Optional[bool] = None
    icon_size_bytes: Optional[int] = None
    lifecycle_hooks: Optional[Dict[str, Dict[str, Any]]] = None

    # Federal v4.2.0 — `system=True` marks platform-managed extensions
    # (admin / billing / developer / automations). Auto-installed for every
    # user on registration, hidden from marketplace, cannot be uninstalled.
    # Reserved for first-party Imperal authors (validator V31).
    system: Optional[bool] = None

    # Federal I-EXT-MANIFEST-HIDDEN-SIDEBAR-SYSTEM-ONLY (2026-05-27) —
    # `hidden_in_sidebar=True` instructs the Imperal Panel sidebar to NOT
    # render the icon for this extension. Functionality is preserved
    # (chat tools still work, skeleton still runs, lifecycle still fires)
    # — only the visual sidebar tile is suppressed.
    #
    # Restricted to system apps (`system=True`) — third-party extensions
    # MUST NOT hide themselves from the user-facing sidebar. Enforced by
    # `validate_manifest_dict` (V32) and the root model_validator below.
    hidden_in_sidebar: Optional[bool] = None

    # Federal v4.2.2 — EXT-SECRETS-V1. Optional array of per-user encrypted
    # credential declarations the extension reads via ``ctx.secrets.get()``.
    # Closes the `I-MANIFEST-EMITTER-SCHEMA-SYMMETRIC` drift where the
    # emitter wrote `secrets[]` from v4.2.2 onwards but this Pydantic model
    # had no matching field (extra="forbid" would have rejected — but
    # publish-time validators didn't gate through here).
    secrets: Optional[List[SecretDecl]] = None

    # Federal Ф2 — UI surface inside the contract. Additive list of declared
    # panels (slot + serialized ui tree). Validated via the Panel model, which
    # enforces ALLOWED_PANEL_SLOTS and the Input.type enum on any present tree.
    panels: Optional[List["Panel"]] = None

    # --- Marketplace merge (docs/imperal-cloud/developer-portal.md) ---
    name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    homepage: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    marketplace: Optional[Dict[str, Any]] = None
    pricing: Optional[Dict[str, Any]] = None

    @field_validator("app_id")
    @classmethod
    def _app_id_valid(cls, v: str) -> str:
        if not APP_ID_PATTERN.match(v):
            raise ValueError(
                f"app_id '{v}' must match [a-z0-9][a-z0-9-]*[a-z0-9] "
                f"(2+ chars, lowercase, no underscores)"
            )
        return v

    @field_validator("version")
    @classmethod
    def _version_valid(cls, v: str) -> str:
        if not SEMVER_PATTERN.match(v):
            raise ValueError(
                f"version '{v}' must be valid semver (e.g. '1.0.0' "
                f"or '1.0.0-rc.1')"
            )
        return v

    @field_validator("required_scopes")
    @classmethod
    def _required_scopes_valid(cls, v: List[str]) -> List[str]:
        for s in v:
            if not SCOPE_PATTERN.match(s):
                raise ValueError(
                    f"required_scopes entry '{s}' must be '*', "
                    f"'ns:action', 'ns:*', or legacy 'ns.action'"
                )
        return v

    @model_validator(mode="after")
    def _hidden_in_sidebar_requires_system(self) -> "Manifest":
        """Federal I-EXT-MANIFEST-HIDDEN-SIDEBAR-SYSTEM-ONLY.

        Third-party extensions MUST NOT hide themselves from the user-facing
        Imperal Panel sidebar. The hidden_in_sidebar flag is reserved for
        first-party Imperal system apps (system=True).
        """
        if self.hidden_in_sidebar is True and self.system is not True:
            raise ValueError(
                "hidden_in_sidebar=True requires system=True "
                "(federal I-EXT-MANIFEST-HIDDEN-SIDEBAR-SYSTEM-ONLY — "
                "third-party extensions cannot hide themselves from the sidebar)"
            )
        return self


# === Public API =======================================================

def validate_manifest_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a manifest dict against the JSON Schema contract.

    Returns a list of `ValidationIssue` entries for the schema-level rules
    M1–M5 (empty list means those passed). **Raises** ``ValueError`` on the
    hard semantic rules M6.3 / M7.3 / M8.2, which run only when the manifest
    is otherwise structurally valid (no M1–M5 issues present).

    Rule codes:
    - `M1`   — root is not a dict / JSON object             (issue)
    - `M2`   — missing required field                        (issue)
    - `M3`   — unknown top-level field (typo detection)      (issue)
    - `M4`   — invalid value (regex / type / enum mismatch)  (issue)
    - `M5`   — nested field error (tool / signal / schedule) (issue)
    - `M6.3` — webhooks[].path must be unique                (raises ValueError)
    - `M7.3` — events.emits[].type must be app_id-prefixed   (raises ValueError)
    - `M8.2` — exposed[].name must be unique                 (raises ValueError)

    Raises:
        ValueError: on an M6.3 / M7.3 / M8.2 violation.
    """
    # Local import — ValidationIssue lives in validator.py; avoid a
    # circular import at module load by deferring.
    from imperal_sdk.validator import ValidationIssue

    issues: List[ValidationIssue] = []

    if not isinstance(data, dict):
        issues.append(ValidationIssue(
            rule="M1", level="ERROR",
            message=f"manifest root must be a JSON object, got {type(data).__name__}",
            fix="Ensure imperal.json parses to a top-level {...} object",
        ))
        return issues

    try:
        Manifest.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            etype = err["type"]
            msg = err["msg"]

            if etype == "missing":
                rule, fix = "M2", f"Add '{loc}' field to imperal.json"
            elif etype == "extra_forbidden":
                rule = "M3"
                fix = (
                    f"Remove '{loc}' — not a known manifest field. "
                    f"Common typos: 'schedule'→'schedules', 'tool'→'tools'"
                )
            elif loc.startswith(("tools.", "signals.", "schedules.")):
                rule, fix = "M5", f"Fix nested value at '{loc}': {msg}"
            else:
                rule, fix = "M4", f"Fix value at '{loc}': {msg}"

            issues.append(ValidationIssue(
                rule=rule, level="ERROR",
                message=f"[{loc or 'root'}] {msg}",
                fix=fix,
            ))

    # --- Post-Pydantic semantic rules (raising) ---
    # Only run when Pydantic found no issues — semantic rules operate on
    # structurally valid data; running them on invalid data (e.g. empty type
    # that Pydantic already caught) produces confusing double-errors.
    if issues:
        return issues

    # M6.3: webhook path uniqueness
    if "webhooks" in data and isinstance(data["webhooks"], list):
        paths = [
            w["path"] for w in data["webhooks"]
            if isinstance(w, dict) and "path" in w
        ]
        if len(paths) != len(set(paths)):
            raise ValueError(
                f"M6.3 webhooks[].path duplicate — paths must be unique: {paths}"
            )

    # M7.3: events.emits[].type must be prefixed by app_id (cross-namespace block)
    if (
        "events" in data
        and isinstance(data["events"], dict)
        and "emits" in data["events"]
        and isinstance(data["events"]["emits"], list)
    ):
        app_id = data.get("app_id", "")
        for emit in data["events"]["emits"]:
            if not isinstance(emit, dict):
                continue
            etype = emit.get("type", "")
            # min_length=1 on EventEmit.type guarantees non-empty if Pydantic
            # validation passed; the truthy guard is dropped (federal no-silent-drop).
            if not etype.startswith(app_id + "."):
                raise ValueError(
                    f"M7.3 events.emits[].type {etype!r} must be prefixed by "
                    f"app_id {app_id!r} (cross-namespace block)"
                )

    # M8.2: exposed name uniqueness
    if "exposed" in data and isinstance(data["exposed"], list):
        names = [
            e["name"] for e in data["exposed"]
            if isinstance(e, dict) and "name" in e
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                f"M8.2 exposed[].name duplicate — names must be unique: {names}"
            )

    # V25 — federal: I-MANIFEST-NO-ORCHESTRATOR-TOOL
    # Manifests MUST NOT contain `tool_<ext>_chat` orchestrator-tool entries.
    # These were emitted by ChatExtension's now-removed LLM router (SDK <5.0.0).
    # Extensions rebuilt against SDK 5.0.0+ no longer produce them.
    for tool in data.get("tools") or []:
        name = tool.get("name", "") if isinstance(tool, dict) else ""
        if _ORCH_TOOL_RE.match(name):
            # federal: I-MANIFEST-NO-ORCHESTRATOR-TOOL — V25 rule emit site
            issues.append(ValidationIssue(
                rule="V25", level="ERROR",
                message=(
                    f"manifest contains orchestrator-tool '{name}' — "
                    f"this was emitted by ChatExtension LLM router (SDK <5.0.0). "
                    f"Rebuild against imperal-sdk>=5.0.0 to remove."
                ),
                fix="Remove the tool_*_chat entry and rebuild with imperal-sdk>=5.0.0.",
            ))

    return issues


def get_schema() -> Dict[str, Any]:
    """Return the JSON Schema (Draft 2020-12) for `imperal.json`.

    Emitted via `Manifest.model_json_schema()`. Stable within a SDK
    minor version; prefer the committed static file at
    `imperal_sdk/schemas/imperal.schema.json` for external tooling that
    should pin a specific version.
    """
    schema = Manifest.model_json_schema()
    schema["$id"] = "https://imperal.io/schemas/imperal.schema.json"
    schema["title"] = "Imperal Extension Manifest"
    schema["description"] = (
        "Shape of the `imperal.json` file produced by "
        "`imperal_sdk.manifest.generate_manifest()` and consumed by the "
        "Imperal Cloud Registry. Validated at deploy-time by "
        "`imperal_sdk.manifest_schema.validate_manifest_dict`."
    )
    return schema


MANIFEST_SCHEMA: Dict[str, Any] = get_schema()


__all__ = [
    "Manifest",
    "Tool",
    "ToolParam",
    "Signal",
    "Schedule",
    "Webhook",
    "EventSubscription",
    "EventEmit",
    "Events",
    "ExposedDecl",
    "HealthCheckDecl",
    "LifecycleDecl",
    "TrayDecl",
    "SecretDecl",
    # Ф2 — UI surface models (manifest_schema_ui.py)
    "UINode",
    "Panel",
    "validate_manifest_dict",
    "get_schema",
    "MANIFEST_SCHEMA",
    "APP_ID_PATTERN",
    "SEMVER_PATTERN",
    "SCOPE_PATTERN",
]
