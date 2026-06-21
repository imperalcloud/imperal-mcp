# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Protocol for ``ctx.cache`` — short-lived, Pydantic-typed per-user cache.

Extensions interact with a concrete :class:`imperal_sdk.cache.CacheClient`
via this surface. Values must be instances of Pydantic models registered
with :meth:`imperal_sdk.extension.Extension.cache_model`; TTL is bounded in
[5, 300] seconds; keys are alphanumeric + ``_-:`` up to 128 characters.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class CacheProtocol(Protocol):
    """Read/write interface for ctx.cache.

    Implementations MUST enforce:

    - ``ttl_seconds`` in [5, 300] (I-CACHE-TTL-CAP-300S)
    - values are Pydantic ``BaseModel`` instances registered via
      ``@ext.cache_model`` (I-CACHE-PYDANTIC-ONLY,
      I-CACHE-MODEL-REGISTRATION-REQUIRED)
    - serialized envelope <= 64 KB (I-CACHE-VALUE-SIZE-CAP-64KB)
    - key syntax: ``[A-Za-z0-9_\\-:]+``, length <= 128 (I-CACHE-KEY-SAFETY)
    """

    async def get(self, key: str, model: type[T]) -> T | None: ...

    async def set(
        self,
        key: str,
        value: BaseModel,
        ttl_seconds: int = 60,
    ) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def get_or_fetch(
        self,
        key: str,
        model: type[T],
        fetcher: Callable[[], Awaitable[T]],
        ttl_seconds: int = 60,
    ) -> T: ...
