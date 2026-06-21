from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import httpx

# refresh this many seconds before the access token's stated expiry
_REFRESH_SKEW = 60


class NotLoggedInError(RuntimeError):
    """No usable credentials — the user must run `imperal-mcp login`."""


def gen_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def creds_path() -> Path:
    return Path(os.path.expanduser("~")) / ".imperal" / "credentials.json"


def save_creds(d: dict) -> None:
    p = creds_path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    # write 0600 atomically
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.chmod(p, 0o600)


def load_creds() -> dict | None:
    p = creds_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


async def _refresh(api_url: str, refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as cli:
        resp = await cli.post(f"{api_url}/v1/auth/refresh", json={"refresh_token": refresh_token})
    if resp.status_code != 200:
        raise NotLoggedInError("session expired — run `imperal-mcp login`")
    return resp.json()


async def ensure_access_token(cfg) -> str:
    creds = load_creds()
    if not creds or not creds.get("refresh_token"):
        raise NotLoggedInError("not logged in — run `imperal-mcp login`")
    now = time.time()
    if creds.get("access_token") and creds.get("access_expires_at", 0) - _REFRESH_SKEW > now:
        return creds["access_token"]
    tok = await _refresh(cfg.api_url, creds["refresh_token"])
    creds = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", creds["refresh_token"]),
        "access_expires_at": now + int(tok.get("expires_in", 900)),
    }
    save_creds(creds)
    return creds["access_token"]
