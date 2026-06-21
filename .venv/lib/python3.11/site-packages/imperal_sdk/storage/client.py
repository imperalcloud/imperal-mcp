# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
import httpx

from imperal_sdk.types.models import FileInfo
from imperal_sdk.types.pagination import Page


class StorageClient:
    def __init__(self, gateway_url: str, auth_token: str = "", extension_id: str = "", tenant_id: str = "default", service_token: str = ""):
        self._gateway_url = gateway_url.rstrip("/")
        self._auth_token = auth_token or service_token
        self._extension_id = extension_id
        self._tenant_id = tenant_id

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._auth_token}"}

    async def upload(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> FileInfo:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._gateway_url}/v1/internal/storage/upload", files={"file": (path, data, content_type)}, data={"path": path, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            raw = resp.json()
            return FileInfo(
                path=path,
                size=raw.get("size", len(data)),
                content_type=content_type,
                created_at=raw.get("created_at", ""),
                url=raw.get("url", ""),
            )

    async def download(self, path: str) -> bytes:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._gateway_url}/v1/internal/storage/download", params={"path": path, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            return resp.content

    async def delete(self, path: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{self._gateway_url}/v1/internal/storage", params={"path": path, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=10)
            return resp.status_code == 200

    async def list(self, prefix: str = "") -> Page[FileInfo]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._gateway_url}/v1/internal/storage/list", params={"prefix": prefix, "extension_id": self._extension_id, "tenant_id": self._tenant_id}, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            # Support both list-of-strings and list-of-dicts responses
            files_raw = raw.get("files", [])
            items: list[FileInfo] = []
            for f in files_raw:
                if isinstance(f, str):
                    items.append(FileInfo(path=f))
                else:
                    items.append(FileInfo(
                        path=f.get("path", ""),
                        size=f.get("size", 0),
                        content_type=f.get("content_type", ""),
                        created_at=f.get("created_at", ""),
                        url=f.get("url", ""),
                    ))
            return Page(data=items, has_more=raw.get("has_more", False), cursor=raw.get("cursor"), total=raw.get("total"))
