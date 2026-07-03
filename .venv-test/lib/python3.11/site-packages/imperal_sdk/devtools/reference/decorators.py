# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""``decorator`` kind — ``chat.function`` + the ``ext.*`` decorator methods.

Qualified ``chat.function`` (on ChatExtension) and ``ext.<name>`` (on
Extension). ``self`` is dropped. Any listed name that is absent or not a plain
decorator method (e.g. a property) degrades to a noted placeholder rather than
crashing — the completeness gate (T6) then records it with a reason.
"""
from __future__ import annotations

import inspect
from typing import Any

from imperal_sdk.devtools.reference._introspect import (
    callable_symbol,
    degraded_symbol,
)

# The canonical ext decorator set (scope expansion 2026-06-19, Valentin).
# ``on_refresh`` was removed: it does not exist on Extension in SDK 5.4.x+.
# ``lifecycle`` is a property (not a function) — kept so the completeness
# gate can record it as a degraded placeholder with an explanatory note.
_EXT_DECORATORS = (
    "secret", "tool", "skeleton", "cache_model", "on_upgrade",
    "webhook", "emits", "tray", "panel", "widget", "lifecycle",
)


def collect() -> dict[str, dict[str, Any]]:
    from imperal_sdk.chat.extension import ChatExtension
    from imperal_sdk.extension import Extension

    symbols: dict[str, dict[str, Any]] = {
        "chat.function": callable_symbol(
            ChatExtension.function, name="chat.function", kind="decorator", skip_self=True),
    }
    for name in _EXT_DECORATORS:
        qual = f"ext.{name}"
        member = inspect.getattr_static(Extension, name, None)
        if member is None:
            symbols[qual] = degraded_symbol(
                qual, "decorator", f"not present on Extension in SDK {_version()}")
            continue
        if not (inspect.isfunction(member) or inspect.ismethod(member)):
            # e.g. ``lifecycle`` is a read-only property, not a decorator.
            symbols[qual] = degraded_symbol(
                qual, "decorator", f"{type(member).__name__}, not a decorator method")
            continue
        symbols[qual] = callable_symbol(
            member, name=qual, kind="decorator", skip_self=True)
    return symbols


def _version() -> str:
    import imperal_sdk
    return imperal_sdk.__version__
