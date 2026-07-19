from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
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
# short pause before re-reading creds after a failed refresh, giving a sibling
# process time to finish writing the pair it already won the rotation race for
_SIBLING_RETRY_DELAY_S = 0.3


class NotLoggedInError(RuntimeError):
    """No usable credentials — the user must run `imperal-mcp login`."""


class TransientAuthError(RuntimeError):
    """A refresh attempt failed for a NON-verdict reason — gateway 5xx during
    a deploy, a network timeout. The session may be perfectly valid: callers
    retry; they must NEVER treat this as logged-out. Only an HTTP 401 from
    /v1/auth/refresh is the gateway's actual logout verdict."""


def gen_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def creds_path() -> Path:
    return Path(os.path.expanduser("~")) / ".imperal" / "credentials.json"


def save_creds(d: dict) -> None:
    """Write credentials atomically: temp file in the same directory, then
    ``os.replace`` onto the real path.

    ``os.replace`` is an atomic rename on POSIX (single ``rename(2)`` syscall,
    same filesystem since the temp file lives in the same directory), so a
    concurrent reader (another process, or this one) always sees either the
    old file or the fully-written new one — never a truncated/partial one.
    The previous implementation opened the destination with ``O_TRUNC`` and
    wrote in place, which briefly left the file empty if the process died
    mid-write.
    """
    p = creds_path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=".credentials.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_creds() -> dict | None:
    p = creds_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


async def _refresh(api_url: str, refresh_token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            resp = await cli.post(f"{api_url}/v1/auth/refresh",
                                  json={"refresh_token": refresh_token})
    except httpx.HTTPError as e:
        raise TransientAuthError(f"refresh transport error: {type(e).__name__}") from e
    if resp.status_code == 401:
        raise NotLoggedInError("session expired — run `imperal-mcp login`")
    if resp.status_code != 200:
        raise TransientAuthError(f"refresh failed: HTTP {resp.status_code}")
    return resp.json()


# Serializes every in-process refresh attempt. The gateway rotates refresh
# tokens SINGLE-USE (an atomic claim revokes the presented token and mints a
# new pair), so two concurrent callers in the SAME process racing the same
# on-disk refresh_token would have one winner and one loser 401ing as
# "session expired" (proven live 2026-07-15).
#
# A plain module-level ``asyncio.Lock()`` is safe to construct here at import
# time: since Python 3.10, asyncio's synchronization primitives no longer
# bind to a running loop in ``__init__`` — they bind lazily on first
# ``await`` — and this process only ever drives ONE event loop across the
# lock's whole lifetime (the MCP server owns a single long-lived loop for
# its process; the CLI's ``login``/``logout`` each call ``asyncio.run()``
# exactly once and never touch this lock). If that invariant ever changes
# (multiple concurrently-alive loops sharing this module in one process),
# switch to a per-loop lock (``{id(loop): asyncio.Lock()}``) instead of a
# single module-level instance.
_refresh_lock = asyncio.Lock()


async def ensure_access_token(cfg, force: bool = False) -> str:
    creds = load_creds()
    if not creds or not creds.get("refresh_token"):
        raise NotLoggedInError("not logged in — run `imperal-mcp login`")
    now = time.time()
    if not force and creds.get("access_token") and creds.get("access_expires_at", 0) - _REFRESH_SKEW > now:
        return creds["access_token"]

    async with _refresh_lock:
        # Re-read: a sibling in-process caller may have already refreshed
        # (and saved) while we were waiting for the lock — nothing to do.
        fresh = load_creds() or creds
        now = time.time()
        if not force and fresh.get("access_token") and fresh.get("access_expires_at", 0) - _REFRESH_SKEW > now:
            return fresh["access_token"]
        if not fresh.get("refresh_token"):
            raise NotLoggedInError("not logged in — run `imperal-mcp login`")

        attempted = fresh["refresh_token"]
        presented = attempted
        try:
            tok = await _refresh(cfg.api_url, presented)
        except NotLoggedInError:
            # Cross-PROCESS race: a sibling process sharing this on-disk
            # credentials file may have already won the single-use rotation.
            # Give its save() a moment to land, then check whether the
            # refresh_token on disk moved out from under us. If it did,
            # this wasn't a real logout — retry once with the fresh token.
            # If it's still identical, we really are logged out; re-raise.
            await asyncio.sleep(_SIBLING_RETRY_DELAY_S)
            sibling = load_creds()
            sibling_token = sibling.get("refresh_token") if sibling else None
            if not sibling_token or sibling_token == attempted:
                raise
            presented = sibling_token
            tok = await _refresh(cfg.api_url, presented)

        # Save FIRST, then return: the death-window between the gateway's
        # rotation (which already happened server-side, inside _refresh's
        # HTTP call) and this save is the one place a hard-killed process can
        # still strand a revoked refresh_token on disk — that residual risk
        # is closed server-side (grace-window task), not here; minimizing the
        # gap client-side is all the SDK can do.
        now = time.time()
        new_creds = {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token", presented),
            "access_expires_at": now + int(tok.get("expires_in", 900)),
        }
        save_creds(new_creds)
        return new_creds["access_token"]


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
