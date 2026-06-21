# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
from __future__ import annotations
from fastapi import Header, HTTPException
from imperal_sdk.auth.client import ImperalAuth, AuthError
from imperal_sdk.types.identity import UserContext


def require_auth(auth: ImperalAuth | None = None, gateway_url: str = "https://auth.imperal.io"):
    _auth = auth or ImperalAuth(gateway_url)

    async def dependency(authorization: str | None = Header(None)) -> UserContext:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        token = authorization.removeprefix("Bearer ")
        try:
            return _auth.verify(token)
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e))

    return dependency


def require_scope(*required_scopes: str, auth: ImperalAuth | None = None, gateway_url: str = "https://auth.imperal.io"):
    _auth_dep = require_auth(auth=auth, gateway_url=gateway_url)

    async def dependency(authorization: str | None = Header(None)) -> UserContext:
        user = await _auth_dep(authorization)
        for scope in required_scopes:
            if not user.has_scope(scope):
                raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
        return user

    return dependency
