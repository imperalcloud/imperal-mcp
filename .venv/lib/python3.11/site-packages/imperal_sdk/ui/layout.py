"""Imperal SDK · Layout UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode


def Stack(
    children: list[UINode],
    direction: str = "v",
    gap: int = 3,
    wrap: bool | None = None,
    align: str = "",
    justify: str = "",
    sticky: bool = False,
    className: str = "",
) -> UINode:
    """Flex layout — vertical or horizontal.

    wrap: tri-state flex-wrap. ``None`` (default) → emit no prop, Panel applies
    direction-specific default (horizontal auto-wraps, vertical does not).
    ``True`` / ``False`` → explicit override, Panel respects as-is. Pass
    ``wrap=False`` on a horizontal Stack to opt out of auto-wrap.
    align/justify: flex alignment.
    sticky: pin to top of scroll container (useful for toolbars).
    className: custom CSS classes (overrides default system padding).
    """
    props: dict[str, Any] = {"children": children, "direction": direction, "gap": gap}
    if wrap is not None: props["wrap"] = wrap
    if align: props["align"] = align
    if justify: props["justify"] = justify
    if sticky: props["sticky"] = True
    if className: props["className"] = className
    return UINode(type="Stack", props=props)


def Grid(children: list[UINode], columns: int = 2, gap: int = 3) -> UINode:
    """CSS Grid layout."""
    return UINode(type="Grid", props={"children": children, "columns": columns, "gap": gap})


def Tabs(tabs: list[dict], default_tab: int = 0) -> UINode:
    """Tabbed content. Each tab: {"label": str, "content": UINode}."""
    return UINode(type="Tabs", props={"tabs": tabs, "default_tab": default_tab})


def Page(children: list[UINode], title: str = "", subtitle: str = "") -> UINode:
    """Top-level page container."""
    props: dict[str, Any] = {"children": children}
    if title: props["title"] = title
    if subtitle: props["subtitle"] = subtitle
    return UINode(type="Page", props=props)


def Section(children: list[UINode], title: str = "", collapsible: bool = False) -> UINode:
    """Grouped section with optional title and collapsible behaviour."""
    props: dict[str, Any] = {"children": children, "collapsible": collapsible}
    if title: props["title"] = title
    return UINode(type="Section", props=props)


def Row(children: list[UINode], gap: int = 3) -> UINode:
    """Horizontal flex row — alias for Stack(direction='h')."""
    return UINode(type="Stack", props={"children": children, "direction": "h", "gap": gap})


def Column(children: list[UINode], gap: int = 3) -> UINode:
    """Vertical flex column — alias for Stack(direction='v')."""
    return UINode(type="Stack", props={"children": children, "direction": "v", "gap": gap})


def Accordion(sections: list[dict], allow_multiple: bool = False) -> UINode:
    """Collapsible accordion. Each section: {"id", "title", "children"}."""
    return UINode(type="Accordion", props={"sections": sections, "allow_multiple": allow_multiple})
