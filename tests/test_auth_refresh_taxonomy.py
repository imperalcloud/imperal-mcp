import httpx
import pytest
import respx

from imperal_mcp.config import Config
from imperal_mcp import auth
from imperal_mcp.auth import NotLoggedInError, TransientAuthError


# ── _refresh: 401 is the ONLY logout verdict; everything else is transient ────
# A 401 from /v1/auth/refresh is the gateway's actual "you are logged out"
# verdict. A 5xx (e.g. mid-deploy) or a transport-level failure (timeout,
# connection reset) says nothing about the session's validity — callers must
# be able to retry those without the client wrongly declaring the user logged
# out and demanding `imperal-mcp login` again.

@respx.mock
@pytest.mark.asyncio
async def test_refresh_401_is_verdict():
    respx.post("https://x/v1/auth/refresh").mock(return_value=httpx.Response(401))
    with pytest.raises(NotLoggedInError):
        await auth._refresh("https://x", "rt")


@respx.mock
@pytest.mark.asyncio
async def test_refresh_502_is_transient_not_logout():
    respx.post("https://x/v1/auth/refresh").mock(return_value=httpx.Response(502))
    with pytest.raises(TransientAuthError):
        await auth._refresh("https://x", "rt")


@respx.mock
@pytest.mark.asyncio
async def test_refresh_network_error_is_transient():
    respx.post("https://x/v1/auth/refresh").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(TransientAuthError):
        await auth._refresh("https://x", "rt")


# ── ensure_access_token(force=) ────────────────────────────────────────────────
# Stream-resilience callers (Tasks 2-3) need a way to force a refresh even when
# the cached access token isn't expired yet (e.g. the gateway rejected it
# mid-stream despite a not-yet-expired local clock). Default behavior (the
# unexpired shortcut) must be unchanged when force is not requested.

@pytest.mark.asyncio
async def test_force_refresh_ignores_unexpired_access_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"access_token": "OLD", "refresh_token": "rt", "access_expires_at": 9999999999})

    async def _fake_refresh(api_url, rt):
        return {"access_token": "NEW", "refresh_token": "rt2", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", _fake_refresh)

    cfg = Config(api_url="https://x", token=None)
    assert await auth.ensure_access_token(cfg) == "OLD"              # default: shortcut
    assert await auth.ensure_access_token(cfg, force=True) == "NEW"  # force: refresh now
    assert auth.load_creds()["access_token"] == "NEW"
