"""Bounded, non-Turing canon projection for IR entity descriptors."""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Template engine — CLOSED filter whitelist (non-Turing: no expressions/loops)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\{\{\s*(.*?)\s*\}\}")
_ALLOWED_FILTERS = {"count", "default", "format"}


class CanonError(ValueError):
    """Raised when a canon template uses a filter outside the closed whitelist."""


def _apply_filter(name: str, arg: str, value: Any) -> Any:
    if name == "count":
        return len(value) if value is not None else 0
    if name == "default":
        return value if (value not in (None, "")) else arg.strip("'\"")
    if name == "format":
        return format(value, arg.strip("'\"")) if value is not None else ""
    raise CanonError(
        f"Canon filter {name!r} is not in the closed whitelist {_ALLOWED_FILTERS}"
    )


def _render_token(expr: str, data: dict) -> str:
    # forms: "field" | "count(field)" | "field | filter:'arg'"
    m = re.fullmatch(r"(\w+)\((\w+)\)", expr)
    if m:
        return str(_apply_filter(m.group(1), "", data.get(m.group(2))))
    if "|" in expr:
        field, rest = (p.strip() for p in expr.split("|", 1))
        fname, _, farg = (p.strip() for p in rest.partition(":"))
        if fname not in _ALLOWED_FILTERS:
            raise CanonError(
                f"Canon filter {fname!r} is not in the closed whitelist {_ALLOWED_FILTERS}"
            )
        return str(_apply_filter(fname, farg, data.get(field)))
    return str(data.get(expr.strip(), ""))


def _render_template(template: str, data: dict) -> str:
    return _TOKEN.sub(lambda mo: _render_token(mo.group(1), data), template)


# ---------------------------------------------------------------------------
# id_from helper
# ---------------------------------------------------------------------------


def _first_present(fields: list[str], data: dict) -> Any:
    for f in fields:
        v = data.get(f)
        if v is not None:
            return v
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def project_canon(spec: dict, data: dict) -> dict:
    """Return canonical ``{id?, title?, kind?}`` fields from *data* using *spec*.

    Supported spec keys:

    ``id_from``
        List of field names tried in order; first non-None value wins;
        empty string ``""`` if none match.

    ``kind_const``
        Literal string written to ``out["kind"]`` unchanged.

    ``title_template``
        A ``{{field}}`` template rendered against *data* using a **closed**
        filter whitelist: ``count`` / ``default`` / ``format``.
        An unlisted filter raises :exc:`CanonError` (non-Turing boundary).
    """
    out: dict[str, Any] = {}
    if "id_from" in spec:
        out["id"] = _first_present(list(spec["id_from"]), data)
    if "kind_const" in spec:
        out["kind"] = spec["kind_const"]
    if "title_template" in spec:
        out["title"] = _render_template(spec["title_template"], data)
    return out
