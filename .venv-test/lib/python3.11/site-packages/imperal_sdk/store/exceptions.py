# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Exceptions raised by imperal_sdk.store."""
from __future__ import annotations


class StoreError(Exception):
    """Base for all store exceptions."""


class StoreUnavailable(StoreError):
    """Auth Gateway unreachable or overloaded.

    SDK-side callers should catch this and skip the tick (for scheduler
    fan-out) or back-off (for user-facing handlers).
    """
    def __init__(self, retry_after: int = 30):
        super().__init__(f"store unavailable (retry in {retry_after}s)")
        self.retry_after = retry_after


class StoreContractError(StoreError):
    """Auth Gateway returned response violating shared Pydantic contract.

    Indicates SDK/Auth-GW schema drift — should be caught by I-SDK-GW-CONTRACT-1
    CI snapshot test before reaching production.
    """
