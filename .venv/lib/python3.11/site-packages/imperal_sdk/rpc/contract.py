"""W2 envelope schema for Fast-RPC between auth-gw and kernel.

Spec: superpowers/specs/2026-04-27-w2-pydantic-rpc-design.md §5.1.

The envelope carries a `v: Literal[1]` discriminator so future evolution
goes through a Pydantic discriminated union (RpcRequestV1 | RpcRequestV2 | …)
without breaking the wire.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ENVELOPE_VERSION: Literal[1] = 1


class RpcStatus(StrEnum):
    """Outcome of a fast-RPC dispatch."""

    SUCCESS = "success"
    ERROR = "error"


class RpcErrorCategory(StrEnum):
    """Typed error categorisation that drives auth-gw fallback decisions.

    See spec §7.1 for the action table per category.
    """

    APPLICATION = "application"            # extension raised; do NOT fallback
    INFRASTRUCTURE = "infrastructure"      # Redis/network/worker; DO fallback
    TIMEOUT = "timeout"                    # deadline exceeded; DO fallback
    SCHEMA_VIOLATION = "schema_violation"  # malformed envelope; DO fallback
    TENANT_MISMATCH = "tenant_mismatch"    # I2 violation; do NOT fallback (security)


class RpcError(BaseModel):
    """Typed error embedded inside RpcReply when status == ERROR."""

    model_config = ConfigDict(frozen=True)

    category: RpcErrorCategory
    message: str
    retryable: bool


class RpcRequest(BaseModel):
    """Request envelope sent via XADD to ``imperal:rpc:extension_call``.

    Field semantics map 1:1 onto the live wire format documented in
    ``2026-04-18-fast-rpc-redis-streams-design.md`` §4.1. The ``v`` field
    is the only addition introduced by W2 and defaults to 1 for callers
    that do not specify it explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    v: Literal[1] = ENVELOPE_VERSION
    corr_id: str = Field(min_length=16, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    agency_id: str | None = None
    email: str
    role: str
    scopes: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    app_id: str
    function: str
    params: dict[str, Any] = Field(default_factory=dict)
    reply_list: str
    deadline_ns: int
    submitted_at_ns: int


class RpcReply(BaseModel):
    """Reply envelope LPUSH'd to ``imperal:rpc:reply:{corr_id}``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    v: Literal[1] = ENVELOPE_VERSION
    corr_id: str = Field(min_length=16, max_length=64)
    status: RpcStatus
    result: dict[str, Any] | None = None
    worker_id: str
    started_at_ns: int
    finished_at_ns: int
    error: RpcError | None = None

    @model_validator(mode="after")
    def _check_status_error_consistency(self) -> "RpcReply":
        if self.status == RpcStatus.ERROR and self.error is None:
            raise ValueError("RpcReply with status=ERROR must include an error")
        if self.status == RpcStatus.SUCCESS and self.error is not None:
            raise ValueError("RpcReply with status=SUCCESS must not include an error")
        return self
