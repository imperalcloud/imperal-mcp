"""Time family — timestamps, scheduling, duration, recurrence, booking. Namespace time.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.field import _facet_field


class Timestamped(BaseModel):
    created_at: datetime | None = _facet_field(role="time.created_at")
    updated_at: datetime | None = _facet_field(role="time.updated_at")
    deleted_at: datetime | None = _facet_field(role="time.deleted_at")


class Schedulable(BaseModel):
    start_at: datetime | None = _facet_field(role="time.start_at")
    end_at: datetime | None = _facet_field(role="time.end_at")
    due_at: datetime | None = _facet_field(role="time.due_at")
    all_day: bool | None = _facet_field(role="time.all_day")
    timezone: str | None = _facet_field(role="time.timezone")


class Duration(BaseModel):
    duration_s: float | None = _facet_field(role="time.duration_s")
    duration_display_unit: str | None = _facet_field(role="time.duration_display_unit")


class Recurring(BaseModel):
    recurrence_rule: str | None = _facet_field(role="time.recurrence_rule")
    recurrence_until: datetime | None = _facet_field(role="time.recurrence_until")
    recurrence_count: int | None = _facet_field(role="time.recurrence_count")
    is_recurring_master: bool | None = _facet_field(role="time.is_recurring_master")
    next_occurrence_at: datetime | None = _facet_field(role="time.next_occurrence_at")
    recurrence_anchor: Literal["due_date", "completion_date"] | None = _facet_field(role="time.recurrence_anchor")


class Booked(BaseModel):
    booked_at: datetime | None = _facet_field(role="time.booked_at")
    check_in_at: datetime | None = _facet_field(role="time.check_in_at")
    check_out_at: datetime | None = _facet_field(role="time.check_out_at")
    cancelled_at: datetime | None = _facet_field(role="time.cancelled_at")
    cancellation_deadline: datetime | None = _facet_field(role="time.cancellation_deadline")
