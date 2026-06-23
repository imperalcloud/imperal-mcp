import json

import httpx
import pytest
import respx

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient, ImperalAuthError, ImperalError
from imperal_mcp.auth import NotLoggedInError

CFG = Config(api_url="http://gw", token="jwt-abc")


@pytest.mark.asyncio
async def test_requires_token(tmp_path, monkeypatch):
    # With no token and no stored credentials, the client raises an auth-related error.
    # Use a clean tmp home so real on-disk creds don't interfere.
    monkeypatch.setenv("HOME", str(tmp_path))
    c = ImperalClient(Config(api_url="http://gw", token=None))
    with pytest.raises((ImperalAuthError, NotLoggedInError)):
        await c.whoami()


@respx.mock
@pytest.mark.asyncio
async def test_whoami_and_deploy_forward_imperal_id():
    respx.get("http://gw/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"imperal_id": "imp_u_1"})
    )
    deploy = respx.post("http://gw/v1/extensions/developer/call").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"app_id": "demo"}})
    )
    c = ImperalClient(CFG)
    assert await c.whoami() == "imp_u_1"
    out = await c.deploy_ir("demo", {"ir_version": "1", "app": {"id": "demo"}})
    body = json.loads(deploy.calls.last.request.read().decode())
    assert body["user_id"] == "imp_u_1" and body["function"] == "deploy_ir"
    assert out["status"] == "success"


@respx.mock
@pytest.mark.asyncio
async def test_run_tool_targets_app_call():
    respx.get("http://gw/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"imperal_id": "imp_u_1"})
    )
    route = respx.post("http://gw/v1/extensions/notes/call").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": []})
    )
    c = ImperalClient(CFG)
    await c.run_tool("notes", "list_notes", {})
    assert route.called
    body = json.loads(route.calls.last.request.read().decode())
    assert body["user_id"] == "imp_u_1"


def _mock_registered_ok():
    """Mock /auth/me + /register so ensure_registered() is a no-op (already a dev)."""
    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_u_1"}))
    respx.post("http://gw/v1/developer/register").mock(
        return_value=httpx.Response(400, json={"detail": "Already registered as developer"}))


# ── ONB-2: ensure_app register-then-get-or-create ──────────────────────── #

@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_skips_create_when_app_exists():
    _mock_registered_ok()
    get_route = respx.get("http://gw/v1/developer/apps/demo").mock(
        return_value=httpx.Response(200, json={"app_id": "demo"}))
    # deliberately do NOT mock POST /apps — a create attempt would raise (route not found)
    c = ImperalClient(CFG)
    await c.ensure_app("demo", "Demo")
    assert get_route.called
    assert not any(
        call.request.method == "POST" and call.request.url.path == "/v1/developer/apps"
        for call in respx.calls
    )


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_creates_when_missing():
    _mock_registered_ok()
    respx.get("http://gw/v1/developer/apps/demo").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    create_route = respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(200, json={"app_id": "demo"}))
    c = ImperalClient(CFG)
    await c.ensure_app("demo", "Demo")
    assert create_route.called
    body = json.loads(create_route.calls.last.request.read().decode())
    assert body["app_id"] == "demo" and body["git_url"] == "https://imperal.io/ir-apps/demo"


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_swallows_409():
    _mock_registered_ok()
    respx.get("http://gw/v1/developer/apps/demo").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://gw/v1/developer/apps").mock(return_value=httpx.Response(409, text="app already exists"))
    c = ImperalClient(CFG)
    await c.ensure_app("demo", "Demo App")  # must not raise


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_reraises_500():
    _mock_registered_ok()
    respx.get("http://gw/v1/developer/apps/demo").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://gw/v1/developer/apps").mock(return_value=httpx.Response(500, text="internal server error"))
    c = ImperalClient(CFG)
    with pytest.raises(ImperalError) as exc_info:
        await c.ensure_app("demo", "Demo App")
    assert exc_info.value.status_code == 500


# F3 — gateway returns HTTP 400 "already in use" for first-party extension apps
@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_swallows_400_already_in_use():
    """Real gateway: re-creating a first-party app returns 400 with 'already in use'."""
    _mock_registered_ok()
    respx.get("http://gw/v1/developer/apps/x").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(400, json={"detail": "App ID 'x' is already in use by a first-party extension"}))
    c = ImperalClient(CFG)
    await c.ensure_app("x", "X App")  # must NOT raise — treat as idempotent


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_reraises_400_other_reason():
    """A 400 for a different reason (e.g. invalid app_id format) must still raise."""
    _mock_registered_ok()
    respx.get(url__regex=r"http://gw/v1/developer/apps/.+").mock(
        return_value=httpx.Response(404, json={"detail": "not found"}))
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(400, json={"detail": "app_id contains invalid characters"}))
    c = ImperalClient(CFG)
    with pytest.raises(ImperalError) as exc_info:
        await c.ensure_app("bad id!", "Bad")
    assert exc_info.value.status_code == 400


# F1 — get_marketplace_app returns {} on 404 (no crash)
@respx.mock
@pytest.mark.asyncio
async def test_get_marketplace_app_returns_empty_on_404():
    respx.get("http://gw/v1/marketplace/apps/nonexistent").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    c = ImperalClient(CFG)
    result = await c.get_marketplace_app("nonexistent")
    assert result == {}


@respx.mock
@pytest.mark.asyncio
async def test_get_marketplace_app_returns_data_on_success():
    respx.get("http://gw/v1/marketplace/apps/notes").mock(
        return_value=httpx.Response(
            200,
            json={"app_id": "notes", "tools": [{"name": "list_notes", "action_type": "read"}]},
        )
    )
    c = ImperalClient(CFG)
    result = await c.get_marketplace_app("notes")
    assert result["app_id"] == "notes"
    assert result["tools"][0]["name"] == "list_notes"


@respx.mock
@pytest.mark.asyncio
async def test_client_uses_token_provider():
    calls = {"n": 0}

    async def provider():
        calls["n"] += 1
        return "tok-from-provider"

    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_x"}))
    c = ImperalClient(Config(api_url="http://gw", token=None), token_provider=provider)
    assert await c.whoami() == "imp_x"
    assert calls["n"] >= 1
    assert respx.calls.last.request.headers["authorization"] == "Bearer tok-from-provider"


# ── ONB-1: ensure_registered (auto free explorer) ──────────────────────── #

@respx.mock
@pytest.mark.asyncio
async def test_ensure_registered_registers_explorer_when_not_registered():
    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_u_AbC123"}))
    route = respx.post("http://gw/v1/developer/register").mock(
        return_value=httpx.Response(200, json={"tier": "explorer"}))
    c = ImperalClient(CFG)
    await c.ensure_registered()
    assert route.called
    body = json.loads(route.calls.last.request.read().decode())
    assert body["tier"] == "explorer"
    assert body["nickname"] == "imp_u_abc123"  # handle derived (lowercased) from imperal_id


@respx.mock
@pytest.mark.asyncio
async def test_ensure_registered_tolerates_already_registered():
    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_u_1"}))
    respx.post("http://gw/v1/developer/register").mock(
        return_value=httpx.Response(400, json={"detail": "Already registered as developer"}))
    c = ImperalClient(CFG)
    await c.ensure_registered()  # must NOT raise


@respx.mock
@pytest.mark.asyncio
async def test_ensure_registered_retries_handle_on_collision():
    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_u_dupe"}))
    route = respx.post("http://gw/v1/developer/register").mock(side_effect=[
        httpx.Response(400, json={"detail": "Nickname 'imp_u_dupe' is already taken"}),
        httpx.Response(200, json={"tier": "explorer"}),
    ])
    c = ImperalClient(CFG)
    await c.ensure_registered()  # must NOT raise
    assert route.call_count == 2
    body2 = json.loads(route.calls[1].request.read().decode())
    assert body2["nickname"] != "imp_u_dupe" and body2["tier"] == "explorer"
