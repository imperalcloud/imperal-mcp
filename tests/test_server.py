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


# ── Task 4: run_write_tool (write direct + destructive elicitation + autopilot) ──
from imperal_mcp.server import run_write_tool_logic, Autopilot


class WriteFakeClient(ImperalClient):
    def __init__(self, action_types):
        super().__init__(Config(api_url="http://gw", token="t"))
        self._at = action_types            # {function: action_type}
        self.operate_result = None         # returned on the non-bypass call
        self.operate_result_bypass = None  # returned on the bypass call, if set
        self.calls = []                    # (function, confirmation_bypassed)
        self.last_bypass = None

    async def get_app(self, app_id):
        return {"tools_json": [{"name": n, "action_type": at} for n, at in self._at.items()]}

    async def get_marketplace_app(self, app_id):
        return {}

    async def operate(self, app_id, function, params, confirmation_bypassed=False):
        self.calls.append((function, confirmation_bypassed))
        self.last_bypass = confirmation_bypassed
        if confirmation_bypassed and self.operate_result_bypass is not None:
            return self.operate_result_bypass
        return self.operate_result


class _Data:
    def __init__(self, decision): self.decision = decision

class _Accepted:          # mirrors mcp AcceptedElicitation
    action = "accept"
    def __init__(self, decision): self.data = _Data(decision)

class _Declined:          # mirrors mcp DeclinedElicitation
    action = "decline"
    data = None

class _Ctx:
    def __init__(self, result): self._r = result; self.elicits = 0
    async def elicit(self, message, schema=None):
        self.elicits += 1
        return self._r


@pytest.mark.asyncio
async def test_write_executes_direct_no_prompt():
    c = WriteFakeClient({"create_note": "write"})
    c.operate_result = {"kind": "tool_result", "content": {"id": 1}}
    ctx = _Ctx(_Accepted("reject"))  # would reject IF asked — must NOT be asked
    out = await run_write_tool_logic(c, ctx, "notes", "create_note", {"t": 1}, Autopilot())
    assert out["status"] == "ok"
    assert c.last_bypass is False
    assert ctx.elicits == 0

@pytest.mark.asyncio
async def test_read_tier_refused_no_dispatch():
    c = WriteFakeClient({"list_notes": "read"})
    out = await run_write_tool_logic(c, _Ctx(_Accepted("reject")), "notes", "list_notes", {}, Autopilot())
    assert out["status"] == "refused" and out["reason"] == "use run_read_tool"
    assert c.calls == []

@pytest.mark.asyncio
async def test_blocked_tier_refused_no_dispatch():
    c = WriteFakeClient({"tool_mail_chat": "write"})  # legacy → classify_tier -> blocked
    out = await run_write_tool_logic(c, _Ctx(_Accepted("reject")), "mail", "tool_mail_chat", {}, Autopilot())
    assert out["status"] == "refused"
    assert c.calls == []

@pytest.mark.asyncio
async def test_destructive_reject_never_dispatches():
    # ELICIT-FIRST: on reject, operate must NEVER be called (nothing executes).
    c = WriteFakeClient({"delete_notes": "destructive"})
    c.operate_result = {"kind": "tool_result", "content": {"deleted": 999}}  # must never surface
    ctx = _Ctx(_Accepted("reject"))
    out = await run_write_tool_logic(c, ctx, "notes", "delete_notes", {}, Autopilot())
    assert out["status"] == "refused" and out["reason"] == "human_rejected"
    assert ctx.elicits == 1
    assert c.calls == []  # operate NEVER called — no execution before consent

@pytest.mark.asyncio
async def test_destructive_declined_treated_as_reject_never_dispatches():
    c = WriteFakeClient({"delete_notes": "destructive"})
    c.operate_result = {"kind": "tool_result", "content": {"deleted": 999}}
    out = await run_write_tool_logic(c, _Ctx(_Declined()), "notes", "delete_notes", {}, Autopilot())
    assert out["status"] == "refused" and out["reason"] == "human_rejected"
    assert c.calls == []  # decline fails safe: nothing executes

@pytest.mark.asyncio
async def test_destructive_approve_once_runs_single_bypass_no_autopilot():
    c = WriteFakeClient({"delete_notes": "destructive"})
    c.operate_result = {"kind": "tool_result", "content": {"deleted": 3}}
    ap = Autopilot(); ctx = _Ctx(_Accepted("approve_once"))
    out = await run_write_tool_logic(c, ctx, "notes", "delete_notes", {}, ap)
    assert out["status"] == "ok" and out["consent"] == "elicited"
    assert ctx.elicits == 1
    assert c.calls == [("delete_notes", True)]  # ONE call, bypass=True, only after approval
    assert ap.enabled is False  # approve-once must NOT flip autopilot

@pytest.mark.asyncio
async def test_destructive_autopilot_choice_enables_and_runs():
    c = WriteFakeClient({"delete_notes": "destructive"})
    c.operate_result = {"kind": "tool_result", "content": {"deleted": 1}}
    ap = Autopilot(); ctx = _Ctx(_Accepted("autopilot"))
    out = await run_write_tool_logic(c, ctx, "notes", "delete_notes", {}, ap)
    assert out["status"] == "ok" and out["consent"] == "autopilot"
    assert ap.enabled is True  # the human's autopilot choice flipped it
    assert c.calls == [("delete_notes", True)]

@pytest.mark.asyncio
async def test_destructive_autopilot_on_skips_prompt():
    c = WriteFakeClient({"delete_notes": "destructive"})
    c.operate_result = {"kind": "tool_result", "content": {"deleted": 2}}
    ap = Autopilot(); ap.enabled = True
    ctx = _Ctx(_Accepted("reject"))  # would reject IF asked — must NOT be asked
    out = await run_write_tool_logic(c, ctx, "notes", "delete_notes", {}, ap)
    assert out["status"] == "ok" and out["consent"] == "autopilot"
    assert ctx.elicits == 0
    assert c.calls == [("delete_notes", True)]  # single bypass call, no prompt

@pytest.mark.asyncio
async def test_write_error_content_maps_to_error_status():
    c = WriteFakeClient({"create_note": "write"})
    c.operate_result = {"kind": "tool_result", "content": {"error": "boom"}}
    out = await run_write_tool_logic(c, _Ctx(_Accepted("reject")), "notes", "create_note", {}, Autopilot())
    assert out["status"] == "error"
