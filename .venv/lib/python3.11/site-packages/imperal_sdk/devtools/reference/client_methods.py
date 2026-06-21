# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""``client_method`` kind — ``ctx.<ns>.<method>`` across all client namespaces.

REUSES ``generate_api_surface._load_namespaces`` (federal: no parallel
enumerator) so this view can never drift from the api-surface view.
"""
from __future__ import annotations

import inspect
from typing import Any

from imperal_sdk.devtools.generate_api_surface import _load_namespaces
from imperal_sdk.devtools.reference._introspect import callable_symbol


def collect() -> dict[str, dict[str, Any]]:
    symbols: dict[str, dict[str, Any]] = {}
    for ns, cls in _load_namespaces().items():
        for name, member in inspect.getmembers(cls, predicate=callable):
            if name.startswith("_"):
                continue
            qual = f"ctx.{ns}.{name}"
            symbols[qual] = callable_symbol(
                member, name=qual, kind="client_method", skip_self=True)
    return symbols
