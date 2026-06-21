# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""IRSkeleton — first-class skeleton slot for the IR envelope."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ._impl import Impl


class IRSkeleton(BaseModel):
    """One skeleton section declared by an extension.

    ``producer`` follows the same :class:`~imperal_sdk.ir.schema.Impl`
    discriminated union used by :class:`~imperal_sdk.ir.schema.IRFunction`.
    For skeleton refresh tools the kind is always ``"code"``.
    """

    model_config = ConfigDict(extra="forbid")

    section: str
    shape: dict[str, Any] = Field(default_factory=dict)
    producer: Impl
    alert: bool = False
    ttl: int = 300
