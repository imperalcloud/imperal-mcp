"""HMAC-SHA256 short-lived call tokens for Imperal internal service-to-service auth.

Kernel mints tokens per tool invocation; Auth GW verifies. Shared module
guarantees both sides use the same implementation (SDK version pinning
ties kernel and Auth GW together).
"""
from __future__ import annotations

import base64
import binascii
import hmac
import hashlib
import json
import secrets
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


ToolType = Literal["skeleton", "panel", "tool", "chat_fn"]

# Generous upper bound; canonical tokens are ~300-400 bytes. Guards against
# DoS on signature/base64 work for pathological inputs.
_MAX_TOKEN_LEN = 2048


class CallTokenClaims(BaseModel):
    tool_type: ToolType
    app_id: str
    user_id: str
    iat: int
    exp: int
    jti: str = Field(..., min_length=16)


class CallTokenError(ValueError):
    """Raised when a call token fails mint or verify. Caller maps to HTTP 401/403."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical_payload(claims: CallTokenClaims) -> bytes:
    """JSON with sorted keys and compact separators for deterministic signing."""
    return json.dumps(
        claims.model_dump(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def mint_call_token(
    tool_type: ToolType,
    app_id: str,
    user_id: str,
    ttl_seconds: int,
    hmac_secret: bytes,
) -> str:
    """Produce a signed token string: <payload_b64>.<sig_b64>.

    Args:
        ttl_seconds: Negative values allowed for tests (produces expired token).
        hmac_secret: Signing key. Same bytes must appear in the verify-side
            rotation list.
    """
    now = int(time.time())
    claims = CallTokenClaims(
        tool_type=tool_type,
        app_id=app_id,
        user_id=user_id,
        iat=now,
        exp=now + ttl_seconds,
        jti=secrets.token_urlsafe(16),
    )
    payload = _canonical_payload(claims)
    sig = hmac.new(hmac_secret, payload, hashlib.sha256).digest()
    return _b64e(payload) + "." + _b64e(sig)


async def _verify_common(
    token: str,
    hmac_secrets: list[bytes],
    redis,
) -> CallTokenClaims:
    """Shared verify path: signature + structure + expiry + replay.

    Callers add scope checks (tool_type, app_id, user_id) on top.
    """
    if len(token) > _MAX_TOKEN_LEN:
        raise CallTokenError("token length exceeds limit")
    if "." not in token:
        raise CallTokenError("malformed call token")
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except (binascii.Error, ValueError) as e:
        raise CallTokenError(f"malformed call token: {e}")

    for s in hmac_secrets:
        expected = hmac.new(s, payload, hashlib.sha256).digest()
        if hmac.compare_digest(sig, expected):
            break
    else:
        raise CallTokenError("invalid call token signature")

    try:
        claims = CallTokenClaims.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValidationError) as e:
        raise CallTokenError(f"malformed call token payload: {e}")

    now = int(time.time())
    # RFC 7519 § 4.1.4: current time MUST be before the expiration —
    # equal ⇒ expired.
    if claims.exp <= now:
        raise CallTokenError("call token expired")

    # Replay protection: SETNX jti with TTL of remaining validity.
    ttl = max(1, claims.exp - now)
    acquired = await redis.set(
        f"imperal:calltoken:jti:{claims.jti}", "1", nx=True, ex=ttl
    )
    if not acquired:
        raise CallTokenError("call token replayed")

    return claims


async def verify_call_token(
    token: str,
    required_tool_type: ToolType,
    required_app_id: str,
    required_user_id: str,
    hmac_secrets: list[bytes],
    redis,
) -> CallTokenClaims:
    """Verify signature + claims + freshness + replay. Raises CallTokenError.

    `hmac_secrets` is ordered [current, prev...] for rotation support.
    """
    claims = await _verify_common(token, hmac_secrets, redis)
    if claims.tool_type != required_tool_type:
        raise CallTokenError("tool_type mismatch")
    if claims.app_id != required_app_id:
        raise CallTokenError("app_id mismatch")
    if claims.user_id != required_user_id:
        raise CallTokenError("user_id mismatch")
    return claims


async def verify_call_token_any_tool_type(
    token: str,
    required_app_id: str,
    required_user_id: str,
    hmac_secrets: list[bytes],
    redis,
) -> CallTokenClaims:
    """Variant for endpoints accessible from any tool context (e.g. ctx.cache).

    Enforces app_id + user_id + signature + freshness + replay. Does NOT
    enforce specific tool_type.
    """
    claims = await _verify_common(token, hmac_secrets, redis)
    if claims.app_id != required_app_id:
        raise CallTokenError("app_id mismatch")
    if claims.user_id != required_user_id:
        raise CallTokenError("user_id mismatch")
    return claims
