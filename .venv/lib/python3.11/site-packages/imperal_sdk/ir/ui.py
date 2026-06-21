"""IR panel model — Tier-1 static-tree render (Task E1).

Defines ``IRPanel`` and the discriminated ``Render`` union used in the IR
envelope's ``ui`` slot.  Slot names are validated against the canonical
``ALLOWED_PANEL_SLOTS`` frozenset so bad slot strings are caught at
IR-construction time, not at deploy time.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..types.contributions import ALLOWED_PANEL_SLOTS


class RenderStatic(BaseModel):
    """Tier-1 render: a plain serialisable UI-node tree (no runtime needed)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["static"]
    tree: dict[str, Any] = Field(default_factory=dict)


class RenderTemplate(BaseModel):
    """Tier-2 render: a declarative template tree evaluated at render time."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["template"]
    tree: dict[str, Any] = Field(default_factory=dict)


class RenderCode(BaseModel):
    """Tier-3 render: a Python module + callable entry point (code panel)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["code"]
    module: str
    entry: str


Render = Annotated[
    Union[RenderStatic, RenderTemplate, RenderCode],
    Field(discriminator="kind"),
]


class IRPanel(BaseModel):
    """A single panel declared by an extension in the IR envelope."""
    model_config = ConfigDict(extra="forbid")

    panel_id: str
    slot: str
    title: str = ""
    icon: str = ""
    render: Render

    @field_validator("slot")
    @classmethod
    def _check_slot(cls, v: str) -> str:
        if v not in ALLOWED_PANEL_SLOTS:
            raise ValueError(
                f"slot {v!r} is not allowed; valid slots: {sorted(ALLOWED_PANEL_SLOTS)}"
            )
        return v
