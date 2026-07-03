"""sdl.field — declare a typed field carrying an explicit SDL semantic role.

The role is stamped into the Pydantic field's ``json_schema_extra`` under the
``x-sdl-role`` key, so the kernel and validators can read field→role mapping from
``model_json_schema()`` / ``model_fields``. Custom roles are validated eagerly
(at class definition time) and must use a non-reserved namespace.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from imperal_sdk.sdl.roles import (
    validate_custom_role,
    is_valid_role,
    namespace_of,
    RESERVED_NAMESPACES,
    RoleError,
)

ROLE_KEY = "x-sdl-role"


def field(*, role: str, default: Any = None, **kwargs: Any):
    """Pydantic field carrying an SDL semantic ``role``.

    The role is stamped into ``json_schema_extra['x-sdl-role']`` (readable via
    ``model_fields[name].json_schema_extra[ROLE_KEY]``). Use pydantic's native
    ``description=`` for a human description; it is forwarded to ``pydantic.Field``.

    Args:
        role: dotted custom role in a non-reserved namespace (validated eagerly).
        default: field default. Defaults to ``None`` (optional). Pass
            ``default=...`` (Ellipsis) to make the field required.
        **kwargs: forwarded to ``pydantic.Field`` (e.g. ``description=``).
    """
    validate_custom_role(role)
    json_schema_extra: dict[str, Any] = dict(kwargs.pop("json_schema_extra", None) or {})
    json_schema_extra[ROLE_KEY] = role
    return Field(default, json_schema_extra=json_schema_extra, **kwargs)


def _facet_field(*, role: str, default: Any = None, **kwargs: Any):
    """Internal: declare a STANDARD facet field. Unlike the public ``field``,
    a facet role MUST use a reserved namespace (facets own the standard role
    namespaces). Validates grammar + reserved-namespace membership.
    """
    if not is_valid_role(role):
        raise RoleError(f"Malformed facet role {role!r}: expected dotted lowercase.")
    if namespace_of(role) not in RESERVED_NAMESPACES:
        raise RoleError(
            f"Facet role {role!r} must use a reserved namespace "
            f"(one of {sorted(RESERVED_NAMESPACES)})."
        )
    json_schema_extra: dict[str, Any] = dict(kwargs.pop("json_schema_extra", None) or {})
    json_schema_extra[ROLE_KEY] = role
    return Field(default, json_schema_extra=json_schema_extra, **kwargs)
