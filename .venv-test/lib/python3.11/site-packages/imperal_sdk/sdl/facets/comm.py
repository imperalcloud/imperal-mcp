"""Communication family — conversations, threads, message state, reactions, calls, drafts.
Namespace comm.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Conversational(BaseModel):
    conversation_ref: Ref | None = _facet_field(role="comm.conversation_ref")
    conversation_type: Literal["dm", "group", "channel", "thread", "mailbox", "broadcast"] | None = _facet_field(role="comm.conversation_type")
    channel_name: str | None = _facet_field(role="comm.channel_name")
    is_group: bool | None = _facet_field(role="comm.is_group")
    # collision-avoidance: field name prefixed to avoid clash with Participants.participant_count
    conversation_participant_count: int | None = _facet_field(role="comm.participant_count")
    last_message_at: datetime | None = _facet_field(role="comm.last_message_at")
    last_preview: str | None = _facet_field(role="comm.last_preview")


class Threaded(BaseModel):
    thread_ref: Ref | None = _facet_field(role="comm.thread_ref")
    reply_to_message: Ref | None = _facet_field(role="comm.reply_to_message")
    root: Ref | None = _facet_field(role="comm.root")
    depth: int | None = _facet_field(role="comm.depth")


class MessageState(BaseModel):
    direction: Literal["incoming", "outgoing"] | None = _facet_field(role="comm.direction")
    is_read: bool | None = _facet_field(role="comm.is_read")
    delivery_state: Literal["sending", "sent", "delivered", "read", "failed"] | None = _facet_field(role="comm.delivery_state")
    sent_at: datetime | None = _facet_field(role="comm.sent_at")
    edited_at: datetime | None = _facet_field(role="comm.edited_at")
    is_from_me: bool | None = _facet_field(role="comm.is_from_me")


class Reactable(BaseModel):
    reactions: dict[str, int] | None = _facet_field(role="comm.reactions")
    reaction_count: int | None = _facet_field(role="comm.reaction_count")
    my_reactions: list[str] | None = _facet_field(role="comm.my_reactions")


class Callable(BaseModel):
    call_direction: Literal["incoming", "outgoing", "missed"] | None = _facet_field(role="comm.call_direction")
    call_type: Literal["voice", "video", "screen_share", "conference"] | None = _facet_field(role="comm.call_type")
    call_state: Literal["ringing", "connecting", "active", "ended", "declined", "missed", "no_answer", "busy"] | None = _facet_field(role="comm.call_state")
    answered: bool | None = _facet_field(role="comm.answered")
    end_reason: Literal["hangup", "declined", "no_answer", "busy", "failed", "network"] | None = _facet_field(role="comm.end_reason")
    ring_duration_s: int | None = _facet_field(role="comm.ring_duration_s")


class Draftable(BaseModel):
    is_draft: bool | None = _facet_field(role="comm.is_draft")
    scheduled_send_at: datetime | None = _facet_field(role="comm.scheduled_send_at")
    last_saved_at: datetime | None = _facet_field(role="comm.last_saved_at")
    is_auto_generated: bool | None = _facet_field(role="comm.is_auto_generated")
