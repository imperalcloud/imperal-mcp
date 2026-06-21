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
