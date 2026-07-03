"""SDL facet resolution — by-name lookup returning merged {field: role} maps.

Public API
----------
resolve_facets(names) -> dict[str, str]
    Merge the field/role maps for the named standard facets.
    Raises KeyError for any unknown facet name.
"""
from __future__ import annotations

from . import facets as _facets
from .entity import roles_of


def resolve_facets(names: list[str]) -> dict[str, str]:
    """Resolve standard facet names to their merged ``{field: role}`` map.

    Parameters
    ----------
    names:
        Facet class names as exported from ``imperal_sdk.sdl.facets``
        (e.g. ``["Invoiced", "Timestamped"]``).

    Returns
    -------
    dict[str, str]
        Merged ``{field_name: dotted_role}`` for all requested facets.
        An empty list returns an empty dict.

    Raises
    ------
    KeyError
        If any name in *names* is not a known facet class.
    """
    out: dict[str, str] = {}
    for name in names:
        cls = getattr(_facets, name, None)
        if cls is None or not isinstance(cls, type):
            raise KeyError(f"Unknown facet {name!r}")
        out.update(roles_of(cls))
    return out
