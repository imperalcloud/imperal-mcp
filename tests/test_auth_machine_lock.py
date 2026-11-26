"""One refresh at a time on a machine, and a refusal that is heard once (2026-11-26).

One day of the gateway's access log: /v1/auth/refresh answered 401 1381 times and 200 703 times, every refusal from
four addresses of these clients. One machine holds one credentials file read by several processes; the lock inside
a process did not reach the others, and a process holding a refused token asked again on every call."""
import asyncio
import json
import os
import subprocess
import sys
import time

import pytest

from imperal_mcp import auth


class _Cfg:
    api_url = "https://gw.test"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "creds_path", lambda: tmp_path / ".imperal" / "credentials.json")
    return tmp_path


def _expired(token="r1"):
    auth.save_creds({"access_token": "a-old", "refresh_token": token, "access_expires_at": time.time() - 10})


def test_a_refused_token_is_asked_once_and_never_again(home, monkeypatch):
    _expired("dead")
    calls = []

    async def refuse(api_url, token):
        calls.append(token)
        raise auth.NotLoggedInError("session expired")

    monkeypatch.setattr(auth, "_refresh", refuse)
    monkeypatch.setattr(auth, "_SIBLING_RETRY_DELAY_S", 0)
    for _ in range(5):
        with pytest.raises(auth.NotLoggedInError):
            asyncio.run(auth.ensure_access_token(_Cfg()))
    assert calls == ["dead"]                       # five calls of the client, ONE request to the gateway
    assert "dead" not in auth._refused_path().read_text()        # the token itself is not written anywhere new


def test_a_new_sign_in_is_asked_again(home, monkeypatch):
    _expired("dead")

    async def refuse(api_url, token):
        raise auth.NotLoggedInError("session expired")

    monkeypatch.setattr(auth, "_refresh", refuse)
    monkeypatch.setattr(auth, "_SIBLING_RETRY_DELAY_S", 0)
    with pytest.raises(auth.NotLoggedInError):
        asyncio.run(auth.ensure_access_token(_Cfg()))
    _expired("fresh")                               # a sign-in wrote a new token

    async def grant(api_url, token):
        return {"access_token": "a-new", "refresh_token": token + "+", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", grant)
    assert asyncio.run(auth.ensure_access_token(_Cfg())) == "a-new"


def test_a_failure_that_is_no_verdict_is_not_remembered(home, monkeypatch):
    _expired("r1")

    async def down(api_url, token):
        raise auth.TransientAuthError("refresh failed: HTTP 502")

    monkeypatch.setattr(auth, "_refresh", down)
    with pytest.raises(auth.TransientAuthError):
        asyncio.run(auth.ensure_access_token(_Cfg()))
    assert not auth._refused_path().exists()


def test_what_the_disk_holds_after_the_wait_decides(home, monkeypatch):
    _expired("r1")
    asked = []

    async def grant(api_url, token):
        asked.append(token)
        return {"access_token": "never", "refresh_token": "x", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", grant)

    def sibling_refreshed_meanwhile(wait=None):
        auth.save_creds({"access_token": "a-sibling", "refresh_token": "r2", "access_expires_at": time.time() + 900})
        return None

    monkeypatch.setattr(auth, "_machine_lock", sibling_refreshed_meanwhile)
    assert asyncio.run(auth.ensure_access_token(_Cfg())) == "a-sibling" and asked == []


def test_the_lock_is_one_per_machine_and_a_dead_holder_frees_it(home):
    first = auth._machine_lock(wait=0.2)
    assert first is not None
    # another PROCESS cannot take it while this one holds it...
    code = ("import sys; from pathlib import Path; from imperal_mcp import auth; "
            "auth.creds_path = lambda: Path(sys.argv[1]) / '.imperal' / 'credentials.json'; "
            "fd = auth._machine_lock(wait=0.3); print('got' if fd is not None else 'busy')")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    out = subprocess.run([sys.executable, "-c", code, str(home)], capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "busy", out.stderr[-300:]
    auth._machine_unlock(first)
    # ...and takes it at once when it is let go
    out = subprocess.run([sys.executable, "-c", code, str(home)], capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "got", out.stderr[-300:]


def test_a_lock_that_cannot_be_taken_never_stops_a_sign_in(home, monkeypatch):
    _expired("r1")
    monkeypatch.setattr(auth, "_machine_lock", lambda wait=None: None)

    async def grant(api_url, token):
        return {"access_token": "a-new", "refresh_token": "r2", "expires_in": 900}

    monkeypatch.setattr(auth, "_refresh", grant)
    assert asyncio.run(auth.ensure_access_token(_Cfg())) == "a-new"
    assert json.loads(auth.creds_path().read_text())["refresh_token"] == "r2"
