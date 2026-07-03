# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""``ui_component`` kind — every public component factory in ``imperal_sdk.ui``.

Component factories are functions returning a ``UINode``; the two data objects
in ``ui.__all__`` (``AgencyTheme``, ``ColorPair``) are not factories and are
skipped. Enums: ``ui.Input.type`` is sourced from ``INPUT_TYPES`` (the single
source), plus any live ``Literal[...]`` param is captured automatically.
"""
from __future__ import annotations

import inspect
from typing import Any

from imperal_sdk.devtools.reference._introspect import (
    callable_symbol,
    enums_from_literals,
)


def collect() -> dict[str, dict[str, Any]]:
    import imperal_sdk.ui as ui
    from imperal_sdk.ui.input_components import INPUT_TYPES

    # Declared per-param enums whose single source is a code constant rather
    # than a Literal annotation. Merged on top of any auto-detected Literals.
    enum_overrides: dict[str, dict[str, list[str]]] = {
        "ui.Input": {"type": list(INPUT_TYPES)},
    }

    symbols: dict[str, dict[str, Any]] = {}
    for name in ui.__all__:
        obj = getattr(ui, name)
        if not inspect.isfunction(obj):
            continue
        qual = f"ui.{name}"
        enums = enums_from_literals(obj)
        enums.update(enum_overrides.get(qual, {}))
        sym = callable_symbol(obj, name=qual, kind="ui_component", skip_self=False,
                              enums=enums)
        # All factories return a UINode regardless of the source annotation.
        sym["returns"] = "UINode"
        symbols[qual] = sym
    return symbols
