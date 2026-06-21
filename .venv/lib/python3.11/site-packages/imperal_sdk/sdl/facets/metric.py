"""Analytics & Metrics family — aggregation, time series, trends, confidence, thresholds.
Namespace metric.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Aggregated(BaseModel):
    aggregation: str | None = _facet_field(role="metric.aggregation")
    window_start: datetime | None = _facet_field(role="metric.window_start")
    window_end: datetime | None = _facet_field(role="metric.window_end")
    granularity: str | None = _facet_field(role="metric.granularity")
    fill_policy: Literal["none", "zero", "previous", "linear", "null"] | None = _facet_field(role="metric.fill_policy")


class TimeSeriesPoint(BaseModel):
    # ts_timestamp / ts_value: prefixed to avoid collision with quantity.value
    ts_timestamp: datetime | None = _facet_field(role="metric.ts_timestamp")
    ts_value: float | None = _facet_field(role="metric.ts_value")


class Trended(BaseModel):
    delta: float | None = _facet_field(role="metric.delta")
    change_pct: float | None = _facet_field(role="metric.change_pct")
    trend: Literal["up", "down", "flat"] | None = _facet_field(role="metric.trend")
    # trend_period: prefixed to avoid collision with a generic "period" field if one lands
    trend_period: str | None = _facet_field(role="metric.trend_period")


class Confident(BaseModel):
    confidence_level: float | None = _facet_field(role="metric.confidence_level")
    ci_lower: float | None = _facet_field(role="metric.ci_lower")
    ci_upper: float | None = _facet_field(role="metric.ci_upper")
    margin_of_error: float | None = _facet_field(role="metric.margin_of_error")
    p_value: float | None = _facet_field(role="metric.p_value")
    is_significant: bool | None = _facet_field(role="metric.is_significant")


class Threshold(BaseModel):
    # threshold_target: prefixed to avoid collision with quantity.Range.target
    threshold_target: float | None = _facet_field(role="metric.threshold_target")
    threshold: float | None = _facet_field(role="metric.threshold")
    breached: bool | None = _facet_field(role="metric.breached")


class Dimensioned(BaseModel):
    dimensions: dict[str, str] | None = _facet_field(role="metric.dimensions")
