import asyncio
import json
import pytest

from imperal_mcp.config import Config
from imperal_mcp.client import ImperalClient
from imperal_mcp.server import (
    build_server,
    _resolve_action_type,
    _tools_of,
    run_read_tool_logic,
    deploy_ir_logic,
)


class FakeClient(ImperalClient):
    def __init__(self):
        super().__init__(Config(api_url="http://gw", token="t"))
        self.ran = []

    async def get_app(self, app_id):
        return {"tools_json": [
            {"name": "list_notes", "action_type": "read"},
            {"name": "delete_note", "action_type": "destructive"},
        ]}

    async def get_marketplace_app(self, app_id):
        return {}

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


@pytest.mark.asyncio
async def test_run_read_tool_refuses_synthetic():
    c = FakeClient()
    out = await run_read_tool_logic(c, "app", "__panel__home", {})
    assert c.ran == []            # never executed
    assert out["refused"] is True


# F1 — _tools_of handles manifest_json as a JSON string
def test_tools_of_tools_json_list():
    app = {"tools_json": [{"name": "foo", "action_type": "read"}]}
    assert _tools_of(app) == [{"name": "foo", "action_type": "read"}]


def test_tools_of_manifest_json_dict():
    app = {"manifest_json": {"tools": [{"name": "bar", "action_type": "write"}]}}
    assert _tools_of(app) == [{"name": "bar", "action_type": "write"}]


def test_tools_of_manifest_json_string():
    tools = [{"name": "list_links", "action_type": "read"}]
    app = {"manifest_json": json.dumps({"tools": tools})}
    assert _tools_of(app) == tools


def test_tools_of_manifest_json_none():
    assert _tools_of({"manifest_json": None}) == []


def test_tools_of_manifest_json_invalid_string():
    # Malformed JSON → returns []
    assert _tools_of({"manifest_json": "not-json"}) == []


# F1 — _resolve_action_type with manifest_json as JSON string
@pytest.mark.asyncio
async def test_resolve_action_type_manifest_json_string():
    """get_app returns manifest_json as a JSON string → must parse and resolve action_type."""
    class StringManifestClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))

        async def get_app(self, app_id):
            tools = [{"name": "list_links", "action_type": "read"}]
            return {"manifest_json": json.dumps({"tools": tools})}

        async def get_marketplace_app(self, app_id):
            return {}

    c = StringManifestClient()
    result = await _resolve_action_type(c, "link-saver", "list_links")
    assert result == "read"


# F1 — _resolve_action_type falls back to marketplace when get_app has no tools
@pytest.mark.asyncio
async def test_resolve_action_type_marketplace_fallback():
    """When get_app returns no tools, marketplace catalog is consulted."""
    class MarketplaceClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))

        async def get_app(self, app_id):
            return {"manifest_json": None}  # no tools from dev record

        async def get_marketplace_app(self, app_id):
            return {"tools": [{"name": "read_notes", "action_type": "read"}]}

    c = MarketplaceClient()
    result = await _resolve_action_type(c, "notes", "read_notes")
    assert result == "read"


@pytest.mark.asyncio
async def test_resolve_action_type_returns_none_when_neither_has_tool():
    """Unknown function → None regardless of marketplace response."""
    class EmptyClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))

        async def get_app(self, app_id):
            return {}

        async def get_marketplace_app(self, app_id):
            return {}

    c = EmptyClient()
    result = await _resolve_action_type(c, "app", "nonexistent")
    assert result is None


# AZV-3c — deploy_ir_logic retries once ONLY on a transient failure
@pytest.mark.asyncio
async def test_deploy_ir_logic_retries_once_on_transient(monkeypatch):
    """First deploy returns a transient error; second succeeds. Must retry exactly once."""
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class RetryClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))
            self.deploy_calls = 0

        async def whoami(self):
            return "imp_u_test"

        async def deploy_ir(self, app_id, ir_dict):
            self.deploy_calls += 1
            if self.deploy_calls == 1:
                return {"status": "error", "error": "deploy timed out, please retry"}
            return {"status": "success", "data": {"app_id": app_id}}

    c = RetryClient()
    result = await deploy_ir_logic(c, {"ir_version": "1.0", "app": {"id": "demo"}}, "demo")
    assert result["status"] == "success"
    assert c.deploy_calls == 2 and sleep_calls == [1.0]


# AZV-3c — a DETERMINISTIC failure is NOT retried (a retry would just re-fail
# and add a fleet-wide catalog reload)
@pytest.mark.asyncio
async def test_deploy_ir_logic_no_retry_on_deterministic_error(monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class DetClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))
            self.deploy_calls = 0

        async def whoami(self):
            return "imp_u_test"

        async def deploy_ir(self, app_id, ir_dict):
            self.deploy_calls += 1
            return {"status": "error", "error": "validation failed: tool 'x' has no description"}

    c = DetClient()
    result = await deploy_ir_logic(c, {"ir_version": "1.0", "app": {"id": "demo"}}, "demo")
    assert result["status"] == "error"
    assert c.deploy_calls == 1 and sleep_calls == []  # NOT retried


@pytest.mark.asyncio
async def test_deploy_ir_logic_no_retry_on_immediate_success(monkeypatch):
    """First deploy succeeds → no retry, no sleep."""
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class SuccessClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))
            self.deploy_calls = 0

        async def whoami(self):
            return "imp_u_test"

        async def deploy_ir(self, app_id, ir_dict):
            self.deploy_calls += 1
            return {"status": "success", "data": {"app_id": app_id}}

    c = SuccessClient()
    ir = {"ir_version": "1.0", "app": {"id": "demo"}}
    result = await deploy_ir_logic(c, ir, "demo")

    assert result["status"] == "success"
    assert c.deploy_calls == 1  # called once only
    assert sleep_calls == []    # no sleep


# DEP-3 — a non-success deploy result is surfaced truthfully with a clear error
@pytest.mark.asyncio
async def test_deploy_ir_logic_failure_always_has_error_string():
    class FailClient(ImperalClient):
        def __init__(self):
            super().__init__(Config(api_url="http://gw", token="t"))

        async def whoami(self):
            return "imp_u_test"

        async def deploy_ir(self, app_id, ir_dict):
            # gateway sometimes returns a bare non-success with only `message`
            return {"status": "error", "message": "ownership check failed"}

    out = await deploy_ir_logic(FailClient(), {"ir_version": "1.0", "app": {"id": "demo"}}, "demo")
    assert out["status"] == "error"
    assert out.get("error")  # a clear, non-empty error string is present
    assert "ownership" in out["error"].lower()
