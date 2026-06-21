"""Re-exports `_check_target_scope` for chat/guards.py backward compat.

Delegates to the substrate-neutral platform shim (`runtime/_platform`); when the
platform runtime is unavailable the shim returns a permissive-shape, deny-outcome
fallback. This module names no engine implementation.
"""
from __future__ import annotations

from ._platform import check_target_scope as _check_target_scope  # noqa: F401
