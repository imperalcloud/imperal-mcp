# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""JSON Schema contracts for `ctx.*` client response types.

These are the HTTP-response shapes returned from the Auth Gateway and
other Imperal-platform services to the SDK clients (`ctx.store`,
`ctx.ai`, `ctx.billing`, `ctx.storage`, `ctx.http`). Inside the SDK the
ergonomic `@dataclass` forms in `types/models.py` remain the public API;
at the HTTP boundary, these Pydantic mirrors are the enforceable
contract — they catch backend-drift the moment a service response
deviates from the declared shape.

Covered
-------
- `DocumentModel`         — `ctx.store.get/query/create/update()` response row
- `CompletionResultModel` — `ctx.ai.complete()` response
- `LimitsResultModel`     — `ctx.billing.check_limits()` response
- `SubscriptionInfoModel` — `ctx.billing.get_subscription()` response
- `BalanceInfoModel`      — `ctx.billing.get_balance()` response
- `FileInfoModel`         — `ctx.storage.upload/list()` response entry
- `HTTPResponseModel`     — `ctx.http.get/post/...()` wrapped response

Rule codes (mirrors the contracts.py M/AR/EV/FC/CR scheme):
  `DOC1..5`  Document
  `CPL1..5`  CompletionResult
  `LIM1..5`  LimitsResult
  `SUB1..5`  SubscriptionInfo
  `BAL1..5`  BalanceInfo
  `FIL1..5`  FileInfo
  `HRS1..5`  HTTPResponse

External tooling should prefer the committed static files at
`imperal_sdk/schemas/{document,completion_result,...}.schema.json`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from imperal_sdk.types.contracts import _shape_schema, _validate_against_model
from imperal_sdk.types.metered_event import MeteredEvent


# === Models ===========================================================

class DocumentModel(BaseModel):
    """Pydantic contract for `Document` — one row in the extension store."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    data: Dict[str, Any] = Field(default_factory=dict)
    extension_id: str = ""
    tenant_id: str = "default"
    created_at: str = ""
    updated_at: str = ""
    user_id: str = ""  # populated by ctx.store.query_all (1.5.23+); empty for single-user contexts


class CompletionResultModel(BaseModel):
    """Pydantic contract for `CompletionResult` — ctx.ai.complete() output."""

    model_config = ConfigDict(extra="forbid")

    text: str
    model: str = ""
    usage: Dict[str, Any] = Field(default_factory=dict)
    stop_reason: str = ""


class LimitsResultModel(BaseModel):
    """Pydantic contract for `LimitsResult` — ctx.billing.check_limits() output."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = True
    balance: int = 0
    plan: str = ""
    limits: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class SubscriptionInfoModel(BaseModel):
    """Pydantic contract for `SubscriptionInfo` — ctx.billing.get_subscription()."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = ""
    plan_name: str = ""
    status: str = ""
    period: str = "monthly"
    current_period_start: str = ""
    current_period_end: str = ""


class BalanceInfoModel(BaseModel):
    """Pydantic contract for `BalanceInfo` — ctx.billing.get_balance()."""

    model_config = ConfigDict(extra="forbid")

    balance: int = 0
    plan: str = ""
    cap: int = 0


class FileInfoModel(BaseModel):
    """Pydantic contract for `FileInfo` — ctx.storage.upload/list() entry."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    size: int = Field(default=0, ge=0)
    content_type: str = ""
    created_at: str = ""
    url: str = ""


class HTTPResponseModel(BaseModel):
    """Pydantic contract for `HTTPResponse` — ctx.http.*() wrapped response.

    The dataclass accepts `body: dict | str | bytes`; bytes cannot cross a
    JSON boundary so the schema form is `Dict | str` — the SDK's
    `HTTPResponse.json()` / `.text()` helpers convert as needed.
    """

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(..., ge=100, le=599)
    body: Union[Dict[str, Any], str, List[Any]] = ""
    headers: Dict[str, str] = Field(default_factory=dict)


# === Validators =======================================================

def validate_document_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the Document contract. Rule codes `DOC1..5`."""
    return _validate_against_model(data, DocumentModel, "DOC")


def validate_completion_result_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the CompletionResult contract. Rule codes `CPL1..5`."""
    return _validate_against_model(data, CompletionResultModel, "CPL")


def validate_limits_result_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the LimitsResult contract. Rule codes `LIM1..5`."""
    return _validate_against_model(data, LimitsResultModel, "LIM")


def validate_subscription_info_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the SubscriptionInfo contract. Rule codes `SUB1..5`."""
    return _validate_against_model(data, SubscriptionInfoModel, "SUB")


def validate_balance_info_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the BalanceInfo contract. Rule codes `BAL1..5`."""
    return _validate_against_model(data, BalanceInfoModel, "BAL")


def validate_file_info_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the FileInfo contract. Rule codes `FIL1..5`."""
    return _validate_against_model(data, FileInfoModel, "FIL")


def validate_http_response_dict(data: Any) -> List["ValidationIssue"]:
    """Validate a dict against the HTTPResponse contract. Rule codes `HRS1..5`."""
    return _validate_against_model(data, HTTPResponseModel, "HRS")


# === JSON Schema exports ==============================================

_SCHEMA_META = [
    # (model, id_slug, title, description)
    (DocumentModel, "document", "Imperal Document",
     "One row in the extension store. Returned from ctx.store.get(), "
     ".query(), .create(), .update()."),
    (CompletionResultModel, "completion_result", "Imperal CompletionResult",
     "Response from ctx.ai.complete() — text plus model/usage metadata."),
    (LimitsResultModel, "limits_result", "Imperal LimitsResult",
     "Response from ctx.billing.check_limits() — whether the user may "
     "proceed, their remaining balance, and plan details."),
    (SubscriptionInfoModel, "subscription_info", "Imperal SubscriptionInfo",
     "Response from ctx.billing.get_subscription() — plan ID/name/status "
     "and billing period."),
    (BalanceInfoModel, "balance_info", "Imperal BalanceInfo",
     "Response from ctx.billing.get_balance() — token balance, plan, cap."),
    (FileInfoModel, "file_info", "Imperal FileInfo",
     "Response from ctx.storage.upload() and .list() — storage path, "
     "size, MIME, and signed URL."),
    (HTTPResponseModel, "http_response", "Imperal HTTPResponse",
     "Wrapped response from ctx.http.* — status code, body (dict/str/list), "
     "and headers. Bytes bodies are not JSON-boundary-safe and are "
     "excluded from the schema; use HTTPResponse.text()/json() locally."),
]


def get_document_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[0]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_completion_result_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[1]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_limits_result_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[2]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_subscription_info_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[3]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_balance_info_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[4]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_file_info_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[5]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_http_response_schema() -> Dict[str, Any]:
    m, s, t, d = _SCHEMA_META[6]
    return _shape_schema(m.model_json_schema(), id_slug=s, title=t, description=d)


def get_metered_event_schema() -> Dict[str, Any]:
    """JSON Schema for `MeteredEvent` — the open<->closed metering interface."""
    return _shape_schema(
        MeteredEvent.model_json_schema(),
        id_slug="metered_event",
        title="Imperal MeteredEvent",
        description=(
            "A single metered unit crossing the open<->closed boundary. "
            "Carries dimensions (quantities) only — price resolution is the "
            "platform's (closed) concern."
        ),
    )


DOCUMENT_SCHEMA: Dict[str, Any] = get_document_schema()
COMPLETION_RESULT_SCHEMA: Dict[str, Any] = get_completion_result_schema()
LIMITS_RESULT_SCHEMA: Dict[str, Any] = get_limits_result_schema()
SUBSCRIPTION_INFO_SCHEMA: Dict[str, Any] = get_subscription_info_schema()
BALANCE_INFO_SCHEMA: Dict[str, Any] = get_balance_info_schema()
FILE_INFO_SCHEMA: Dict[str, Any] = get_file_info_schema()
HTTP_RESPONSE_SCHEMA: Dict[str, Any] = get_http_response_schema()
METERED_EVENT_SCHEMA: Dict[str, Any] = get_metered_event_schema()


__all__ = [
    # Models
    "DocumentModel", "CompletionResultModel", "LimitsResultModel",
    "SubscriptionInfoModel", "BalanceInfoModel", "FileInfoModel",
    "HTTPResponseModel",
    # Validators
    "validate_document_dict", "validate_completion_result_dict",
    "validate_limits_result_dict", "validate_subscription_info_dict",
    "validate_balance_info_dict", "validate_file_info_dict",
    "validate_http_response_dict",
    # Schema getters
    "get_document_schema", "get_completion_result_schema",
    "get_limits_result_schema", "get_subscription_info_schema",
    "get_balance_info_schema", "get_file_info_schema",
    "get_http_response_schema", "get_metered_event_schema",
    # Schema constants
    "DOCUMENT_SCHEMA", "COMPLETION_RESULT_SCHEMA", "LIMITS_RESULT_SCHEMA",
    "SUBSCRIPTION_INFO_SCHEMA", "BALANCE_INFO_SCHEMA", "FILE_INFO_SCHEMA",
    "HTTP_RESPONSE_SCHEMA", "METERED_EVENT_SCHEMA",
]
