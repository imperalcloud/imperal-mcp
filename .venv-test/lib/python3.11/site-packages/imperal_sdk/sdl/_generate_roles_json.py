"""Generate sdl_roles.json — the machine-readable SDL role catalog.

Phase 1 emits the Entity core roles. Phase 2 (facet library) extends
``build_catalog`` with facet field roles. Run: ``python -m imperal_sdk.sdl._generate_roles_json``.
"""
from __future__ import annotations

import json
import pathlib

from imperal_sdk.sdl.roles import CORE_ROLES

_SCHEMA_VERSION = 1


def build_catalog() -> dict:
    """Role catalog: Entity core roles + every standard facet's roles (sorted, stable)."""
    import imperal_sdk.sdl.facets as _facets
    from imperal_sdk.sdl.entity import roles_of as _roles_of

    roles = [
        {"role": role, "field": field_name, "tier": "core", "facet": "Entity"}
        for field_name, role in CORE_ROLES.items()
    ]
    seen = {r["role"] for r in roles}
    for facet_name in _facets.__all__:
        model = getattr(_facets, facet_name)
        for field_name, role in _roles_of(model).items():
            if role in seen:
                continue
            seen.add(role)
            roles.append({"role": role, "field": field_name, "tier": "facet", "facet": facet_name})
    roles.sort(key=lambda r: r["role"])
    return {"schema_version": _SCHEMA_VERSION, "sdl_vocab_version": str(_SCHEMA_VERSION), "roles": roles}


def _target_path() -> pathlib.Path:
    # repo root = three parents up from this file (src/imperal_sdk/sdl/_gen.py)
    return pathlib.Path(__file__).resolve().parents[3] / "sdl_roles.json"


def main() -> None:
    path = _target_path()
    path.write_text(json.dumps(build_catalog(), indent=2) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
