"""A new agent's first minutes (2026-11-13): a fresh `uvx imperal-mcp` from the MCP Registry, no account yet.

Live before this release: the tool list opened with eight IR-app tools, orient answered a bare "No module named
'webbee'" without the [code] extra, the memory tools said "run `imperal-mcp login`" (a browser step no agent can take)
and the protocol put 3 706 characters into every session."""
import asyncio

import pytest

from imperal_mcp import auth
from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS, MISSING_CODE_DEPENDENCY_MESSAGE
from imperal_mcp.server import build_server

APP_TOOLS = {"validate_ir", "smoke_ir", "deploy_ir", "list_apps", "get_app", "run_read_tool", "run_write_tool",
             "upload_file"}


def _text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    if isinstance(content, dict):
        return str(content)
    return " ".join(getattr(c, "text", "") for c in content)


@pytest.mark.asyncio
async def test_the_list_opens_with_the_code_and_memory_tools(tmp_path):
    names = [t.name for t in await build_server(None, workspace=str(tmp_path)).list_tools()]
    assert names[0] not in APP_TOOLS and set(names[-len(APP_TOOLS):]) == APP_TOOLS


def test_the_protocol_is_short_and_plain():
    assert len(EXOSKELETON_INSTRUCTIONS) <= 2400          # 3 706 characters before, in every session
    assert "—" not in EXOSKELETON_INSTRUCTIONS and "--" not in EXOSKELETON_INSTRUCTIONS
    assert "`login`" in EXOSKELETON_INSTRUCTIONS


@pytest.mark.asyncio
async def test_a_code_tool_without_the_code_extra_says_what_to_install(tmp_path, monkeypatch):
    srv = build_server(None, workspace=str(tmp_path))

    def no_webbee(**_kw):
        raise ModuleNotFoundError("No module named 'webbee'", name="webbee")
    monkeypatch.setattr(srv._exoskeleton, "orient", no_webbee)
    text = _text(await srv.call_tool("orient", {"query": "x"}))
    assert MISSING_CODE_DEPENDENCY_MESSAGE in text and "--with 'imperal-mcp[code]'" in text


@pytest.mark.asyncio
async def test_any_other_import_error_stays_an_error(tmp_path, monkeypatch):
    srv = build_server(None, workspace=str(tmp_path))

    def broken(**_kw):
        raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
    monkeypatch.setattr(srv._exoskeleton, "orient", broken)
    with pytest.raises(Exception, match="yaml"):
        await srv.call_tool("orient", {"query": "x"})


class _Grant:
    """A device grant the test finishes by hand."""

    def __init__(self):
        self.finish: asyncio.Future | None = None
        self.calls = 0

    async def __call__(self, cfg, *, on_prompt=None, open_browser=True):
        self.calls += 1
        assert open_browser is False                    # stdout is the MCP stream: no browser child on it
        self.finish = asyncio.get_running_loop().create_future()
        on_prompt("ABCD-1234", "https://panel.imperal.io/device", "https://panel.imperal.io/device?code=ABCD-1234")
        return await self.finish


@pytest.mark.asyncio
async def test_an_agent_signs_in_by_showing_a_link_and_a_code(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    grant = _Grant()
    login = auth.AgentLogin(cfg_factory=lambda: None, login=grant)

    first = await login()
    assert first["status"] == "waiting_for_user" and first["user_code"] == "ABCD-1234"
    assert first["verification_uri_complete"].endswith("ABCD-1234")
    assert (await login())["status"] == "waiting_for_user" and grant.calls == 1   # one grant, not a second

    grant.finish.set_result("dev@example.com")
    await asyncio.sleep(0)
    done = await login()
    assert done == {"ok": True, "status": "signed_in", "email": "dev@example.com"}


@pytest.mark.asyncio
async def test_a_declined_sign_in_says_so_and_the_next_call_starts_again(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    grant = _Grant()
    login = auth.AgentLogin(cfg_factory=lambda: None, login=grant)
    await login()
    grant.finish.set_exception(RuntimeError("login was declined in the browser."))
    await asyncio.sleep(0)
    failed = await login()
    assert failed["ok"] is False and "declined" in failed["error"]
    assert (await login())["status"] == "waiting_for_user" and grant.calls == 2


@pytest.mark.asyncio
async def test_signed_in_already_starts_no_grant_unless_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth.save_creds({"refresh_token": "r", "access_token": "a", "access_expires_at": 0})
    grant = _Grant()
    login = auth.AgentLogin(cfg_factory=lambda: None, login=grant)
    assert (await login())["status"] == "signed_in" and grant.calls == 0
    assert (await login(again=True))["status"] == "waiting_for_user" and grant.calls == 1


@pytest.mark.asyncio
async def test_the_login_tool_is_served(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    srv = build_server(None, workspace=str(tmp_path))
    grant = _Grant()
    srv._agent_login._login = grant
    srv._agent_login._cfg_factory = lambda: None
    assert "ABCD-1234" in _text(await srv.call_tool("login", {}))


@pytest.mark.asyncio
async def test_not_signed_in_points_at_the_login_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(auth.NotLoggedInError, match="`login` tool"):
        await auth.ensure_access_token(auth_cfg())


def auth_cfg():
    from imperal_mcp.config import Config
    return Config(api_url="http://gw", token=None)
