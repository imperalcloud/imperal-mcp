"""Canonical SDL entity types: Entity (core), Ref (lightweight reference),
EntityList[T] (typed list), plus roles_of() introspection.

The Entity core fields carry FIXED semantic roles (core.*) by their very names —
the kernel reads entity.id / entity.title / entity.kind directly, no guessing.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

from imperal_sdk.sdl.field import ROLE_KEY
from imperal_sdk.sdl.roles import CORE_ROLES

T = TypeVar("T")


class Ref(BaseModel):
    """Lightweight reference to another entity (parent/related/list-item/cross-app).

    Carries ``title`` so the kernel can render/resolve without a second lookup.
    """
    id: str | int
    kind: str
    title: str
    app_id: str | None = None


class Entity(BaseModel):
    """Canonical base for any SDL entity. Subclasses add domain fields + facets.

    Required: id, title, kind. ``kind`` defaults to the subclass name lowercased.
    An empty-string ``kind`` is treated as absent and is replaced by the subclass
    name lowercased (e.g. ``Entity(id=1, title="X", kind="").kind == "entity"``).

    Carries the schema marker ``x-sdl: "entity"`` so the platform can detect an
    SDL-typed result from its ``return_schema`` alone. Inherited by subclasses.
    """
    model_config = ConfigDict(json_schema_extra={"x-sdl": "entity"})
    id: str | int
    title: str
    kind: str = ""
    subtitle: str | None = None
    description: str | None = None
    status: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _default_kind(self) -> "Entity":
        if not self.kind:
            self.kind = type(self).__name__.lower()
        return self


class EntityList(BaseModel, Generic[T]):
    """Typed list result with list/pagination semantics. Mirrors Page[T].

    Carries the schema marker ``x-sdl: "entity-list"`` for platform detection.
    """
    model_config = ConfigDict(json_schema_extra={"x-sdl": "entity-list"})
    items: list[T]
    total: int | None = None
    page: int | None = None
    has_more: bool = False

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


def roles_of(model: type[BaseModel]) -> dict[str, str]:
    """Map field-name → semantic role for an Entity subclass (or any model).

    Core Entity fields resolve to their fixed ``core.*`` roles; other fields
    resolve to a custom role iff declared via ``sdl.field`` (``x-sdl-role`` in
    ``json_schema_extra``). Plain untagged fields are omitted.

    Accepts either an Entity subclass OR an instance (an instance is coerced to its
    type) so callers (e.g. the kernel) can pass whichever they have.
    """
    if not isinstance(model, type):
        model = type(model)
    out: dict[str, str] = {}
    for fname, finfo in model.model_fields.items():
        if fname in CORE_ROLES:
            out[fname] = CORE_ROLES[fname]
            continue
        extra = finfo.json_schema_extra
        if isinstance(extra, dict):
            role = extra.get(ROLE_KEY)
            if isinstance(role, str):
                out[fname] = role
    return out
