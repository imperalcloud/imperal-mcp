"""SDL semantic role grammar, reserved-namespace registry, and core role catalog.

A role is a dotted lowercase string (e.g. ``core.title``, ``audio.bpm``) declaring
the SEMANTIC meaning of a field. Standard facet roles live under reserved namespaces;
extension-declared custom roles (via ``sdl.field``) must use a non-reserved namespace.
Pure module — no internal SDK dependencies.
"""
from __future__ import annotations

import re

# Namespaces owned by the standard facet library. Custom roles MUST NOT use these.
RESERVED_NAMESPACES: frozenset[str] = frozenset({
    "core", "time", "people", "content", "comm", "media", "quantity",
    "money", "catalog", "task", "geo", "net", "metric", "event",
    "rating", "sec", "device",
})

# Dotted role grammar: >=2 lowercase segments, first char alpha.
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")

# Canonical roles of the Entity core fields (Phase 1). Facet roles append in Phase 2.
CORE_ROLES: dict[str, str] = {
    "id": "core.id",
    "title": "core.title",
    "kind": "core.kind",
    "subtitle": "core.subtitle",
    "description": "core.description",
    "status": "core.status",
    "url": "core.url",
}


class RoleError(ValueError):
    """Raised when a semantic role is malformed or illegally uses a reserved namespace."""


def is_valid_role(role: str) -> bool:
    """True if ``role`` matches the dotted-lowercase grammar."""
    return bool(_ROLE_RE.match(role))


def namespace_of(role: str) -> str:
    """Return the first dotted segment (the namespace).

    The caller is responsible for passing a syntactically valid role; this function
    does not validate.
    """
    return role.split(".", 1)[0]


def validate_custom_role(role: str) -> None:
    """Validate an extension-declared custom role. Raises RoleError on bad grammar
    or use of a reserved namespace."""
    if not is_valid_role(role):
        raise RoleError(
            f"Malformed role {role!r}: expected dotted lowercase, e.g. 'audio.bpm'."
        )
    ns = namespace_of(role)
    if ns in RESERVED_NAMESPACES:
        raise RoleError(
            f"Role {role!r} uses reserved namespace {ns!r}; "
            "custom roles must use a non-reserved namespace."
        )
