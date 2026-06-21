import json

import httpx
import pytest
import respx

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient, ImperalAuthError, ImperalError
from imperal_mcp.auth import NotLoggedInError

CFG = Config(api_url="http://gw", token="jwt-abc")


@pytest.mark.asyncio
async def test_requires_token():
    # With no token and no stored credentials, the client raises an auth-related error.
    # Previously ImperalAuthError (sync path); now NotLoggedInError from auth.ensure_access_token.
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


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_swallows_409():
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(409, text="app already exists")
    )
    c = ImperalClient(CFG)
    # Must not raise
    await c.ensure_app("demo", "Demo App")


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_reraises_500():
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(500, text="internal server error")
    )
    c = ImperalClient(CFG)
    with pytest.raises(ImperalError) as exc_info:
        await c.ensure_app("demo", "Demo App")
    assert exc_info.value.status_code == 500


# F3 — gateway returns HTTP 400 "already in use" for first-party extension apps
@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_swallows_400_already_in_use():
    """Real gateway: re-creating a first-party app returns 400 with 'already in use'."""
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(
            400,
            json={"detail": "App ID 'x' is already in use by a first-party extension"},
        )
    )
    c = ImperalClient(CFG)
    # Must NOT raise — treat as idempotent
    await c.ensure_app("x", "X App")


@respx.mock
@pytest.mark.asyncio
async def test_ensure_app_reraises_400_other_reason():
    """A 400 for a different reason (e.g. invalid app_id format) must still raise."""
    respx.post("http://gw/v1/developer/apps").mock(
        return_value=httpx.Response(
            400, json={"detail": "app_id contains invalid characters"}
        )
    )
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
async def test_client_uses_token_provider(monkeypatch):
    calls = {"n": 0}

    async def provider():
        calls["n"] += 1
        return "tok-from-provider"

    respx.get("http://gw/v1/auth/me").mock(return_value=httpx.Response(200, json={"imperal_id": "imp_x"}))
    c = ImperalClient(Config(api_url="http://gw", token=None), token_provider=provider)
    assert await c.whoami() == "imp_x"
    assert calls["n"] >= 1
    assert respx.calls.last.request.headers["authorization"] == "Bearer tok-from-provider"
