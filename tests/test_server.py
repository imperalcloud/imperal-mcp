import pytest

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient
from imperal_mcp.server import build_server, _resolve_action_type, run_read_tool_logic


class FakeClient(ImperalClient):
    def __init__(self):
        super().__init__(Config(api_url="http://gw", token="t"))
        self.ran = []

    async def get_app(self, app_id):
        return {"tools_json": [
            {"name": "list_notes", "action_type": "read"},
            {"name": "delete_note", "action_type": "destructive"},
        ]}

    async def run_tool(self, app_id, function, params):
        self.ran.append((app_id, function))
        return {"status": "success", "data": {"email": "a@b.com"}}


def test_build_server_registers_tools():
    srv = build_server(FakeClient())
    # FastMCP exposes the server object; smoke check it constructed.
    assert srv is not None


@pytest.mark.asyncio
async def test_resolve_action_type():
    c = FakeClient()
    assert await _resolve_action_type(c, "app", "list_notes") == "read"
    assert await _resolve_action_type(c, "app", "delete_note") == "destructive"
    assert await _resolve_action_type(c, "app", "unknown") is None


@pytest.mark.asyncio
async def test_run_read_tool_allows_read_and_scrubs():
    c = FakeClient()
    out = await run_read_tool_logic(c, "app", "list_notes", {})
    assert c.ran == [("app", "list_notes")]
    assert "a@b.com" not in str(out)  # defensive scrub applied


@pytest.mark.asyncio
async def test_run_read_tool_refuses_write():
    c = FakeClient()
    out = await run_read_tool_logic(c, "app", "delete_note", {})
    assert c.ran == []  # never executed
    assert out["refused"] is True
