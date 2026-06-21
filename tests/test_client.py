import json

import httpx
import pytest
import respx

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient, ImperalAuthError

CFG = Config(api_url="http://gw", token="jwt-abc")


@pytest.mark.asyncio
async def test_requires_token():
    c = ImperalClient(Config(api_url="http://gw", token=None))
    with pytest.raises(ImperalAuthError):
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
