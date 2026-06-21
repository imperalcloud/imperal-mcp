"""Imperal SDK · Feedback UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction


def Alert(message: str, title: str = "", type: str = "info") -> UINode:
    """Alert banner — info/success/warn/error."""
    return UINode(type="Alert", props={"message": message, "title": title, "type": type})


def Progress(value: int, label: str = "", variant: str = "bar", color: str = "") -> UINode:
    """Progress bar or circular indicator. value: 0-100.
    color: one of 'blue' (default), 'green', 'red', 'yellow', 'purple'. Empty string
    uses the default blue. Use semantic colors for status bars (e.g. red for
    over-budget, green for healthy).
    """
    props = {"value": value, "label": label, "variant": variant}
    if color:
        props["color"] = color
    return UINode(type="Progress", props=props)


def Chart(
    data: list[dict],
    type: str = "line",
    x_key: str = "name",
    height: int = 200,
    colors: dict[str, str] | None = None,
    y2_keys: list[str] | None = None,
) -> UINode:
    """Chart — line/bar/pie using Recharts.

    colors : optional mapping ``{series_key: color}`` (CSS color or hex). Series not
             listed fall through to the default PALETTE.
    y2_keys : keys in ``data`` that should render on a secondary Y-axis (right side).
              Use for mixed-scale metrics (e.g. spend $ on left, clicks on right).
    """
    props: dict = {"chart_type": type, "data": data, "x_key": x_key, "height": height}
    # Build series list when colors is provided so React receives per-key color.
    if colors and data:
        keys = [k for k in data[0].keys() if k != x_key]
        props["series"] = [
            {"key": k, "label": k, "color": colors[k]} if k in colors else {"key": k, "label": k}
            for k in keys
        ]
    if y2_keys:
        props["y2_keys"] = list(y2_keys)
    return UINode(type="Chart", props=props)


def Loading(message: str = "Loading...", variant: str = "spinner") -> UINode:
    """Loading state indicator. variant: spinner/skeleton/dots."""
    return UINode(type="Loading", props={"message": message, "variant": variant})


def Error(message: str, title: str = "Error", retry: UIAction | None = None) -> UINode:
    """Error state with optional retry action."""
    props: dict[str, Any] = {"message": message, "title": title}
    if retry: props["retry"] = retry
    return UINode(type="Error", props=props)
