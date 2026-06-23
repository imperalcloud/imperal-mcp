from __future__ import annotations

import re
from typing import Any

import httpx

from .config import Config


class ImperalAuthError(RuntimeError):
    pass


class ImperalError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ImperalClient:
    def __init__(self, cfg: Config, token_provider=None):
        self._cfg = cfg
        self._imperal_id: str | None = None
        if token_provider is not None:
            self._token_provider = token_provider
        elif cfg.token:
            async def _static() -> str:
                return cfg.token
            self._token_provider = _static
        else:
            from . import auth

            async def _stored():
                return await auth.ensure_access_token(cfg)
            self._token_provider = _stored

    async def _headers(self) -> dict[str, str]:
        token = await self._token_provider()
        if not token:
            raise ImperalAuthError("no Imperal token — run `imperal-mcp login` or set IMPERAL_TOKEN")
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        url = f"{self._cfg.api_url}{path}"
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=60) as cli:
            resp = await cli.request(method, url, json=json, headers=headers)
        if resp.status_code >= 400:
            raise ImperalError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)
        return resp.json()

    async def whoami(self) -> str:
        if self._imperal_id is None:
            data = await self._request("GET", "/v1/auth/me")
            self._imperal_id = data.get("imperal_id") or data.get("id")
            if not self._imperal_id:
                raise ImperalError("GET /v1/auth/me did not return imperal_id")
        return self._imperal_id

    def _derive_handle(self, imperal_id: str) -> str:
        """Derive a valid, unique developer handle from the (unique) imperal_id.
        Guaranteed to satisfy the gateway handle pattern
        ^[a-z0-9][a-z0-9_-]{1,28}[a-z0-9]$ (3-30 chars)."""
        h = re.sub(r"[^a-z0-9_-]", "", imperal_id.lower())
        h = re.sub(r"^[^a-z0-9]+", "", h)
        h = re.sub(r"[^a-z0-9]+$", "", h)
        if len(h) < 3:
            h = f"dev-{h}" if h else "dev-user"
        h = h[:30]
        h = re.sub(r"[^a-z0-9]+$", "", h)  # [:30] must still end alphanumeric
        return h or "dev-user"

    async def _try_register(self, nickname: str) -> bool:
        """POST /v1/developer/register at the free explorer tier. Returns True if
        registered OR already-registered; False on a handle collision/reservation
        (caller may retry with another handle)."""
        try:
            await self._request("POST", "/v1/developer/register",
                                json={"tier": "explorer", "nickname": nickname})
            return True
        except ImperalError as e:
            msg = str(e).lower()
            if e.status_code == 400 and "already registered" in msg:
                return True
            if e.status_code == 400 and ("taken" in msg or "reserved" in msg or "invalid nickname" in msg):
                return False
            raise

    async def ensure_registered(self) -> None:
        """Idempotently ensure the caller is a registered developer (free
        `explorer` tier). No-op if already registered. Auto-derives a valid
        unique handle from imperal_id (the user can rename it later in the panel)."""
        uid = await self.whoami()
        handle = self._derive_handle(uid)
        if await self._try_register(handle):
            return
        alt = (handle[:24] + "-" + re.sub(r"[^a-z0-9]", "", uid.lower())[-4:])[:30]
        if await self._try_register(alt):
            return
        raise ImperalError(
            "could not auto-register you as a developer (free explorer tier); "
            "register manually in the Imperal panel, then retry")

    async def ensure_app(self, app_id: str, display_name: str) -> None:
        """Ensure the caller's developer app row exists. Idempotent:
        (1) auto-register the caller as a developer (free explorer),
        (2) get-or-create the app (GET first; create only if 404)."""
        await self.ensure_registered()
        try:
            await self.get_app(app_id)
            return  # already exists
        except ImperalError as e:
            if e.status_code != 404:
                raise  # a real error — surface it
        # 404 → create
        try:
            await self._request("POST", "/v1/developer/apps", json={
                "app_id": app_id,
                "display_name": display_name or app_id,
                "git_url": f"https://imperal.io/ir-apps/{app_id}",
            })
        except ImperalError as e:
            msg = str(e).lower()
            if e.status_code == 409 or "already in use" in msg or "exists" in msg:
                return  # create-race: app appeared between GET and POST — fine
            raise

    async def _dev_call(self, function: str, params: dict) -> dict:
        uid = await self.whoami()
        return await self._request("POST", "/v1/extensions/developer/call", json={
            "user_id": uid, "tenant_id": "default", "function": function, "params": params,
        })

    async def deploy_ir(self, app_id: str, ir_dict: dict) -> dict:
        return await self._dev_call("deploy_ir", {"app_id": app_id, "ir_dict": ir_dict})

    async def smoke_ir(self, ir_dict: dict, function: str, args: dict) -> dict:
        return await self._dev_call("smoke_ir", {"ir_dict": ir_dict, "function": function, "args": args})

    async def list_apps(self) -> list[dict]:
        return await self._request("GET", "/v1/developer/apps")

    async def get_app(self, app_id: str) -> dict:
        return await self._request("GET", f"/v1/developer/apps/{app_id}")

    async def get_marketplace_app(self, app_id: str) -> dict:
        """Fetch app manifest from the marketplace catalog. Returns {} on 404/error."""
        try:
            return await self._request("GET", f"/v1/marketplace/apps/{app_id}")
        except ImperalError:
            return {}

    async def run_tool(self, app_id: str, function: str, params: dict) -> dict:
        uid = await self.whoami()
        return await self._request("POST", f"/v1/extensions/{app_id}/call", json={
            "user_id": uid, "tenant_id": "default", "function": function, "params": params,
        })
