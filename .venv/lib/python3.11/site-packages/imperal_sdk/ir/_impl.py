# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Impl discriminated union — shared by schema.py and skeleton.py."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ImplCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["code"]
    module: str
    entry: str


class ImplDeclarative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["declarative"]
    steps: list[dict[str, Any]] = Field(default_factory=list)


Impl = Annotated[Union[ImplCode, ImplDeclarative], Field(discriminator="kind")]
