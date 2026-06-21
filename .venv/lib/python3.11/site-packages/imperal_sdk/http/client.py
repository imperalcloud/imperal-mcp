# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
import httpx

from imperal_sdk.types.models import HTTPResponse


def _wrap(resp: httpx.Response) -> HTTPResponse:
    """Convert httpx.Response to typed HTTPResponse."""
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        try:
            body = resp.json()
        except Exception:
            body = resp.text
    elif resp.content:
        try:
            body = resp.text
        except Exception:
            body = resp.content
    else:
        body = ""
    return HTTPResponse(status_code=resp.status_code, body=body, headers=dict(resp.headers))


class HTTPClient:
    """Federal HTTP client.

    Per-call ``timeout=`` kwarg overrides the instance default. Federal
    cap is 180 seconds (``I-LONGRUN-HTTP-CAP-180S``) — anything longer
    must use :func:`ctx.background_task` instead.
    """

    def __init__(
        self,
        timeout: float = 30,
        max_redirects: int = 5,
        max_timeout: float = 180,
    ):
        self._timeout = timeout
        self._max_timeout = max_timeout
        self._max_redirects = max_redirects

    def _resolve_timeout(self, override: float | None) -> float:
        if override is None:
            return self._timeout
        if override <= 0:
            raise ValueError(f"ctx.http timeout must be > 0; got {override}")
        if override > self._max_timeout:
            raise ValueError(
                f"ctx.http timeout {override}s exceeds federal cap "
                f"({self._max_timeout}s). For >180s use ctx.background_task() "
                f"— see concepts/long-running-operations."
            )
        return override

    async def get(self, url: str, *, timeout: float | None = None, **kwargs) -> HTTPResponse:
        t = self._resolve_timeout(timeout)
        async with httpx.AsyncClient(timeout=t, follow_redirects=True,
                                     max_redirects=self._max_redirects) as c:
            return _wrap(await c.get(url, **kwargs))

    async def post(self, url: str, *, timeout: float | None = None, **kwargs) -> HTTPResponse:
        t = self._resolve_timeout(timeout)
        async with httpx.AsyncClient(timeout=t, follow_redirects=True,
                                     max_redirects=self._max_redirects) as c:
            return _wrap(await c.post(url, **kwargs))

    async def put(self, url: str, *, timeout: float | None = None, **kwargs) -> HTTPResponse:
        t = self._resolve_timeout(timeout)
        async with httpx.AsyncClient(timeout=t, follow_redirects=True,
                                     max_redirects=self._max_redirects) as c:
            return _wrap(await c.put(url, **kwargs))

    async def patch(self, url: str, *, timeout: float | None = None, **kwargs) -> HTTPResponse:
        t = self._resolve_timeout(timeout)
        async with httpx.AsyncClient(timeout=t, follow_redirects=True,
                                     max_redirects=self._max_redirects) as c:
            return _wrap(await c.patch(url, **kwargs))

    async def delete(self, url: str, *, timeout: float | None = None, **kwargs) -> HTTPResponse:
        t = self._resolve_timeout(timeout)
        async with httpx.AsyncClient(timeout=t, follow_redirects=True,
                                     max_redirects=self._max_redirects) as c:
            return _wrap(await c.delete(url, **kwargs))
