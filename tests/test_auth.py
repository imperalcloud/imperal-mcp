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
