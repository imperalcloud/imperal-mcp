"""Imperal SDK · Interactive UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction


def Button(
    label: str,
    variant: str = "primary",
    on_click: UIAction | None = None,
    disabled: bool = False,
    size: str = "md",
    full_width: bool = False,
    icon: str = "",
) -> UINode:
    """Clickable button. size: sm/md/lg. icon: Lucide icon name."""
    props: dict[str, Any] = {
        "label": label, "variant": variant, "disabled": disabled, "size": size,
    }
    if full_width: props["full_width"] = True
    if on_click: props["on_click"] = on_click
    if icon: props["icon"] = icon
    return UINode(type="Button", props=props)


def Card(
    title: str = "",
    subtitle: str = "",
    content: UINode | None = None,
    footer: UINode | None = None,
    on_click: UIAction | None = None,
) -> UINode:
    """Container card with optional title, subtitle, content and footer slots."""
    props: dict[str, Any] = {}
    if title: props["title"] = title
    if subtitle: props["subtitle"] = subtitle
    if content: props["content"] = content
    if footer: props["footer"] = footer
    if on_click: props["on_click"] = on_click
    return UINode(type="Card", props=props)


def Menu(items: list[dict], trigger: UINode | None = None) -> UINode:
    """Dropdown menu. Each item: {"label", "icon", "on_click", "separator"}."""
    props: dict[str, Any] = {"items": items}
    if trigger: props["trigger"] = trigger
    return UINode(type="Menu", props=props)


def Dialog(
    title: str,
    content: UINode | None = None,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    on_confirm: UIAction | None = None,
) -> UINode:
    """Modal dialog with confirm/cancel actions."""
    props: dict[str, Any] = {
        "title": title,
        "confirm_label": confirm_label,
        "cancel_label": cancel_label,
    }
    if content: props["content"] = content
    if on_confirm: props["on_confirm"] = on_confirm
    return UINode(type="Dialog", props=props)


def Tooltip(content: str, children: UINode | None = None) -> UINode:
    """Hover tooltip wrapping an optional child node."""
    props: dict[str, Any] = {"content": content}
    if children: props["children"] = children
    return UINode(type="Tooltip", props=props)


def Link(
    label: str = "",
    href: str = "",
    on_click: UIAction | None = None,
    *,
    text: str = "",
) -> UINode:
    """Hyperlink — navigates via href or fires on_click action.

    The visible text can be passed as either ``label`` (canonical) or
    ``text`` (alias matching the HTML/JSX `<a>text</a>` mental model).
    Exactly one must be provided; ``label`` wins if both are set.
    """
    resolved = label or text
    if not resolved:
        raise TypeError("ui.Link requires a 'label' (or 'text' alias)")
    props: dict[str, Any] = {"label": resolved}
    if href: props["href"] = href
    if on_click: props["on_click"] = on_click
    return UINode(type="Link", props=props)


def SlideOver(
    title: str,
    children: list[UINode] | None = None,
    subtitle: str = "",
    open: bool = True,
    width: str = "md",
    on_close: UIAction | None = None,
) -> UINode:
    """Side panel sliding in from right. width: sm/md/lg/xl."""
    props: dict[str, Any] = {
        "title": title,
        "subtitle": subtitle,
        "open": open,
        "width": width,
    }
    if children: props["children"] = children
    if on_close: props["on_close"] = on_close
    return UINode(type="SlideOver", props=props)
