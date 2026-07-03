from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from pathlib import Path

import httpx

# refresh this many seconds before the access token's stated expiry
_REFRESH_SKEW = 60
# poll interval (s) used if the gateway doesn't specify one
_DEFAULT_POLL_INTERVAL = 5
# extra seconds added to the poll interval on a slow_down signal
_SLOW_DOWN_BUMP = 5


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


# ── Device-authorization-grant login (RFC 8628) ───────────────────────────────
# ONE mechanism for every surface — local, SSH, WSL, container, headless. The
# terminal shows a short user_code + a URL; the user opens the URL in ANY
# browser (even on a phone), enters the code, and the terminal polls until it
# receives tokens. No loopback callback, so it works identically remote & local.

def _default_prompt(user_code: str, verification_uri: str, verification_uri_complete: str) -> None:
    print()
    print("  To sign in, open this URL in any browser:")
    print(f"    {verification_uri}")
    print(f"  and enter the code:  {user_code}")
    print()


async def login_device(cfg, *, on_prompt=None, open_browser: bool = True) -> str:
    """Log in via the device-authorization grant; returns the logged-in email.

    ``on_prompt(user_code, verification_uri, verification_uri_complete)`` shows
    the code + URL to the user. It defaults to printing to stdout; the webbee
    dock passes its own renderer so the prompt lands in the action feed (in a
    full-screen UI a bare ``print`` would be invisible).
    """
    show = on_prompt or _default_prompt
    verifier, challenge = gen_pkce()

    async with httpx.AsyncClient(timeout=30) as cli:
        resp = await cli.post(
            f"{cfg.api_url}/v1/auth/cli/device/authorize",
            json={"code_challenge": challenge, "code_challenge_method": "S256"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"could not start login: {resp.status_code} {resp.text[:200]}")
        start = resp.json()

        device_code = start["device_code"]
        verification_uri = start["verification_uri"]
        verification_uri_complete = start.get("verification_uri_complete", verification_uri)
        interval = int(start.get("interval", _DEFAULT_POLL_INTERVAL))
        deadline = time.monotonic() + int(start.get("expires_in", 600))

        show(start["user_code"], verification_uri, verification_uri_complete)
        if open_browser:
            try:
                webbrowser.open(verification_uri_complete)
            except Exception:
                pass  # headless / no browser — the user opens the URL themselves

        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("login timed out — re-run the command to try again.")
            poll = await cli.post(
                f"{cfg.api_url}/v1/auth/cli/device/token",
                json={"device_code": device_code, "code_verifier": verifier},
            )
            data = poll.json() if poll.content else {}
            if poll.status_code == 200 and data.get("access_token"):
                tok = data
                break
            if poll.status_code == 200:
                # Not ready yet: keep polling; back off further on slow_down.
                if data.get("error") == "slow_down":
                    interval += _SLOW_DOWN_BUMP
                await asyncio.sleep(interval)
                continue
            # Terminal error (4xx): stop polling.
            err = data.get("error", f"http {poll.status_code}")
            if err == "access_denied":
                raise RuntimeError("login was declined in the browser.")
            if err == "expired_token":
                raise RuntimeError("login expired — re-run the command to try again.")
            raise RuntimeError(f"login failed: {err}")

    save_creds({
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": time.time() + int(tok.get("expires_in", 900)),
    })
    return await _whoami_email(cfg.api_url, tok["access_token"])


async def _whoami_email(api_url: str, access_token: str) -> str:
    async with httpx.AsyncClient(timeout=20) as cli:
        resp = await cli.get(f"{api_url}/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code == 200:
        return resp.json().get("email", "(unknown)")
    return "(unknown)"


async def logout(cfg) -> None:
    """Revoke the stored refresh token (best-effort), then delete the creds file."""
    creds = load_creds()
    if creds and creds.get("refresh_token"):
        try:
            async with httpx.AsyncClient(timeout=20) as cli:
                await cli.post(
                    f"{cfg.api_url}/v1/auth/logout",
                    json={"refresh_token": creds["refresh_token"]},
                )
        except httpx.HTTPError:
            pass  # best-effort server revoke; always wipe local creds
    p = creds_path()
    if p.exists():
        p.unlink()
