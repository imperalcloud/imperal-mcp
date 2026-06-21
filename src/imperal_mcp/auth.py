from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
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


# ── Loopback login flow ───────────────────────────────────────────────────────

async def exchange_code(api_url: str, code: str, code_verifier: str, redirect_uri: str) -> dict:
    """POST /v1/auth/cli/token; returns the TokenResponse dict; raises RuntimeError on non-200."""
    async with httpx.AsyncClient(timeout=30) as cli:
        resp = await cli.post(f"{api_url}/v1/auth/cli/token", json={
            "code": code, "code_verifier": code_verifier, "redirect_uri": redirect_uri,
        })
    if resp.status_code != 200:
        raise RuntimeError(f"login failed: {resp.status_code} {resp.text[:200]}")
    return resp.json()


_OK_HTML = b"<html><body><h2>imperal-mcp: you're logged in.</h2>You can close this tab.</body></html>"
_ERR_HTML = b"<html><body><h2>imperal-mcp: login was cancelled or failed.</h2></body></html>"


class _LoopbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path)
        if q.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(q.query)
        _LoopbackHandler.captured = {k: v[0] for k, v in params.items()}
        ok = "code" in _LoopbackHandler.captured
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_OK_HTML if ok else _ERR_HTML)

    def log_message(self, *a):  # silence server log output
        pass


def login(cfg, *, open_browser: bool = True) -> str:
    """Full PKCE loopback login flow; returns the logged-in email."""
    verifier, challenge = gen_pkce()
    state = secrets.token_urlsafe(24)
    _LoopbackHandler.captured = {}

    server = http.server.HTTPServer(("127.0.0.1", 0), _LoopbackHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    panel = getattr(cfg, "panel_url", None) or "https://panel.imperal.io"
    qs = urllib.parse.urlencode({
        "redirect_uri": redirect_uri, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    url = f"{panel}/cli-authorize?{qs}"

    # Serve exactly one request in a background thread
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    print(f"Opening {url}")
    if open_browser:
        webbrowser.open(url)
    t.join(timeout=300)
    server.server_close()

    cap = _LoopbackHandler.captured
    if cap.get("state") != state:
        raise RuntimeError("state mismatch — aborting login")
    if "code" not in cap:
        raise RuntimeError(f"login not completed: {cap.get('error', 'no code')}")

    tok = asyncio.run(exchange_code(cfg.api_url, cap["code"], verifier, redirect_uri))
    save_creds({
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": time.time() + int(tok.get("expires_in", 900)),
    })
    # Confirm identity
    return asyncio.run(_whoami_email(cfg.api_url, tok["access_token"]))


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
