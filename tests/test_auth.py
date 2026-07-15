import asyncio
import base64, hashlib, stat
import httpx, pytest, respx
from imperal_mcp.config import Config
from imperal_mcp import auth


def test_gen_pkce_s256():
    v, c = auth.gen_pkce()
    assert 43 <= len(v) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert c == expected

def test_save_creds_is_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r", "access_token": "a", "access_expires_at": 1})
    p = auth.creds_path()
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(auth.creds_path().parent.stat().st_mode) == 0o700
    assert auth.load_creds()["refresh_token"] == "r"

def test_load_creds_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert auth.load_creds() is None

@respx.mock
@pytest.mark.asyncio
async def test_ensure_access_token_refreshes_when_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r0", "access_token": "old", "access_expires_at": 0})  # expired
    respx.post("http://gw/v1/auth/refresh").mock(return_value=httpx.Response(200, json={
        "access_token": "new", "refresh_token": "r1", "token_type": "bearer", "expires_in": 900}))
    tok = await auth.ensure_access_token(Config(api_url="http://gw", token=None))
    assert tok == "new"
    assert auth.load_creds()["refresh_token"] == "r1"  # rotation persisted

@pytest.mark.asyncio
async def test_ensure_access_token_not_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(auth.NotLoggedInError):
        await auth.ensure_access_token(Config(api_url="http://gw", token=None))

@respx.mock
@pytest.mark.asyncio
async def test_ensure_access_token_refresh_401_tells_user_to_login(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "bad", "access_token": "old", "access_expires_at": 0})
    respx.post("http://gw/v1/auth/refresh").mock(return_value=httpx.Response(401, json={"detail": "x"}))
    with pytest.raises(auth.NotLoggedInError):
        await auth.ensure_access_token(Config(api_url="http://gw", token=None))


# ── multi-process rotation race hardening ─────────────────────────────────────
# The gateway rotates refresh tokens SINGLE-USE (atomic claim revokes the
# presented token and mints a new pair). Two callers racing the same on-disk
# refresh_token — two tasks in one process, or two processes sharing the
# creds file — must not both lose. See auth.py's _refresh_lock docstring.

@pytest.mark.asyncio
async def test_ensure_access_token_concurrent_callers_refresh_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r0", "access_token": "old", "access_expires_at": 0})  # expired

    calls = {"n": 0, "concurrent": 0, "max_concurrent": 0}

    async def fake_refresh(api_url, refresh_token):
        assert refresh_token == "r0"
        calls["n"] += 1
        calls["concurrent"] += 1
        calls["max_concurrent"] = max(calls["max_concurrent"], calls["concurrent"])
        await asyncio.sleep(0.05)  # hold the "network call" open so callers overlap
        calls["concurrent"] -= 1
        return {"access_token": "new", "refresh_token": "r1", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", fake_refresh)
    cfg = Config(api_url="http://gw", token=None)
    results = await asyncio.gather(*(auth.ensure_access_token(cfg) for _ in range(5)))
    assert results == ["new"] * 5
    assert calls["n"] == 1  # exactly one underlying refresh, not five
    assert calls["max_concurrent"] == 1  # never two in flight at once
    assert auth.load_creds()["refresh_token"] == "r1"  # rotation persisted once


@pytest.mark.asyncio
async def test_ensure_access_token_retries_with_sibling_rotated_token(tmp_path, monkeypatch):
    """A sibling PROCESS shares the on-disk creds and wins the single-use
    rotation first: our attempt with the now-revoked token 401s, but the
    refresh_token on disk has moved — that's not a real logout, so we retry
    once with the fresh one and succeed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r0", "access_token": "old", "access_expires_at": 0})

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(auth.asyncio, "sleep", _no_sleep)

    presented = []

    async def fake_refresh(api_url, refresh_token):
        presented.append(refresh_token)
        if refresh_token == "r0":
            # Simulate the sibling process: it already consumed r0 and saved
            # its own rotated pair before we got a chance to re-read.
            auth.save_creds({"refresh_token": "r1-sibling", "access_token": "sibling", "access_expires_at": 0})
            raise auth.NotLoggedInError("session expired — run `imperal-mcp login`")
        assert refresh_token == "r1-sibling"
        return {"access_token": "new", "refresh_token": "r2", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", fake_refresh)
    tok = await auth.ensure_access_token(Config(api_url="http://gw", token=None))
    assert tok == "new"
    assert presented == ["r0", "r1-sibling"]  # exactly one retry, with the fresh token
    assert auth.load_creds()["refresh_token"] == "r2"


@pytest.mark.asyncio
async def test_ensure_access_token_no_retry_when_disk_token_unchanged(tmp_path, monkeypatch):
    """No sibling won the race — the refresh_token on disk after the failed
    attempt is the SAME one we just presented. That's a genuine logout:
    raise without a pointless second attempt."""
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "bad", "access_token": "old", "access_expires_at": 0})

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(auth.asyncio, "sleep", _no_sleep)

    presented = []

    async def fake_refresh(api_url, refresh_token):
        presented.append(refresh_token)
        raise auth.NotLoggedInError("session expired — run `imperal-mcp login`")

    monkeypatch.setattr(auth, "_refresh", fake_refresh)
    with pytest.raises(auth.NotLoggedInError):
        await auth.ensure_access_token(Config(api_url="http://gw", token=None))
    assert presented == ["bad"]  # exactly one attempt, zero retries


def test_save_creds_no_leftover_temp_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r0"})
    p = auth.creds_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    leftovers = [f.name for f in p.parent.iterdir() if f.name != p.name]
    assert leftovers == []  # the temp file was renamed away, not left behind


def test_save_creds_atomic_old_file_survives_write_failure(tmp_path, monkeypatch):
    """If the write to the temp file fails partway, the real credentials file
    must be untouched (atomic replace never ran) and no temp litter remains —
    proving save_creds can't leave a truncated/partial creds file on disk."""
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r0"})
    original = auth.creds_path().read_text()

    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(auth.json, "dump", _boom)
    with pytest.raises(OSError):
        auth.save_creds({"refresh_token": "r1"})

    assert auth.creds_path().read_text() == original  # untouched by the failed write
    leftovers = [f.name for f in auth.creds_path().parent.iterdir() if f.name != auth.creds_path().name]
    assert leftovers == []  # temp file cleaned up on failure


# ── device-code login (RFC 8628) ──────────────────────────────────────────────

_AUTHORIZE = {
    "device_code": "DEV123", "user_code": "WDBK-7Q3M",
    "verification_uri": "https://panel.imperal.io/device",
    "verification_uri_complete": "https://panel.imperal.io/device?code=WDBK-7Q3M",
    "expires_in": 600, "interval": 5,
}


@respx.mock
@pytest.mark.asyncio
async def test_login_device_polls_until_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _no_sleep(_):  # no real waiting between polls
        return None
    monkeypatch.setattr(auth.asyncio, "sleep", _no_sleep)

    respx.post("http://gw/v1/auth/cli/device/authorize").mock(
        return_value=httpx.Response(200, json=_AUTHORIZE))
    respx.post("http://gw/v1/auth/cli/device/token").mock(side_effect=[
        httpx.Response(200, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 900}),
    ])
    respx.get("http://gw/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"email": "dev@imperal.io"}))

    seen = {}
    def on_prompt(user_code, uri, uri_complete):
        seen.update(user_code=user_code, uri=uri, uri_complete=uri_complete)

    email = await auth.login_device(
        Config(api_url="http://gw", token=None), on_prompt=on_prompt, open_browser=False)
    assert email == "dev@imperal.io"
    assert seen["user_code"] == "WDBK-7Q3M"
    assert seen["uri"] == "https://panel.imperal.io/device"
    assert seen["uri_complete"].endswith("?code=WDBK-7Q3M")
    assert auth.load_creds()["refresh_token"] == "r"  # tokens persisted


@respx.mock
@pytest.mark.asyncio
async def test_login_device_backs_off_on_slow_down(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    slept: list = []

    async def _rec_sleep(n):
        slept.append(n)
    monkeypatch.setattr(auth.asyncio, "sleep", _rec_sleep)

    respx.post("http://gw/v1/auth/cli/device/authorize").mock(
        return_value=httpx.Response(200, json=_AUTHORIZE))
    respx.post("http://gw/v1/auth/cli/device/token").mock(side_effect=[
        httpx.Response(200, json={"error": "slow_down"}),
        httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 900}),
    ])
    respx.get("http://gw/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"email": "dev@imperal.io"}))

    await auth.login_device(Config(api_url="http://gw", token=None), open_browser=False)
    assert slept == [10]  # 5 (interval) + _SLOW_DOWN_BUMP after slow_down, then approved


@respx.mock
@pytest.mark.asyncio
async def test_login_device_access_denied_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(auth.asyncio, "sleep", _no_sleep)

    respx.post("http://gw/v1/auth/cli/device/authorize").mock(
        return_value=httpx.Response(200, json=_AUTHORIZE))
    respx.post("http://gw/v1/auth/cli/device/token").mock(
        return_value=httpx.Response(400, json={"error": "access_denied"}))

    with pytest.raises(RuntimeError, match="declined"):
        await auth.login_device(Config(api_url="http://gw", token=None), open_browser=False)


@respx.mock
@pytest.mark.asyncio
async def test_logout_revokes_and_wipes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r", "access_token": "a", "access_expires_at": 9e9})
    respx.post("http://gw/v1/auth/logout").mock(return_value=httpx.Response(200, json={"message": "Logged out"}))
    await auth.logout(Config(api_url="http://gw", token=None))
    assert auth.load_creds() is None  # creds file removed


@respx.mock
@pytest.mark.asyncio
async def test_logout_wipes_local_creds_even_when_server_errors(tmp_path, monkeypatch):
    """Best-effort revoke: a 500 from the server must NOT prevent local creds deletion."""
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r", "access_token": "a", "access_expires_at": 9e9})
    respx.post("http://gw/v1/auth/logout").mock(return_value=httpx.Response(500, text="internal error"))
    await auth.logout(Config(api_url="http://gw", token=None))
    assert auth.load_creds() is None  # local creds wiped despite server error
