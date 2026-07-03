"""The sealed metered-event — the open<->closed metering interface.

Carries WHAT was consumed (dimensions), never WHAT it costs: price resolution is
the platform's (closed) concern. A unit-typed, versioned envelope so new metered
units extend it additively. (No engine/store names here — public surface.)
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_FORBIDDEN = ("base_price", "platform_fee", "cost", "model_tier", "price")


class MeteredIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    imperal_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    agency_id: str | None = None   # nullable-with-known-gap: shape carries it; do NOT trust for rollup until threaded e2e


class MeteredMeter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    unit_type: str = Field(min_length=1)   # "invocation" | (deferred) "storage"|"model"|"subscription"
    meter_version: int = 1                 # vocabulary cadence, decoupled from envelope v


class MeteredAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_id: str
    tool_name: str | None = None
    action_type: str | None = None


class MeteredEvent(BaseModel):
    """A single metered unit. DIMENSIONS only — never resolved price."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    v: Literal[1] = 1
    event_id: str = Field(min_length=1, max_length=50)
    ts: int
    identity: MeteredIdentity
    meter: MeteredMeter
    attribution: MeteredAttribution
    dimensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_price_on_open_contract(self) -> "MeteredEvent":
        for k in self.dimensions:
            if k in _FORBIDDEN:
                raise ValueError(f"price key {k!r} forbidden on the open metered event (dimensions are quantities only)")
        return self
