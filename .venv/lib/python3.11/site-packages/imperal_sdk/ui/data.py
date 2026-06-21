"""Imperal SDK · Data Display UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction


def Badge(label: str = "", value: Any = None, color: str = "gray") -> UINode:
    """Colored badge/pill."""
    return UINode(type="Badge", props={"label": label, "value": value, "color": color})


def Avatar(fallback: str = "?", src: str = "", size: str = "md") -> UINode:
    """Avatar with image or fallback initial."""
    return UINode(type="Avatar", props={"fallback": fallback, "src": src, "size": size})


def Stat(label: str, value: Any, trend: str = "", icon: str = "", color: str = "blue") -> UINode:
    """Metric card — label + value + optional trend."""
    return UINode(type="Stat", props={"label": label, "value": value, "trend": trend, "icon": icon, "color": color})


def ListItem(
    id: str,
    title: str,
    subtitle: str = "",
    meta: str = "",
    avatar: UINode | None = None,
    badge: UINode | None = None,
    selected: bool = False,
    on_click: UIAction | None = None,
    actions: list[dict] | None = None,
    draggable: bool = False,
    droppable: bool = False,
    on_drop: UIAction | None = None,
    icon: str = "",
    expandable: bool = False,
    expanded_content: list[UINode] | None = None,
) -> UINode:
    """Single list entry — used inside List.

    actions: hover actions, e.g. [{"icon": "Trash2", "on_click": Call(...), "confirm": "Delete?"}]
    expandable: if True, clicking toggles expanded_content instead of firing on_click.
    expanded_content: list of UINodes rendered when expanded.
    """
    props: dict[str, Any] = {"id": id, "title": title}
    if subtitle: props["subtitle"] = subtitle
    if meta: props["meta"] = meta
    if avatar: props["avatar"] = avatar
    if badge: props["badge"] = badge
    if selected: props["selected"] = selected
    if on_click: props["on_click"] = on_click
    if actions: props["actions"] = actions
    if draggable: props["draggable"] = draggable
    if droppable: props["droppable"] = droppable
    if on_drop: props["on_drop"] = on_drop
    if icon: props["icon"] = icon
    if expandable: props["expandable"] = expandable
    if expanded_content: props["expanded_content"] = expanded_content
    return UINode(type="ListItem", props=props)


def List(
    items: list[UINode],
    searchable: bool = False,
    grouped_by: str = "",
    page_size: int = 0,
    on_end_reached: UIAction | None = None,
    selectable: bool = False,
    bulk_actions: list[dict] | None = None,
    total_items: int = 0,
    extra_info: str = "",
) -> UINode:
    """Scrollable list of ListItems. Searchable + auto-paginated.

    page_size: items per page. 0 = no pagination (show all).
    on_end_reached: action fired when user scrolls to bottom (infinite scroll).
    selectable: enable multi-select with checkboxes on hover.
    bulk_actions: buttons for bulk operations. Each: {"label", "icon", "action": Call(...)}.
        Selected item IDs are injected as 'message_ids' param.
    total_items: total number of items across all pages (for Paginator display).
    extra_info: extra text in Paginator footer (e.g. "3 unread").
    """
    props: dict[str, Any] = {"items": items, "searchable": searchable, "grouped_by": grouped_by}
    if page_size > 0: props["page_size"] = page_size
    if on_end_reached: props["on_end_reached"] = on_end_reached
    if selectable: props["selectable"] = selectable
    if bulk_actions: props["bulk_actions"] = bulk_actions
    if total_items > 0: props["total_items"] = total_items
    if extra_info: props["extra_info"] = extra_info
    return UINode(type="List", props=props)


def DataColumn(key: str, label: str, sortable: bool = True, width: str = "",
               editable: bool = False, edit_type: str = "text") -> dict:
    """Column definition for DataTable. Returns plain dict (not UINode).

    editable: enable inline cell editing for this column.
    edit_type: "text" for text input, "toggle" for boolean toggle.
    """
    col: dict = {"key": key, "label": label, "sortable": sortable}
    if width: col["width"] = width
    if editable: col["editable"] = editable; col["edit_type"] = edit_type
    return col


def DataTable(columns: list[dict], rows: list[dict],
              on_row_click: UIAction | None = None,
              on_cell_edit: UIAction | None = None) -> UINode:
    """Sortable data table with optional inline cell editing."""
    props: dict[str, Any] = {"columns": columns, "rows": rows}
    if on_row_click: props["on_row_click"] = on_row_click
    if on_cell_edit: props["on_cell_edit"] = on_cell_edit
    return UINode(type="DataTable", props=props)


def Stats(children: list[UINode], columns: int = 0) -> UINode:
    """Horizontal grid of Stat cards. columns=0 means auto."""
    props: dict[str, Any] = {"children": children}
    if columns > 0: props["columns"] = columns
    return UINode(type="Stats", props=props)


def Timeline(items: list[dict]) -> UINode:
    """Vertical timeline. Each item: {"title", "description", "time", "icon", "color"}."""
    return UINode(type="Timeline", props={"items": items})


def Tree(nodes: list[dict]) -> UINode:
    """Hierarchical tree view. Each node: {"id", "label", "children": [...], "icon"}."""
    return UINode(type="Tree", props={"nodes": nodes})


def KeyValue(items: list[dict], columns: int = 1) -> UINode:
    """Key-value pairs grid. Each item: {"key", "value"}."""
    return UINode(type="KeyValue", props={"items": items, "columns": columns})
