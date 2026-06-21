# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Notify client — POSTs notifications to Auth GW `/v1/internal/notify`.

Two invocation styles are both supported for historical reasons:

- ``await ctx.notify("message", priority="high")`` — preferred, used by every
  production extension (microsoft-ads, meta-ads, google-ads, mail, ...).
- ``await ctx.notify.send("message", channel="in_app")`` — alias for callers
  that prefer the named method (documentation / tests have historically shown
  both). Forwarded to ``__call__``.

Session 30 audit (2026-04-18): the Protocol previously declared only ``send``
while the concrete client implemented only ``__call__``. Extensions got lucky
because they called the instance directly, but ``ctx.notify.send(...)`` crashed
at runtime. We now expose both methods on the client, update the Protocol,
and keep the wire shape identical.
"""
from __future__ import annotations

import httpx


class NotifyClient:
    def __init__(self, gateway_url: str, auth_token: str = "", user_id: str = "", service_token: str = ""):
        self._gateway_url = gateway_url.rstrip("/")
        self._auth_token = auth_token or service_token
        self._user_id = user_id

    async def __call__(self, message: str, **kwargs) -> None:
        """Send a notification (preferred call-style).

        kwargs are forwarded verbatim to the Auth GW endpoint. Common keys:
        ``priority`` (``"low"``/``"normal"``/``"high"``/``"urgent"``),
        ``channel`` (``"in_app"``/``"email"``/``"telegram"`` …), ``subject``,
        ``body``. The gateway applies per-channel transport rules.
        """
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self._gateway_url}/v1/internal/notify",
                json={"user_id": self._user_id, "message": message, **kwargs},
                headers={"Authorization": f"Bearer {self._auth_token}"},
                timeout=10,
            )

    async def send(self, message: str, channel: str = "in_app", **kwargs) -> None:
        """Alias for ``__call__``. Accepts a named ``channel`` parameter.

        Equivalent to ``await ctx.notify(message, channel=channel, **kwargs)``.
        Provided because older documentation / tests use this signature.
        """
        await self(message, channel=channel, **kwargs)
