# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Skeleton HTTP client.

v1.6.0 breaking changes:

- ``SkeletonClient.update()`` removed. The kernel ``skeleton_save_section``
  platform operation is the sole writer. Extensions return fresh data from
  their ``@ext.skeleton`` tool and the kernel persists it.
- URL path rewritten to ``/v1/internal/skeleton/{app_id}/{user_id}/{section}``
  (app_id FIRST, matches Auth GW v1.6.0 router + kernel canonical platform
  state store key for this section). Query-string ``extension_id``
  parameter removed.
- Constructor accepts a ``call_token`` (HMAC call-token from
  :mod:`imperal_sdk.security.call_token`). Sent as ``Authorization:
  ImperalCallToken <token>`` alongside the historical ``X-Service-Token``.
"""
from __future__ import annotations
from typing import Any
import httpx


class SkeletonClient:
    """Read-only HTTP client for kernel-persisted skeleton sections."""

    def __init__(
        self,
        gateway_url: str,
        auth_token: str = "",
        extension_id: str = "",
        user_id: str = "",
        service_token: str = "",
        call_token: str = "",
    ):
        self._gateway_url = gateway_url.rstrip("/")
        self._token = auth_token or service_token
        self._extension_id = extension_id
        self._user_id = user_id
        self._call_token = call_token

    def _headers(self) -> dict:
        h = {"X-Service-Token": self._token}
        if self._call_token:
            h["Authorization"] = f"ImperalCallToken {self._call_token}"
        return h

    async def get(self, section: str) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._gateway_url}/v1/internal/skeleton/"
                f"{self._extension_id}/{self._user_id}/{section}",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json().get("data")
