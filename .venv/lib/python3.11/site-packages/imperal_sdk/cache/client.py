# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Concrete HTTP cache client backing ``ctx.cache``.

Talks to the Auth Gateway ``/v1/internal/extcache/{app_id}/{user_id}/{model}/{key_hash}``
router (shipped in Phase 3). HMAC call-token authentication; TTL-bounded,
Pydantic-only, per-user, per-extension.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


# ---- constraints ----------------------------------------------------------

_KEY_MAX_LEN = 128
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:]+$")
_TTL_MIN = 5
_TTL_MAX = 300
_VALUE_MAX_BYTES = 64 * 1024
_ENVELOPE_VERSION = 1
_HTTP_TIMEOUT = 5.0


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not key:
        raise ValueError("cache key must be a non-empty string")
    if len(key) > _KEY_MAX_LEN:
        raise ValueError(
            f"cache key too long: {len(key)} > {_KEY_MAX_LEN} (I-CACHE-KEY-SAFETY)"
        )
    if not _KEY_RE.match(key):
        raise ValueError(
            f"cache key {key!r} has forbidden characters; allowed: "
            "alphanumerics, '_', '-', ':' (I-CACHE-KEY-SAFETY)"
        )


def _validate_ttl(ttl: int) -> None:
    if not isinstance(ttl, int) or isinstance(ttl, bool):
        raise ValueError("ttl_seconds must be int")
    if ttl < _TTL_MIN or ttl > _TTL_MAX:
        raise ValueError(
            f"ttl_seconds must be in [{_TTL_MIN}, {_TTL_MAX}] (got {ttl}); "
            "I-CACHE-TTL-CAP-300S"
        )


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class CacheClient:
    """Pydantic-typed short-lived per-user cache.

    Values flow through a stable JSON envelope::

        {"model": <name>, "version": 1, "data": <value>, "cached_at": <ISO-UTC>}

    The envelope is capped at 64 KB and tied to a specific ``@ext.cache_model``
    registration — attempts to read a key with a different model, or write a
    class not registered via the extension, are rejected at the SDK boundary
    before any network call.

    """

    def __init__(
        self,
        app_id: str,
        user_id: str,
        gw_url: str,
        service_token: str = "",
        call_token: str = "",
        extension: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        if not app_id:
            raise ValueError("CacheClient requires app_id")
        if not user_id:
            raise ValueError("CacheClient requires user_id")
        self._app_id = app_id
        self._user_id = user_id
        self._gw_url = gw_url.rstrip("/")
        self._service_token = service_token
        self._call_token = call_token
        self._extension = extension
        self._http = http_client  # optional injection for testing

    # ---- helpers ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {"X-Service-Token": self._service_token}
        if self._call_token:
            h["Authorization"] = f"ImperalCallToken {self._call_token}"
        return h

    def _url(self, model_name: str, key: str) -> str:
        return (
            f"{self._gw_url}/v1/internal/extcache/"
            f"{self._app_id}/{self._user_id}/{model_name}/{_hash_key(key)}"
        )

    def _resolve_model_name(self, cls: type) -> str:
        if self._extension is None:
            raise RuntimeError(
                "CacheClient has no Extension reference; cannot resolve "
                "@ext.cache_model registration. This is a construction bug "
                "in the kernel Context wiring."
            )
        resolver = getattr(self._extension, "_resolve_cache_model_name", None)
        if resolver is None:
            raise RuntimeError(
                "Extension instance missing _resolve_cache_model_name — "
                "SDK version mismatch?"
            )
        name = resolver(cls)
        if name is None:
            raise ValueError(
                f"cache model {cls.__name__!r} is not registered with "
                f"@{self._app_id}.cache_model(...); register it before "
                "calling ctx.cache.set/get (I-CACHE-MODEL-REGISTRATION-REQUIRED)"
            )
        return name

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        if self._http is not None:
            return await self._http.request(method, url, **kw)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            return await client.request(method, url, **kw)

    # ---- public API ------------------------------------------------------

    async def get(self, key: str, model: type[T]) -> T | None:
        _validate_key(key)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(
                "cache.get: model must be a Pydantic BaseModel subclass "
                "(I-CACHE-PYDANTIC-ONLY)"
            )
        model_name = self._resolve_model_name(model)
        resp = await self._request(
            "GET",
            self._url(model_name, key),
            headers=self._headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        env = resp.json()
        if env.get("model") != model_name or env.get("version") != _ENVELOPE_VERSION:
            return None
        data = env.get("data")
        if data is None:
            return None
        return model.model_validate(data)

    async def set(
        self,
        key: str,
        value: BaseModel,
        ttl_seconds: int = 60,
    ) -> None:
        _validate_key(key)
        _validate_ttl(ttl_seconds)
        if not isinstance(value, BaseModel):
            raise TypeError(
                "cache.set: value must be a Pydantic BaseModel instance "
                "(I-CACHE-PYDANTIC-ONLY); dicts / primitives not accepted"
            )
        model_name = self._resolve_model_name(type(value))
        envelope = {
            "model": model_name,
            "version": _ENVELOPE_VERSION,
            "data": value.model_dump(mode="json"),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        payload_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > _VALUE_MAX_BYTES:
            raise ValueError(
                f"cache value envelope too large: {len(payload_bytes)} > "
                f"{_VALUE_MAX_BYTES} bytes (I-CACHE-VALUE-SIZE-CAP-64KB)"
            )
        # Enforce envelope-size cap regardless of transport shape — the
        # serialised body we compute above is the same bytes that end up in
        # the platform state store, so the cap applies whether we send ``content=`` or ``json=``.
        _ = payload_bytes  # kept for size validation side-effect; not sent
        resp = await self._request(
            "PUT",
            self._url(model_name, key),
            headers=self._headers(),
            json={"envelope": envelope, "ttl_seconds": ttl_seconds},
        )
        resp.raise_for_status()

    async def delete(self, key: str) -> None:
        """Delete cache entry under all registered model namespaces.

        The platform state store does NOT support a wildcard model segment —
        a wildcard would silently match no real entry. Since a key can exist
        under any registered model, we iterate all models and issue one DELETE
        per namespace. Idempotent; 404 is not an error.
        """
        _validate_key(key)
        key_hash = _hash_key(key)
        ext = self._extension
        models: list[str]
        if ext is not None and hasattr(ext, "_cache_models"):
            models = list(ext._cache_models.keys())
        else:
            models = []
        for model_name in models:
            url = (
                f"{self._gw_url}/v1/internal/extcache/"
                f"{self._app_id}/{self._user_id}/{model_name}/{key_hash}"
            )
            resp = await self._request(
                "DELETE", url, headers=self._headers()
            )
            if resp.status_code in (200, 204, 404):
                continue
            resp.raise_for_status()

    async def get_or_fetch(
        self,
        key: str,
        model: type[T],
        fetcher: Callable[[], Awaitable[T]],
        ttl_seconds: int = 60,
    ) -> T:
        cached = await self.get(key, model)
        if cached is not None:
            return cached
        fresh = await fetcher()
        if not isinstance(fresh, model):
            raise TypeError(
                f"cache.get_or_fetch: fetcher returned {type(fresh).__name__}, "
                f"expected {model.__name__} (I-CACHE-PYDANTIC-ONLY)"
            )
        await self.set(key, fresh, ttl_seconds=ttl_seconds)
        return fresh
