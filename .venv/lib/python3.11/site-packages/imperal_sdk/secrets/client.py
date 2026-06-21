"""SecretClient — thin HTTP proxy from SDK to auth-gw /v1/secrets/*.

Federal contract:
- NEVER caches plaintext between calls (I-SECRETS-HANDLER-SCOPE-MEMORY).
- Validates name against manifest declarations (I-SECRETS-CONTRACT-DECLARED).
- Validates write_mode before PUT/DELETE/rotate.
- Translates auth-gw 503 → SecretVaultUnavailable.
- Returns None for 404 SECRET_NOT_SET (declared but no value yet).

Dev mode (when ``IMPERAL_DEV_MODE=true``):
- get(name) reads ``IMPERAL_SECRET_<UPPER_NAME>`` env var
- set/delete/rotate are no-ops with a WARN log (manifest contract still enforced)
- list() reflects env-var presence

Pytest: inject a MockSecretStore via fixture; see imperal_sdk.testing.MockSecretStore.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from imperal_sdk.secrets.exceptions import (
    SecretNotDeclaredError,
    SecretWriteForbidden,
    SecretVaultUnavailable,
    SecretValueTooLarge,
)
from imperal_sdk.secrets.spec import SecretSpec

log = logging.getLogger(__name__)

SDK_HTTP_TIMEOUT_S = 5.0


@dataclass
class SecretStatus:
    """Returned by ``ctx.secrets.list()``. NEVER carries the value itself."""
    name: str
    description: str
    is_set: bool
    last_accessed_at: Optional[int]


def _dev_mode_active() -> bool:
    return os.getenv("IMPERAL_DEV_MODE", "").lower() in {"1", "true", "yes", "on"}


def _dev_env_key(name: str) -> str:
    return f"IMPERAL_SECRET_{name.upper()}"


class SecretClient:
    """Source-inspection contract: NO module-level cache, NO @lru_cache,
    NO instance attribute holding plaintext between calls. Plaintext is
    only ever a local variable in get()'s return path."""

    def __init__(
        self,
        *,
        ext_id: str,
        imperal_id: str,
        auth_gw_base: str,
        session_token: str,
        declared: dict[str, SecretSpec],
    ):
        self._ext_id = ext_id
        self._imperal_id = imperal_id
        self._base = auth_gw_base.rstrip("/")
        self._token = session_token
        self._declared = declared

    def _headers(self, *, json: bool = False) -> dict:
        h = {
            "Authorization": f"Bearer {self._token}",
            "X-Acting-User": self._imperal_id,
            "X-Ext-Id": self._ext_id,
        }
        if json:
            h["Content-Type"] = "application/json"
        return h

    def _ensure_declared(self, name: str) -> SecretSpec:
        if name not in self._declared:
            raise SecretNotDeclaredError(
                f"secret name={name!r} not in manifest for ext_id={self._ext_id!r}"
            )
        return self._declared[name]

    async def get(self, name: str) -> Optional[str]:
        self._ensure_declared(name)

        if _dev_mode_active():
            return os.getenv(_dev_env_key(name))

        try:
            async with httpx.AsyncClient(timeout=SDK_HTTP_TIMEOUT_S) as c:
                r = await c.get(
                    f"{self._base}/v1/secrets/{self._ext_id}/{name}",
                    headers=self._headers(),
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            raise SecretVaultUnavailable(
                f"auth-gw unreachable on get(name={name!r}): {type(e).__name__}"
            ) from None
        if r.status_code == 200:
            return r.json().get("value")
        if r.status_code == 404:
            return None
        if r.status_code == 503:
            raise SecretVaultUnavailable(
                f"auth-gw 503 on get(name={name!r})"
            )
        raise RuntimeError(
            f"unexpected auth-gw status {r.status_code} on get(name={name!r})"
        )

    async def set(self, name: str, value: str) -> None:
        spec = self._ensure_declared(name)
        if spec.write_mode == "user":
            raise SecretWriteForbidden(
                f"secret name={name!r} has write_mode='user'; only Panel UI can "
                f"write. Declare write_mode='extension' or 'both' to allow."
            )
        if len(value.encode("utf-8")) > spec.max_bytes:
            raise SecretValueTooLarge(
                f"value ({len(value.encode())} bytes) exceeds "
                f"max_bytes={spec.max_bytes} for name={name!r}"
            )
        if _dev_mode_active():
            log.warning(
                "secret writes ignored in dev mode (name=%s, ext_id=%s)",
                name, self._ext_id,
            )
            return

        try:
            async with httpx.AsyncClient(timeout=SDK_HTTP_TIMEOUT_S) as c:
                r = await c.put(
                    f"{self._base}/v1/secrets/{self._ext_id}/{name}",
                    headers=self._headers(json=True),
                    json={"value": value},
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            raise SecretVaultUnavailable(
                f"auth-gw unreachable on set(name={name!r}): {type(e).__name__}"
            ) from None
        if r.status_code == 200:
            return
        if r.status_code == 503:
            raise SecretVaultUnavailable(f"auth-gw 503 on set(name={name!r})")
        raise RuntimeError(
            f"unexpected auth-gw status {r.status_code} on set(name={name!r})"
        )

    async def delete(self, name: str) -> bool:
        spec = self._ensure_declared(name)
        if spec.write_mode == "user":
            raise SecretWriteForbidden(
                f"secret name={name!r} write_mode='user' — only Panel can delete"
            )
        if _dev_mode_active():
            log.warning("secret deletes ignored in dev mode (name=%s)", name)
            return False

        try:
            async with httpx.AsyncClient(timeout=SDK_HTTP_TIMEOUT_S) as c:
                r = await c.delete(
                    f"{self._base}/v1/secrets/{self._ext_id}/{name}",
                    headers=self._headers(),
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            raise SecretVaultUnavailable(
                f"auth-gw unreachable on delete(name={name!r}): {type(e).__name__}"
            ) from None
        if r.status_code == 200:
            return bool(r.json().get("was_set", False))
        raise RuntimeError(
            f"unexpected auth-gw status {r.status_code} on delete(name={name!r})"
        )

    async def is_set(self, name: str) -> bool:
        self._ensure_declared(name)
        if _dev_mode_active():
            return os.getenv(_dev_env_key(name)) is not None

        try:
            async with httpx.AsyncClient(timeout=SDK_HTTP_TIMEOUT_S) as c:
                r = await c.get(
                    f"{self._base}/v1/secrets/{self._ext_id}/{name}/meta",
                    headers=self._headers(),
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            raise SecretVaultUnavailable(
                f"auth-gw unreachable on is_set(name={name!r}): {type(e).__name__}"
            ) from None
        if r.status_code == 200:
            return bool(r.json().get("is_set", False))
        if r.status_code == 404:
            return False
        raise RuntimeError(
            f"unexpected auth-gw status {r.status_code} on is_set(name={name!r})"
        )

    async def list(self) -> list[SecretStatus]:
        if _dev_mode_active():
            return [
                SecretStatus(
                    name=n,
                    description=s.description,
                    is_set=os.getenv(_dev_env_key(n)) is not None,
                    last_accessed_at=None,
                )
                for n, s in self._declared.items()
            ]

        try:
            async with httpx.AsyncClient(timeout=SDK_HTTP_TIMEOUT_S) as c:
                r = await c.get(
                    f"{self._base}/v1/secrets/{self._ext_id}",
                    headers=self._headers(),
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            raise SecretVaultUnavailable(
                f"auth-gw unreachable on list(): {type(e).__name__}"
            ) from None
        if r.status_code == 200:
            return [
                SecretStatus(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    is_set=bool(item.get("is_set", False)),
                    last_accessed_at=item.get("last_accessed_at"),
                )
                for item in r.json()
            ]
        raise RuntimeError(f"unexpected auth-gw status {r.status_code} on list()")
