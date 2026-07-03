"""Events & Tickets family — venue, capacity, RSVP, ticketing, admission, agenda,
cancellation, calendar feeds. Namespace event.*"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Eventful(BaseModel):
    venue: str | None = _facet_field(role="event.venue")
    # event_organizer / event_host: prefixed to avoid collision with people.organizer / people.host
    event_organizer: Ref | None = _facet_field(role="event.event_organizer")
    event_host: Ref | None = _facet_field(role="event.event_host")
    event_type: str | None = _facet_field(role="event.event_type")


class Capacity(BaseModel):
    capacity_total: int | None = _facet_field(role="event.capacity_total")
    capacity_remaining: int | None = _facet_field(role="event.capacity_remaining")
    registered_count: int | None = _facet_field(role="event.registered_count")
    waitlist_count: int | None = _facet_field(role="event.waitlist_count")
    is_sold_out: bool | None = _facet_field(role="event.is_sold_out")


class RSVP(BaseModel):
    rsvp_state: Literal["going", "maybe", "declined", "invited", "waitlisted"] | None = _facet_field(role="event.rsvp_state")
    checked_in: bool | None = _facet_field(role="event.checked_in")
    is_no_show: bool | None = _facet_field(role="event.is_no_show")
    check_in_method: Literal["qr", "nfc", "manual", "geofence"] | None = _facet_field(role="event.check_in_method")


class Ticketed(BaseModel):
    ticket_type: str | None = _facet_field(role="event.ticket_type")
    seat: str | None = _facet_field(role="event.seat")
    barcode: str | None = _facet_field(role="event.barcode")
    # ticket_price: prefixed to avoid collision with money.Priced price fields
    ticket_price: Decimal | None = _facet_field(role="event.ticket_price")


class AdmissionPolicy(BaseModel):
    min_age: int | None = _facet_field(role="event.min_age")
    dress_code: str | None = _facet_field(role="event.dress_code")
    requires_id: bool | None = _facet_field(role="event.requires_id")
    prohibited_items: list[str] | None = _facet_field(role="event.prohibited_items")
    doors_open_at: datetime | None = _facet_field(role="event.doors_open_at")


class AgendaSlot(BaseModel):
    parent_event: Ref | None = _facet_field(role="event.parent_event")
    track: str | None = _facet_field(role="event.track")
    session_type: Literal["talk", "workshop", "break", "keynote", "panel", "networking"] | None = _facet_field(role="event.session_type")
    order_index: int | None = _facet_field(role="event.order_index")
    speakers: list[Ref] | None = _facet_field(role="event.speakers")


class Cancellation(BaseModel):
    is_cancelled: bool | None = _facet_field(role="event.is_cancelled")
    refund_policy: str | None = _facet_field(role="event.refund_policy")
    refund_deadline: datetime | None = _facet_field(role="event.refund_deadline")
    is_refundable: bool | None = _facet_field(role="event.is_refundable")


class CalendarFeed(BaseModel):
    ical_uid: str | None = _facet_field(role="event.ical_uid")
    ics_url: str | None = _facet_field(role="event.ics_url")
    feed_url: str | None = _facet_field(role="event.feed_url")
    calendar_name: str | None = _facet_field(role="event.calendar_name")
    calendar_color: str | None = _facet_field(role="event.calendar_color")
