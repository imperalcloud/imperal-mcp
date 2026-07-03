# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
import time
import logging

import httpx
import jwt
from jwt import PyJWKClient

from imperal_sdk.types.identity import UserContext

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


class ImperalAuth:
    def __init__(self, gateway_url: str = "https://auth.imperal.io"):
        self._gateway_url = gateway_url.rstrip("/")
        self._jwks_client: PyJWKClient | None = None
        self._jwks_last_refresh: float = 0
        self._jwks_cache_seconds: int = 3600

    def _get_jwks_client(self) -> PyJWKClient:
        now = time.time()
        if self._jwks_client is None or (now - self._jwks_last_refresh) > self._jwks_cache_seconds:
            jwks_url = f"{self._gateway_url}/v1/auth/.well-known/jwks.json"
            self._jwks_client = PyJWKClient(jwks_url)
            self._jwks_last_refresh = now
        return self._jwks_client

    def verify(self, token: str) -> UserContext:
        try:
            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token, signing_key.key, algorithms=["RS256"],
                options={"require": ["sub", "exp", "iat"]},
            )
            return UserContext(
                imperal_id=payload["sub"],
                email=payload.get("email", ""),
                tenant_id=payload.get("tenant_id", "default"),
                org_id=payload.get("org_id"),
                role=payload.get("role", "user"),
                scopes=payload.get("scopes", []),
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("Token expired")
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid token: {e}")
        except Exception as e:
            self._jwks_client = None
            try:
                jwks_client = self._get_jwks_client()
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(token, signing_key.key, algorithms=["RS256"])
                return UserContext(
                    imperal_id=payload["sub"],
                    email=payload.get("email", ""),
                    tenant_id=payload.get("tenant_id", "default"),
                    org_id=payload.get("org_id"),
                    role=payload.get("role", "user"),
                    scopes=payload.get("scopes", []),
                )
            except Exception:
                raise AuthError(f"Token verification failed: {e}")

    async def get_user_info(self, token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._gateway_url}/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
