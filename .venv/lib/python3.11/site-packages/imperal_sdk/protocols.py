# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""ExtensionProtocol — what every extension must satisfy for kernel loading."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExtensionProtocol(Protocol):
    """Kernel validates at load time. Fail = CRITICAL log, extension NOT loaded."""
    app_id: str
    version: str
    tools: dict
