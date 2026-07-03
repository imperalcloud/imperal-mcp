# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Shared chat-loop exceptions.

Lives in a leaf module so both `imperal_sdk.chat.handler` and
`imperal_sdk.chat.execution` can import without creating an import
cycle. handler.py re-exports `TaskCancelled` for back-compat with any
caller doing `from imperal_sdk.chat.handler import TaskCancelled`.
"""
from __future__ import annotations


class TaskCancelled(Exception):
    """Raised by ctx.progress() when the user cancels a task."""
