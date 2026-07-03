"""People & Identity family — authorship, assignment, participants, correspondents,
contact points, presence. Namespace people.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Authorship(BaseModel):
    creator: Ref | None = _facet_field(role="people.creator")
    author: Ref | None = _facet_field(role="people.author")
    owner: Ref | None = _facet_field(role="people.owner")
    last_editor: Ref | None = _facet_field(role="people.last_editor")
    editors: list[Ref] | None = _facet_field(role="people.editors")
    contributors: list[Ref] | None = _facet_field(role="people.contributors")


class Assignable(BaseModel):
    assignee: Ref | None = _facet_field(role="people.assignee")
    assignees: list[Ref] | None = _facet_field(role="people.assignees")
    reviewer: Ref | None = _facet_field(role="people.reviewer")
    reviewers: list[Ref] | None = _facet_field(role="people.reviewers")
    team: Ref | None = _facet_field(role="people.team")
    delegated_by: Ref | None = _facet_field(role="people.delegated_by")
    assigned_at: datetime | None = _facet_field(role="people.assigned_at")


class Participants(BaseModel):
    members: list[Ref] | None = _facet_field(role="people.members")
    admins: list[Ref] | None = _facet_field(role="people.admins")
    host: Ref | None = _facet_field(role="people.host")
    organizer: Ref | None = _facet_field(role="people.organizer")
    participant_count: int | None = _facet_field(role="people.participant_count")
    active_now: list[Ref] | None = _facet_field(role="people.active_now")
    typing: list[Ref] | None = _facet_field(role="people.typing")
    join_state: Literal["member", "invited", "requested", "left", "removed", "banned"] | None = _facet_field(role="people.join_state")


class Correspondents(BaseModel):
    sender: Ref | None = _facet_field(role="people.sender")
    recipients_to: list[Ref] | None = _facet_field(role="people.recipients_to")
    recipients_cc: list[Ref] | None = _facet_field(role="people.recipients_cc")
    recipients_bcc: list[Ref] | None = _facet_field(role="people.recipients_bcc")
    reply_to: list[Ref] | None = _facet_field(role="people.reply_to")
    recipient_count: int | None = _facet_field(role="people.recipient_count")


class ContactPoints(BaseModel):
    emails: list[str] | None = _facet_field(role="people.emails")
    phones: list[str] | None = _facet_field(role="people.phones")
    social_handles: dict[str, str] | None = _facet_field(role="people.social_handles")
    website_url: str | None = _facet_field(role="people.website_url")
    preferred_channel: Literal["email", "phone", "sms", "chat"] | None = _facet_field(role="people.preferred_channel")


class Presence(BaseModel):
    online_status: Literal["online", "away", "busy", "dnd", "offline", "invisible"] | None = _facet_field(role="people.online_status")
    status_message: str | None = _facet_field(role="people.status_message")
    status_emoji: str | None = _facet_field(role="people.status_emoji")
    last_seen_at: datetime | None = _facet_field(role="people.last_seen_at")
    active_until: datetime | None = _facet_field(role="people.active_until")
