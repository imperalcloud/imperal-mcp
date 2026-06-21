# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""v1.6.0 ctx.cache — short-lived Pydantic-typed per-user cache.

Surfaced on the context object as ``ctx.cache``. See :mod:`CacheProtocol`
for the async surface and :mod:`CacheClient` for the concrete HTTP
implementation backed by the Auth Gateway extcache router.

Invariants:
- I-CACHE-TTL-CAP-300S
- I-CACHE-PYDANTIC-ONLY
- I-CACHE-MODEL-REGISTRATION-REQUIRED
- I-CACHE-VALUE-SIZE-CAP-64KB
- I-CACHE-KEY-SAFETY
"""
from imperal_sdk.cache.protocol import CacheProtocol
from imperal_sdk.cache.client import CacheClient

__all__ = ["CacheProtocol", "CacheClient"]
