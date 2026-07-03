"""UI Contribution types — Panel, Widget, Command, ContextMenu, Setting, Theme.

Extensions declare UI contributions via these types. Platform renders them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_PANEL_SLOTS: frozenset[str] = frozenset({
    "center", "left", "right", "overlay", "bottom", "chat-sidebar",
})


# I-PANEL-RENDERING-CONTRACT (federal v4.1.6+):
# Single source of truth for *what the Imperal Panel host actually does*
# with each declared slot. The keys MUST equal ALLOWED_PANEL_SLOTS exactly
# (asserted by tests/test_panel_rendering_contract.py). The values are:
#
#   "permanent"      — fetched at session-init batch discovery; rendered
#                      as a persistent column. Currently: left, right.
#   "center-overlay" — fetched on demand via __panel__<id> action when the
#                      panel_id is in the host's isCenterOverlay allowlist
#                      (currently {compose, email_viewer+message_id,
#                      editor+note_id, workshop}). Renders over the chat
#                      region; chat collapses to a 380px right rail.
#   "reserved"       — accepted by the SDK validator but the frontend has
#                      no render path. @ext.panel(slot=...) is a no-op for
#                      these. Reserved for future host work.
#
# When the frontend's render path for a slot changes, BOTH this map and
# the docs table at docs.imperal.io/concepts/panels.mdx MUST be updated.
PANEL_SLOT_RENDERING_STATUS: dict[str, str] = {
    "left":         "permanent",
    "right":        "permanent",
    "center":       "center-overlay",
    "overlay":      "reserved",
    "bottom":       "reserved",
    "chat-sidebar": "reserved",
}


@dataclass
class Panel:
    """A movable UI panel contributed by an extension.

    `slot` selects which region of the host the panel renders in. The
    canonical middle-content slot is `"center"` (used by notes, mail,
    sql-db, tasks, whiteboard). `"main"` was the SDK default through
    3.3.x but was never rendered by any host — removed in 3.4.0.
    """
    id: str
    title: str
    icon: str = ""
    slot: str = "center"  # center, left, right, overlay, chat-sidebar, bottom
    component: str = ""
    default_position: int = 0
    movable: bool = True
    resizable: bool = True
    min_width: int = 200
    max_width: int | None = None
    permissions: list[str] = field(default_factory=list)
    context_trigger: str | None = None
    badge: str | None = None

    def __post_init__(self) -> None:
        if self.slot not in ALLOWED_PANEL_SLOTS:
            raise ValueError(
                f"Panel(id={self.id!r}, slot={self.slot!r}): unknown slot. "
                f"Must be one of {sorted(ALLOWED_PANEL_SLOTS)}. "
                "Note: 'main' was removed in SDK 3.4.0; use 'center' instead."
            )


@dataclass
class Widget:
    """A small UI widget embedded at injection points."""
    id: str
    slot: str  # dashboard.stats, chat.message-actions, email.toolbar, etc.
    component: str = ""
    size: str = "md"  # xs, sm, md, lg
    label: str = ""
    icon: str = ""
    permissions: list[str] = field(default_factory=list)


@dataclass
class Command:
    """A command registered in the command palette."""
    id: str
    title: str
    icon: str = ""
    shortcut: str = ""
    category: str = ""
    handler: str = ""
    when: str = ""


@dataclass
class ContextMenu:
    """A context menu item for right-click menus."""
    slot: str  # chat.message, email.message, file.item, table.row
    label: str
    icon: str = ""
    handler: str = ""
    separator_before: bool = False
    when: str = ""
    group: str = ""


@dataclass
class Setting:
    """A user-configurable setting for the extension."""
    id: str
    type: str  # string, number, boolean, secret, select, list, color, json
    label: str
    description: str = ""
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None
    options: list[dict] | None = None
    placeholder: str = ""
    group: str = ""
    admin_only: bool = False


@dataclass
class Theme:
    """Extension theme customization."""
    accent_color: str = ""
    dark_mode: bool = True
    custom_css: str = ""
    chat_bubble_style: str = "default"  # default, minimal, card
    icon_style: str = "outline"  # outline, solid, duotone
    border_radius: str = "md"  # none, sm, md, lg, full
