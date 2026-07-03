"""Imperal SDK · UI base node."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _serialize(v: Any) -> Any:
    """Recursively serialize UINode/UIAction/list/dict to JSON-safe types."""
    if v is None:
        return None
    if isinstance(v, UINode):
        return v.to_dict()
    if isinstance(v, UIAction):
        return v.to_dict()
    if isinstance(v, list):
        return [_serialize(item) for item in v]
    if isinstance(v, dict):
        return {k: _serialize(dv) for k, dv in v.items()}
    return v


@dataclass(slots=True)
class UINode:
    """Base class for all declarative UI components. Serializes to JSON."""
    type: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for wire transfer."""
        return {
            "type": self.type,
            "props": {k: _serialize(v) for k, v in self.props.items() if v is not None},
        }


@dataclass(slots=True)
class UIAction:
    """Base class for UI actions (Call, Navigate, Send)."""
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {"action": self.action}
        result.update(self.params)
        return result
