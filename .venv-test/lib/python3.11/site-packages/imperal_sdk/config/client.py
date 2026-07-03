# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Read-only config client. All merge layers already resolved by kernel."""
from __future__ import annotations
import copy
from typing import Any


class ConfigClient:
    """Resolved config for current user+app+tenant. Read-only.

    The kernel resolves the full scope hierarchy before creating Context:
    Platform → Tenant → Tenant role_defaults[role] → App → User → Tenant enforced.
    Extension receives the final merged result.
    """

    def __init__(self, resolved: dict):
        self._resolved = resolved

    def get(self, key: str, default: Any = None) -> Any:
        """Get resolved config value using dot notation.

        Examples:
            ctx.config.get("models.primary_model")  # "claude-opus"
            ctx.config.get("persona.language")        # "ru"
            ctx.config.get("custom.missing", "fallback")  # "fallback"
        """
        parts = key.split(".")
        current = self._resolved
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def get_section(self, section: str) -> dict:
        """Get a full config section as dict.

        Example:
            ctx.config.get_section("models")
            # {"primary_model": "claude-opus", "temperature": 0.7, ...}
        """
        val = self._resolved.get(section, {})
        if isinstance(val, dict):
            return copy.deepcopy(val)
        return {}

    def all(self) -> dict:
        """Return full resolved config (deep copy)."""
        return copy.deepcopy(self._resolved)
