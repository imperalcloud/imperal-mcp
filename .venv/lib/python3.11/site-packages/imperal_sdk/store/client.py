# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
from typing import Any, AsyncIterator
import logging
import re
import httpx

from imperal_sdk.types.pagination import Page
from imperal_sdk.types.models import Document  # canonical Document dataclass (1.5.25+)
from imperal_sdk.types.store_contracts import ListUsersRequest, ListUsersResponse  # noqa: F401  # ListUsersRequest imported as drift-sentinel per I-SDK-GW-CONTRACT-1
from imperal_sdk.store.exceptions import StoreUnavailable, StoreContractError

__all__ = ["StoreClient", "Document"]  # re-export Document for legacy imports

_log = logging.getLogger(__name__)
_FORBIDDEN_COLLECTION = re.compile(r"[:\*\?\[\]\s/]")


def _emit_threat_counter(app: str, tenant: str) -> None:
    """Emit SigNoz counter for cross-context bypass attempts.

    I-STORE-THREAT-COUNTER-1 — always 0. Any non-zero firing = real incident.
    Phase 1 stub: structured warning log. Real OTEL counter lands in
    observability activate-phase (see spec §7).
    """
    _log.warning(
        "store.cross_context_bypass_attempt",
        extra={"app_id": app, "tenant_id": tenant},
    )


class StoreClient:
    """Tier 1: Managed document storage via Auth Gateway internal API."""

    def __init__(self, gateway_url: str, auth_token: str = "", extension_id: str = "", user_id: str = "", tenant_id: str = "default", service_token: str = ""):
        self._gateway_url = gateway_url.rstrip("/")
        self._auth_token = auth_token or service_token
        self._extension_id = extension_id
        self._user_id = user_id
        self._tenant_id = tenant_id

    def _headers(self) -> dict:
        return {"X-Service-Token": self._auth_token, "X-Extension-ID": self._extension_id, "X-Tenant-ID": self._tenant_id}

    def _split_path(self, path: str) -> tuple[str, str]:
        """Split 'collection/doc_id' into (collection, doc_id)."""
        if "/" in path:
            parts = path.split("/", 1)
            return parts[0], parts[1]
        return path, path

    async def create(self, collection: str, data: dict) -> Document:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/internal/store", json={"collection": collection, "data": data, "user_id": self._user_id, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            r = resp.json()
            return Document(id=r["id"], collection=collection, data=r.get("data", data), created_at=r.get("created_at") or "", updated_at=r.get("updated_at") or "")

    async def get(self, collection: str, doc_id: str | None = None) -> Document | None:
        """Get a document. Supports both get(collection, doc_id) and get('collection/doc_id')."""
        if doc_id is None:
            collection, doc_id = self._split_path(collection)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._gateway_url}/v1/internal/store/{collection}/{doc_id}", params={"extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            if resp.status_code == 404: return None
            resp.raise_for_status()
            r = resp.json()
            return Document(id=r["id"], collection=collection, data=r.get("data", {}), created_at=r.get("created_at") or "", updated_at=r.get("updated_at") or "")

    async def set(self, key: str, data: Any) -> Document:
        """Upsert shortcut: set('collection/doc_id', data). Creates or updates."""
        collection, doc_id = self._split_path(key)
        existing = await self.get(collection, doc_id)
        if existing:
            return await self.update(collection, doc_id, data if isinstance(data, dict) else {"value": data})
        return await self.create(collection, data if isinstance(data, dict) else {"value": data})

    async def list(self, prefix: str = "") -> list[Document]:
        """List documents in a collection. Supports list('collection/prefix')."""
        collection, _ = self._split_path(prefix) if "/" in prefix else (prefix, "")
        result = await self.query(collection)
        return result.data

    async def query(self, collection: str, where: dict | None = None, order_by: str | None = None, limit: int = 100) -> Page[Document]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/internal/store/{collection}/query", json={"where": where or {}, "order_by": order_by, "limit": limit, "extension_id": self._extension_id, "user_id": self._user_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            if resp.status_code == 404:
                return Page(data=[], has_more=False)
            resp.raise_for_status()
            raw = resp.json()
            if isinstance(raw, list):
                items = [Document(id=r["id"], collection=collection, data=r.get("data", {}), created_at=r.get("created_at") or "", updated_at=r.get("updated_at") or "") for r in raw]
                return Page(data=items, has_more=False)
            items = [Document(id=r["id"], collection=collection, data=r.get("data", {}), created_at=r.get("created_at") or "", updated_at=r.get("updated_at") or "") for r in raw.get("data", [])]
            return Page(data=items, cursor=raw.get("cursor"), has_more=raw.get("has_more", False), total=raw.get("total"))

    async def update(self, collection: str, doc_id: str, data: dict) -> Document:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(f"{self._gateway_url}/v1/internal/store/{collection}/{doc_id}", json={"data": data, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            r = resp.json()
            return Document(id=r["id"], collection=collection, data=r.get("data", data), created_at=r.get("created_at") or "", updated_at=r.get("updated_at") or "")

    async def delete(self, collection: str, doc_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{self._gateway_url}/v1/internal/store/{collection}/{doc_id}", params={"extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            return resp.status_code == 200

    async def count(self, collection: str, where: dict | None = None) -> int:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/internal/store/{collection}/count", json={"where": where or {}, "extension_id": self._extension_id, "user_id": self._user_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=30)
            if resp.status_code == 404:
                return 0
            resp.raise_for_status()
            return resp.json().get("count", 0)

    async def list_users(
        self,
        collection: str,
        *,
        page_size: int = 500,
    ) -> AsyncIterator[str]:
        """Yield user_ids with records in this extension's collection.

        System-context only. Use with ``ctx.as_user(uid)`` for per-user fan-out:

            async for uid in ctx.store.list_users("wt_monitors"):
                user_ctx = ctx.as_user(uid)
                monitors = await user_ctx.store.query(
                    "wt_monitors", where={"enabled": True})
                for m in monitors.data:
                    await check_monitor(user_ctx, m)

        Invariants: I-LIST-USERS-1 (system-context guard),
                    I-LIST-USERS-4 (cursor pagination).

        Raises:
            RuntimeError: caller is not system-context.
            StoreUnavailable: Auth Gateway unreachable.
            ValueError: forbidden chars in collection or invalid page_size.
        """
        if self._user_id != "__system__":
            _emit_threat_counter(app=self._extension_id, tenant=self._tenant_id)
            raise RuntimeError(
                "ctx.store.list_users() requires system context "
                f"(got user_id={self._user_id!r}); "
                "intended for @ext.schedule / @ext.signal handlers."
            )
        if _FORBIDDEN_COLLECTION.search(collection):
            raise ValueError(f"forbidden chars in collection: {collection!r}")
        if not (1 <= page_size <= 10000):
            raise ValueError(f"page_size must be 1..10000, got {page_size}")

        cursor: str | None = None
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self._gateway_url}/v1/internal/store/{collection}/list_users",
                    params={
                        "extension_id": self._extension_id,
                        "tenant_id": self._tenant_id,
                        "cursor": cursor or "0",
                        "limit": page_size,
                    },
                    headers=self._headers(),
                    timeout=30,
                )
                if resp.status_code in (502, 503, 504):
                    raise StoreUnavailable(retry_after=30)
                resp.raise_for_status()
                try:
                    parsed = ListUsersResponse.model_validate_json(resp.text)
                except Exception as e:
                    raise StoreContractError(
                        f"invalid ListUsersResponse from Auth GW: {e}") from e
                for uid in parsed.user_ids:
                    yield uid
                if parsed.next_cursor is None:
                    return
                cursor = parsed.next_cursor

    async def query_all(
        self,
        collection: str,
        *,
        limit: int = 500,
    ) -> list[Document]:
        """Return ALL documents in collection across all users.

        System-context only. Returns list[Document] in a single HTTP call —
        use for bulk fan-out when ``ctx.store.list_users()`` + ``ctx.as_user()``
        would cause N+1 HTTP inefficiency (e.g. event_poller that reads every
        account per tick).

        ``Document.user_id`` is populated from the store row so callers can
        dispatch per-user work without a second round-trip.

        Invariants: I-LIST-USERS-1 (system-context guard — reused for query_all).

        Raises:
            RuntimeError: caller is not system-context.
            StoreUnavailable: Auth Gateway unreachable.
            ValueError: forbidden chars in collection or invalid limit.
        """
        if self._user_id != "__system__":
            _emit_threat_counter(app=self._extension_id, tenant=self._tenant_id)
            raise RuntimeError(
                "ctx.store.query_all() requires system context "
                f"(got user_id={self._user_id!r})."
            )
        if _FORBIDDEN_COLLECTION.search(collection):
            raise ValueError(f"forbidden chars in collection: {collection!r}")
        if not (1 <= limit <= 10000):
            raise ValueError(f"limit must be 1..10000, got {limit}")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._gateway_url}/v1/internal/store/{collection}/all",
                params={
                    "extension_id": self._extension_id,
                    "tenant_id": self._tenant_id,
                    "limit": limit,
                },
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code in (502, 503, 504):
                raise StoreUnavailable(retry_after=30)
            resp.raise_for_status()
            docs = resp.json() or []
            return [
                Document(
                    id=d["id"],
                    collection=collection,
                    data=d.get("data", {}),
                    created_at=d.get("created_at") or "",
                    updated_at=d.get("updated_at") or "",
                    user_id=d.get("user_id") or "",
                )
                for d in docs
            ]
