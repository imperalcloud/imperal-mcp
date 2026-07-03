# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""JSON Schema contracts for cross-boundary payloads.

Every payload that leaves a single Python process — across platform
execution boundaries, the platform state/event store, SSE, or the
Fast-RPC transport — is covered here. Inside a process, the dataclass
forms in `types/` remain the ergonomic API; at the boundary, these
Pydantic mirrors are the machine-enforceable contract.

Covered (as of v1.5.10)
-----------------------
- `ActionResult`  — every `@chat.function` return value. Serialized by
  `ActionResult.to_dict()`, consumed by the kernel executor, platform
  execution history, automation template resolver, and SSE delivery.
- `Event`         — platform event envelope published by extensions
  (`@chat.function(event=...)`) and consumed by the automation engine,
  kernel SSE, and Panel live-refresh. Previously only documented as 10
  textual invariants (RPC-I1..I10) with no runtime schema.

Public API
----------
- `ActionResultModel`, `EventModel`, `Event`  — Pydantic mirrors
- `validate_action_result_dict(data)`         — -> list[ValidationIssue]
- `validate_event_dict(data)`                 -> list[ValidationIssue]
- `get_action_result_schema()`, `ACTION_RESULT_SCHEMA`
- `get_event_schema()`,         `EVENT_SCHEMA`

Note: this is distinct from the public `Event` dataclass in `types.events`
— both names coexist in different submodules.

Rule codes (mirrors manifest_schema M1..M5 shape):
  `AR1..AR5`  — ActionResult payload issues
  `EV1..EV5`  — Event envelope issues

External tooling should prefer the committed static files at
`imperal_sdk/schemas/action_result.schema.json` and `event.schema.json`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


# === Regex contracts =================================================

# Event type: "ns.action", "ns:action", "ns.sub.action", "ns:sub:action".
# Matches both dot-form (legacy, e.g. "sharelock.case_created") and
# colon-form (post session-28, e.g. "notes:created"). At least one
# namespace + action segment required.
EVENT_TYPE_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:[.:][a-z0-9_]+)+$"
)

# Imperal canonical user/tenant ID prefixes; `""` also allowed (system).
_IMP_USER_PATTERN = re.compile(r"^(imp_u_[A-Za-z0-9_]+|__system__|)$")
_IMP_TENANT_PATTERN = re.compile(r"^(imp_t_[A-Za-z0-9_]+|default|)$")


# === ActionResult mirror =============================================

class ActionResultModel(BaseModel):
    """Pydantic contract for `ActionResult.to_dict()` output.

    Mirrors the dataclass in `imperal_sdk.types.action_result` —
    the dataclass is the ergonomic API, this is the machine-enforceable
    boundary contract.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    summary: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retryable: bool = False
    ui: Optional[Dict[str, Any]] = None
    refresh_panels: Optional[List[str]] = None

    @model_validator(mode="after")
    def _status_error_consistency(self) -> "ActionResultModel":
        """status='error' requires non-empty error message.

        Invariant kept symmetric with `ActionResult.error()` factory —
        a malformed dict with status='error' and no error= is a hard
        contract violation (kernel has no user-facing message to show).
        """
        if self.status == "error" and not (self.error or "").strip():
            raise ValueError(
                "status='error' requires a non-empty 'error' field "
                "(factory: ActionResult.error(message))"
            )
        if self.status == "success" and self.error is not None:
            raise ValueError(
                "status='success' must not carry an 'error' field "
                "(factory: ActionResult.success(...))"
            )
        return self


# === Event mirror ====================================================

class EventModel(BaseModel):
    """Pydantic contract for platform Event envelopes on the platform state/event store.

    Mirrors the dataclass in `imperal_sdk.types.events.Event` — same
    five fields, strict validation.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: str
    timestamp: str = ""
    user_id: str = ""
    tenant_id: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def _event_type_shape(cls, v: str) -> str:
        if not v or not EVENT_TYPE_PATTERN.match(v):
            raise ValueError(
                f"event_type '{v}' must be 'namespace.action' or "
                f"'namespace:action' (lowercase, underscore allowed in "
                f"segments; at least one separator)"
            )
        return v

    @field_validator("user_id")
    @classmethod
    def _user_id_shape(cls, v: str) -> str:
        if v and not _IMP_USER_PATTERN.match(v):
            raise ValueError(
                f"user_id '{v}' must be 'imp_u_*', '__system__', or empty"
            )
        return v

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_shape(cls, v: str) -> str:
        if v and not _IMP_TENANT_PATTERN.match(v):
            raise ValueError(
                f"tenant_id '{v}' must be 'imp_t_*', 'default', or empty"
            )
        return v

    # EV6..EV8 — UEB Phase 1 envelope fields (all optional; v1 payloads unaffected)
    event_id: Optional[str] = None                              # EV6: UUIDv7 idempotency/dedup key
    schema_version: Optional[int] = Field(None, ge=1)          # EV7: monotone breaking-change marker
    # EV8: AuditSource enum value
    source: Optional[Literal["user", "system", "automation", "rbac", "mcp", "webhook"]] = None


# === UEB Event (v2 envelope) =========================================


class Event(BaseModel):
    """UEB v2 canonical Event envelope.

    Full structured envelope used by the Universal Event Bus (UEB).
    All three EV6..EV8 fields are optional so that v1 callers that
    omit them continue to work without modification.

    Fields
    ------
    type            — domain noun  (e.g. "state_changed", "invoice_paid")
    scope           — bounded context (e.g. "email", "billing")
    action          — verb  (e.g. "received", "updated")
    actor           — identity that caused the event (user_id or system id)
    tenant_id       — tenant namespace (Imperal canonical or "default")
    user_id         — owning user identity
    timestamp       — ISO-8601 UTC wall-clock
    data            — free-form payload dict
    event_id        — EV6: UUIDv7 idempotency/dedup key (optional)
    schema_version  — EV7: monotone breaking-change marker (optional)
    source          — EV8: AuditSource enum value (optional)
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    scope: str
    action: str
    actor: str
    tenant_id: str = ""
    user_id: str = ""
    timestamp: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)

    # EV6..EV8 — optional; v1 payloads that omit them remain valid
    event_id: Optional[str] = None                              # EV6: UUIDv7 idempotency/dedup key
    schema_version: Optional[int] = Field(None, ge=1)          # EV7: monotone breaking-change marker
    # EV8: AuditSource enum value
    source: Optional[Literal["user", "system", "automation", "rbac", "mcp", "webhook"]] = None


# === FunctionCall mirror =============================================

class FunctionCallModel(BaseModel):
    """Pydantic contract for `FunctionCall.to_dict()` output.

    Records a single `@chat.function` invocation inside `ChatResult`.
    Crosses platform execution boundaries — every field travels the wire.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)
    action_type: Literal["read", "write", "destructive"]
    success: bool
    # `result` is a nested ActionResult.to_dict() output — validated via the
    # broader ActionResultModel when the kernel hydrates the call record.
    result: Optional[Dict[str, Any]] = None
    intercepted: bool = False
    event: str = ""


# === ChatResult mirror ===============================================

class ChatResultModel(BaseModel):
    """Pydantic contract for `ChatResult.to_dict()` output.

    Serialized return from the kernel's typed-dispatch layer; crosses
    platform execution history on every chat turn. The on-wire keys are
    underscore-prefixed (`_handled`, `_functions_called`, ...) — the
    kernel's hub dispatcher depends on that prefix to distinguish its
    transport metadata from raw tool output. Pydantic aliases map them
    to readable Python attribute names.
    """

    # No `populate_by_name` — the wire format is the contract; only the
    # underscore-prefixed keys are accepted. Use the `ChatResult` dataclass
    # in `types/chat_result.py` for in-Python construction.
    model_config = ConfigDict(extra="forbid")

    response: str = ""
    handled: bool = Field(default=False, alias="_handled")
    functions_called: List[FunctionCallModel] = Field(
        default_factory=list, alias="_functions_called"
    )
    had_successful_action: bool = Field(default=False, alias="_had_successful_action")
    message_type: str = Field(default="text", alias="_message_type")
    action_meta: Dict[str, Any] = Field(default_factory=dict, alias="_action_meta")
    intercepted: bool = Field(default=False, alias="_intercepted")
    task_cancelled: bool = Field(default=False, alias="_task_cancelled")
    # P2 Task 27 — NarrationEmission attached when the LLM completed the
    # turn via EMIT_NARRATION_TOOL. Optional (free-form text responses and
    # parse failures leave this null). Nested schema intentionally left open
    # at the transport layer — strict shape validation is owned by the
    # kernel narration verifier + the Pydantic NarrationEmission model in
    # imperal_sdk.chat.narration.
    narration_emission: Optional[Dict[str, Any]] = Field(
        default=None, alias="_narration_emission"
    )


# === Shared validator plumbing =======================================

def _validate_against_model(
    data: Any,
    model: type,
    rule_prefix: str,
) -> List["ValidationIssue"]:
    """Run a dict through a Pydantic model, return ValidationIssue list.

    Rule-code scheme (mirrors manifest_schema):
      `{prefix}1`  root is not a JSON object
      `{prefix}2`  required field missing
      `{prefix}3`  unknown top-level field (typo detection)
      `{prefix}4`  invalid value (regex / type / enum / cross-field)
      `{prefix}5`  nested-field error (currently unused — both models
                   are flat — reserved for forward compat)
    """
    from imperal_sdk.validator import ValidationIssue

    issues: List[ValidationIssue] = []

    if not isinstance(data, dict):
        issues.append(ValidationIssue(
            rule=f"{rule_prefix}1", level="ERROR",
            message=(
                f"payload root must be a JSON object, "
                f"got {type(data).__name__}"
            ),
            fix=f"Ensure the {model.__name__} payload is a top-level {{...}} object",
        ))
        return issues

    try:
        model.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            etype = err["type"]
            msg = err["msg"]

            if etype == "missing":
                rule, fix = f"{rule_prefix}2", f"Add '{loc}' to the payload"
            elif etype == "extra_forbidden":
                rule, fix = f"{rule_prefix}3", (
                    f"Remove '{loc}' — not part of the {model.__name__} contract. "
                    f"Check for typos."
                )
            elif "." in loc:
                rule, fix = f"{rule_prefix}5", f"Fix nested value at '{loc}': {msg}"
            else:
                rule, fix = f"{rule_prefix}4", f"Fix value at '{loc}': {msg}"

            issues.append(ValidationIssue(
                rule=rule, level="ERROR",
                message=f"[{loc or 'root'}] {msg}",
                fix=fix,
            ))

    return issues


# === Public validators ===============================================

def validate_action_result_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the `ActionResult.to_dict()` contract.

    Non-raising. Returns a list of ValidationIssue entries with rule
    codes `AR1..AR5`. Empty list means the payload conforms.
    """
    return _validate_against_model(data, ActionResultModel, "AR")


def validate_event_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the platform Event envelope contract.

    Non-raising. Returns a list of ValidationIssue entries with rule
    codes `EV1..EV5`. Empty list means the envelope conforms.
    """
    return _validate_against_model(data, EventModel, "EV")


def validate_function_call_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the `FunctionCall.to_dict()` contract.

    Non-raising. Rule codes `FC1..FC5`.
    """
    return _validate_against_model(data, FunctionCallModel, "FC")


def validate_chat_result_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the `ChatResult.to_dict()` contract.

    Non-raising. Rule codes `CR1..CR5`. Accepts the underscore-prefixed
    wire format (`_handled`, `_functions_called`, ...).
    """
    return _validate_against_model(data, ChatResultModel, "CR")


# === JSON Schema exports =============================================

def _shape_schema(schema: Dict[str, Any], *, id_slug: str, title: str, description: str) -> Dict[str, Any]:
    schema["$id"] = f"https://imperal.io/schemas/{id_slug}.schema.json"
    schema["title"] = title
    schema["description"] = description
    return schema


def get_action_result_schema() -> Dict[str, Any]:
    """JSON Schema (Draft 2020-12) for `ActionResult.to_dict()`."""
    return _shape_schema(
        ActionResultModel.model_json_schema(),
        id_slug="action_result",
        title="Imperal ActionResult Payload",
        description=(
            "Canonical return-value contract for every @chat.function. "
            "Produced by `ActionResult.to_dict()`; consumed by the "
            "Imperal kernel executor, Temporal activity history, "
            "automation template resolver, and SSE delivery."
        ),
    )


def get_event_schema() -> Dict[str, Any]:
    """JSON Schema (Draft 2020-12) for platform Event envelopes.

    EV6..EV8 optional fields are normalised: the `source` property is
    flattened from Pydantic's anyOf(Literal, null) form to a clean
    ``{"type": "string", "enum": [...], "description": "..."}`` entry so
    that JSON Schema consumers can read the enum list directly without
    unwrapping anyOf.  The other EV6/EV7 optional fields (event_id,
    schema_version) are similarly flattened to their scalar types.
    """
    schema = EventModel.model_json_schema()
    props = schema.setdefault("properties", {})

    # Flatten EV6: event_id  Optional[str] → {type: string, description: ...}
    if "event_id" in props:
        props["event_id"] = {
            "type": "string",
            "description": "EV6 UUIDv7 idempotency/dedup key",
        }

    # Flatten EV7: schema_version  Optional[int] → {type: integer, minimum: 1, description: ...}
    if "schema_version" in props:
        props["schema_version"] = {
            "type": "integer",
            "minimum": 1,
            "description": "EV7 monotone breaking-change marker",
        }

    # Flatten EV8: source  Optional[Literal[...]] → {type: string, enum: [...], description: ...}
    if "source" in props:
        props["source"] = {
            "type": "string",
            "enum": ["user", "system", "automation", "rbac", "mcp", "webhook"],
            "description": "EV8 AuditSource value",
        }

    return _shape_schema(
        schema,
        id_slug="event",
        title="Imperal Platform Event Envelope",
        description=(
            "Canonical shape of Event payloads published on Redis "
            "streams and consumed by the automation engine, SSE "
            "delivery, and Panel live-refresh. Replaces the textual "
            "RPC-I1..I10 invariants with a machine-checkable contract."
        ),
    )


def get_function_call_schema() -> Dict[str, Any]:
    """JSON Schema (Draft 2020-12) for `FunctionCall.to_dict()`."""
    return _shape_schema(
        FunctionCallModel.model_json_schema(),
        id_slug="function_call",
        title="Imperal FunctionCall Record",
        description=(
            "Record of a single @chat.function invocation inside a "
            "ChatResult. Used by the kernel executor to replay, audit, "
            "and bill the chain of calls made during one chat turn."
        ),
    )


def get_chat_result_schema() -> Dict[str, Any]:
    """JSON Schema (Draft 2020-12) for `ChatResult.to_dict()`."""
    return _shape_schema(
        ChatResultModel.model_json_schema(),
        id_slug="chat_result",
        title="Imperal ChatResult Payload",
        description=(
            "Serialized return from the kernel's typed-dispatch layer — the "
            "kernel-transport form of a chat turn's output. Underscore-"
            "prefixed keys distinguish transport metadata from raw "
            "tool response. Crosses Temporal activity history."
        ),
    )


ACTION_RESULT_SCHEMA: Dict[str, Any] = get_action_result_schema()
EVENT_SCHEMA: Dict[str, Any] = get_event_schema()
FUNCTION_CALL_SCHEMA: Dict[str, Any] = get_function_call_schema()
CHAT_RESULT_SCHEMA: Dict[str, Any] = get_chat_result_schema()


__all__ = [
    # Models
    "ActionResultModel",
    "EventModel",
    "FunctionCallModel",
    "ChatResultModel",
    # Validators
    "validate_action_result_dict",
    "validate_event_dict",
    "validate_function_call_dict",
    "validate_chat_result_dict",
    # Schema getters
    "get_action_result_schema",
    "get_event_schema",
    "get_function_call_schema",
    "get_chat_result_schema",
    # Schema constants
    "ACTION_RESULT_SCHEMA",
    "EVENT_SCHEMA",
    "FUNCTION_CALL_SCHEMA",
    "CHAT_RESULT_SCHEMA",
    # Patterns
    "EVENT_TYPE_PATTERN",
]
