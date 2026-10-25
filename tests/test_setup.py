"""Memory plan Task 6: `imperal-mcp setup` gives every shell the server, the hooks and the protocol."""
import json

import pytest

from imperal_mcp import setup as S
from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_exe", lambda: ("/opt/imperal-mcp", []))
    monkeypatch.setattr(S.shutil, "which", lambda name: None)
    return tmp_path


def _hooks_commands(obj) -> list:
    return [h["command"] for v in obj.values() if isinstance(v, list) for g in v
            for h in (g.get("hooks") if isinstance(g, dict) and "hooks" in g else [g]) if isinstance(h, dict)]


def test_setup_writes_server_hooks_and_protocol_for_each_shell(home):
    res = S.setup(["claude", "codex", "antigravity", "gemini"], home=str(home))
    assert set(res) == {"claude", "codex", "antigravity", "gemini"}
    # Claude Code
    assert json.loads((home / ".claude.json").read_text())["mcpServers"]["imperal"]["command"] == "/opt/imperal-mcp"
    ch = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
    assert set(ch) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}
    assert "/opt/imperal-mcp hook prompt" in _hooks_commands(ch)[1] or any("hook prompt" in c for c in _hooks_commands(ch))
    assert EXOSKELETON_INSTRUCTIONS.strip()[:60] in (home / ".claude" / "CLAUDE.md").read_text()
    # Codex
    toml = (home / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.imperal]" in toml and 'command = "/opt/imperal-mcp"' in toml
    xh = json.loads((home / ".codex" / "hooks.json").read_text())["hooks"]
    assert set(xh) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}
    assert EXOSKELETON_INSTRUCTIONS.strip()[:60] in (home / ".codex" / "AGENTS.md").read_text()
    assert "/hooks" in res["codex"]["note"]                       # Codex runs a new hook only once it is trusted
    # Antigravity CLI
    assert "imperal" in json.loads((home / ".gemini" / "config" / "mcp_config.json").read_text())["mcpServers"]
    ah = json.loads((home / ".gemini" / "config" / "hooks.json").read_text())["imperal-mcp"]
    assert set(ah) == {"SessionStart", "PostToolUse", "Stop"}
    # Gemini CLI
    gs = json.loads((home / ".gemini" / "settings.json").read_text())
    assert "imperal" in gs["mcpServers"] and set(gs["hooks"]) == {"SessionStart", "BeforeAgent", "AfterTool", "AfterAgent"}
    assert (home / ".gemini" / "GEMINI.md").read_text().count("IMPERAL-MCP:START") == 1    # one block for both


def test_setup_twice_changes_nothing(home):
    S.setup(["claude", "codex", "antigravity", "gemini"], home=str(home))
    before = {p: p.read_text() for p in home.rglob("*") if p.is_file()}
    S.setup(["claude", "codex", "antigravity", "gemini"], home=str(home))
    assert {p: p.read_text() for p in home.rglob("*") if p.is_file()} == before


def test_remove_takes_only_its_own(home):
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "say done"}]}]}, "theme": "dark"}))
    (home / ".claude" / "CLAUDE.md").write_text("# mine\nkeep this\n")
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "numStartups": 5}))
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('model = "gpt-5"\n')
    S.setup(["claude", "codex"], home=str(home))
    S.setup(["claude", "codex"], home=str(home), remove=True)
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark" and _hooks_commands(settings["hooks"]) == ["say done"]
    assert (home / ".claude" / "CLAUDE.md").read_text().strip() == "# mine\nkeep this"
    assert json.loads((home / ".claude.json").read_text()) == {"mcpServers": {"other": {"command": "x"}}, "numStartups": 5}
    assert (home / ".codex" / "config.toml").read_text().strip() == 'model = "gpt-5"'


def test_a_broken_config_is_never_overwritten(home):
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{not json")
    res = S.setup(["claude"], home=str(home))
    assert "error" in res["claude"] and (home / ".claude" / "settings.json").read_text() == "{not json"


def test_a_server_the_user_named_imperal_is_left_alone(home):
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('[mcp_servers.imperal]\ncommand = "/my/own"\n')
    S.setup(["codex"], home=str(home))
    toml = (home / ".codex" / "config.toml").read_text()
    assert toml.count("[mcp_servers.imperal]") == 1 and "/my/own" in toml


def test_the_installed_shells_are_found(home, monkeypatch):
    (home / ".codex").mkdir()
    monkeypatch.setattr(S.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert S.installed_shells(str(home)) == ["claude", "codex"]


# ── security review (bfeb02c) ──
def test_a_rewritten_config_keeps_its_mode_and_a_new_one_is_private(home):
    import stat
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".claude" / "settings.json").chmod(0o640)
    S.setup(["claude"], home=str(home))
    assert stat.S_IMODE((home / ".claude" / "settings.json").stat().st_mode) == 0o640
    assert stat.S_IMODE((home / ".claude.json").stat().st_mode) == 0o600


def test_a_module_launch_never_reads_the_current_folder(monkeypatch):
    import sys
    from imperal_mcp import cli
    monkeypatch.setattr(cli, "_resolve_cli_executable", lambda: (sys.executable, ["-m", "imperal_mcp.cli"]))
    exe, args = S._exe()
    assert args[0] in ("-P", "-I") and args[1:] == ["-m", "imperal_mcp.cli"]


def test_a_launched_runtime_writes_the_launcher_not_its_own_version(tmp_path, monkeypatch):
    """e2e py3.9: setup wrote .../runtime/py3.12-0.6.6/bin/imperal-mcp -- an upgrade would leave the hooks behind."""
    launcher = tmp_path / "imperal-mcp"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    monkeypatch.setenv("IMPERAL_MCP_LAUNCHER", str(launcher))
    assert S._exe() == (str(launcher), [])
