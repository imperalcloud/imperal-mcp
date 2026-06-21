"""Imperal SDK · Graph UI Component (Cytoscape-backed).

Interactive entity/relationship graph visualisation. Accepts either
Cytoscape API format (nodes/edges with `{data: {...}}` wrapper — as
returned by Cases API `/graph`) or flat dicts. Server-side unwrap keeps
the wire payload lean and the Panel renderer simple.

Typical usage::

    from imperal_sdk import ui

    ui.Graph(
        nodes=payload["nodes"],  # [{"data": {"id": "1", "label": "...", ...}}, ...]
        edges=payload["edges"],  # [{"data": {"id": "e1", "source": "1", "target": "2", ...}}, ...]
        layout="cose-bilkent",
        height=700,
        color_by="type",
    )

Layout options:
    - cose-bilkent: physics-based force-directed (default, best for forensic cases)
    - circle: entities arranged in circle
    - grid: rigid grid layout
    - breadthfirst: hierarchical
    - concentric: centrality-based rings

Performance: designed for up to ~5000 nodes. Above that, filter upstream
(e.g. Cases API `max_nodes` parameter).

Federal rigor: deterministic rendering for the same input. Colour palette
is high-contrast and print-friendly so graph screenshots embed cleanly in
DOJ-style reports.
"""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction


def _unwrap(item: Any) -> dict:
    """Normalise a node/edge entry to a flat dict.

    Accepts:
      - Cytoscape format: {"data": {"id": ..., ...}}
      - Flat dict: {"id": ..., ...}
      - UINode / anything with to_dict (defensive)

    Returns a plain dict ready for wire transfer. Non-dict input becomes
    an empty dict so downstream renderer never crashes.
    """
    if isinstance(item, dict):
        if "data" in item and isinstance(item["data"], dict):
            return dict(item["data"])
        return dict(item)
    if hasattr(item, "to_dict") and callable(item.to_dict):
        d = item.to_dict()
        return d if isinstance(d, dict) else {}
    return {}


def Graph(
    nodes: list,
    edges: list,
    layout: str = "cose-bilkent",
    height: int = 600,
    min_node_size: float = 10.0,
    max_node_size: float = 50.0,
    edge_label_visible: bool = False,
    color_by: str = "type",
    on_node_click: UIAction | None = None,
) -> UINode:
    """Entity graph visualisation (Cytoscape-backed).

    Args:
        nodes: list of node dicts. Accepts Cases API format `{"data": {...}}`
            or flat `{"id": ..., "label": ..., "type": ..., "size": ...}`.
        edges: list of edge dicts. Same unwrap rules as nodes.
        layout: Cytoscape layout algorithm. One of:
            ``cose-bilkent`` | ``circle`` | ``grid`` | ``breadthfirst`` | ``concentric``.
        height: panel height in pixels.
        min_node_size / max_node_size: node diameter clamp (Cytoscape `mapData` range).
        edge_label_visible: render edge labels (off by default — cleaner for dense graphs).
        color_by: node field used for colour dispatch (default ``type``).
        on_node_click: optional UIAction fired when a node is selected.
            The node's ``id`` is injected into the action's params as ``node_id``.

    Returns:
        UINode with ``type="Graph"``. Panel unwraps and renders via cytoscape-js.
    """
    norm_nodes = [_unwrap(n) for n in (nodes or [])]
    norm_edges = [_unwrap(e) for e in (edges or [])]
    props: dict[str, Any] = {
        "nodes": norm_nodes,
        "edges": norm_edges,
        "layout": layout,
        "height": height,
        "min_node_size": min_node_size,
        "max_node_size": max_node_size,
        "edge_label_visible": edge_label_visible,
        "color_by": color_by,
    }
    if on_node_click is not None:
        props["on_node_click"] = on_node_click
    return UINode(type="Graph", props=props)
