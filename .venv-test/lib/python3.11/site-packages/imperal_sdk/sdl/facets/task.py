"""Tasks & Workflow family — priority, progress, completion, blocking, dependencies,
boards, checklists, workflow state, approvals, estimates. Namespace task.*"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from imperal_sdk.sdl.entity import Ref
from imperal_sdk.sdl.field import _facet_field


class Prioritized(BaseModel):
    priority: Literal["low", "medium", "high", "urgent"] | None = _facet_field(role="task.priority")
    urgency: int | None = _facet_field(role="task.urgency")
    severity: Literal["info", "minor", "major", "critical"] | None = _facet_field(role="task.severity")


class Progress(BaseModel):
    progress: float | None = _facet_field(role="task.progress")
    done_count: int | None = _facet_field(role="task.done_count")
    total_count: int | None = _facet_field(role="task.total_count")


class Completable(BaseModel):
    is_done: bool | None = _facet_field(role="task.is_done")
    completed_at: datetime | None = _facet_field(role="task.completed_at")
    completed_by: Ref | None = _facet_field(role="task.completed_by")
    resolution: Literal[
        "completed", "wont_do", "duplicate", "cannot_reproduce", "obsolete", "deferred"
    ] | None = _facet_field(role="task.resolution")


class Blockable(BaseModel):
    is_blocked: bool | None = _facet_field(role="task.is_blocked")
    blocked_reason: str | None = _facet_field(role="task.blocked_reason")
    blocked_since: datetime | None = _facet_field(role="task.blocked_since")
    waiting_on: Ref | None = _facet_field(role="task.waiting_on")


class Dependencies(BaseModel):
    blocks: list[Ref] | None = _facet_field(role="task.blocks")
    blocked_by: list[Ref] | None = _facet_field(role="task.blocked_by")
    related: list[Ref] | None = _facet_field(role="task.related")


class Boarded(BaseModel):
    board: Ref | None = _facet_field(role="task.board")
    column: str | None = _facet_field(role="task.column")
    swimlane: str | None = _facet_field(role="task.swimlane")
    position: int | None = _facet_field(role="task.position")


class Checklist(BaseModel):
    checklist_items: list[dict] | None = _facet_field(role="task.checklist_items")
    checked_count: int | None = _facet_field(role="task.checked_count")
    checklist_total: int | None = _facet_field(role="task.checklist_total")


class WorkflowState(BaseModel):
    state: str | None = _facet_field(role="task.state")
    allowed_transitions: list[str] | None = _facet_field(role="task.allowed_transitions")
    entered_state_at: datetime | None = _facet_field(role="task.entered_state_at")


class Approvable(BaseModel):
    approval_status: Literal[
        "draft", "pending", "approved", "rejected", "changes_requested"
    ] | None = _facet_field(role="task.approval_status")
    approver: Ref | None = _facet_field(role="task.approver")
    decided_at: datetime | None = _facet_field(role="task.decided_at")
    decision_note: str | None = _facet_field(role="task.decision_note")


class Estimable(BaseModel):
    estimate_s: int | None = _facet_field(role="task.estimate_s")
    spent_s: int | None = _facet_field(role="task.spent_s")
    remaining_s: int | None = _facet_field(role="task.remaining_s")
