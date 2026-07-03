# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""``sdl_func`` kind — the ``imperal_sdk.sdl`` helper functions.

The canonical helper set (scope expansion 2026-06-19): entity, field, roles,
roles_of, namespace_of, is_valid_role, validate_custom_role, facets. Some
names (``entity``, ``roles``, ``facets``) are submodules rather than functions
in the live SDK; those degrade to a noted placeholder so the completeness gate
records them with a reason instead of the generator crashing.
"""
from __future__ import annotations

import inspect
from typing import Any

from imperal_sdk.devtools.reference._introspect import (
    callable_symbol,
    degraded_symbol,
)

_SDL_FUNCS = (
    "entity", "field", "roles", "roles_of", "namespace_of",
    "is_valid_role", "validate_custom_role", "facets", "resolve_facets",
    "facet_resolve",
)


def collect() -> dict[str, dict[str, Any]]:
    import imperal_sdk.sdl as sdl

    symbols: dict[str, dict[str, Any]] = {}
    for name in _SDL_FUNCS:
        qual = f"sdl.{name}"
        obj = getattr(sdl, name, None)
        if obj is None:
            symbols[qual] = degraded_symbol(qual, "sdl_func", "not exported by sdl")
        elif inspect.isfunction(obj) or inspect.isbuiltin(obj):
            symbols[qual] = callable_symbol(
                obj, name=qual, kind="sdl_func", skip_self=False)
        else:
            symbols[qual] = degraded_symbol(
                qual, "sdl_func", f"{type(obj).__name__}, not a function")
    return symbols
