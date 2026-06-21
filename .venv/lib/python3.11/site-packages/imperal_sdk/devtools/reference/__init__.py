# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Per-kind enumerators for the SDK reference generator.

Each module exposes one ``collect() -> dict[str, dict]`` function returning a
slice of the ``symbols`` map keyed by qualified name. ``generate_reference``
(the thin orchestrator) merges them. Split out to honour the no-god-file rule
(the full surface is six distinct kinds with bespoke introspection).
"""
from __future__ import annotations

from imperal_sdk.devtools.reference import (
    client_methods,
    dataclasses_kind,
    decorators,
    sdl_funcs,
    sdl_roles,
    ui_components,
)

__all__ = [
    "client_methods",
    "dataclasses_kind",
    "decorators",
    "sdl_funcs",
    "sdl_roles",
    "ui_components",
]
