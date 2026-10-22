"""Every place that states the release version agrees with pyproject.toml.

server.json once stayed at 0.2.3 and the Claude Code plugin files at 0.2.1 while PyPI shipped
0.5.3: the MCP Registry refused the stale version on every release and kept listing 0.2.3.
"""
import json
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_server_json_matches_pyproject():
    v = _pyproject_version()
    s = json.loads((ROOT / "server.json").read_text())
    assert s["version"] == v
    assert [p["version"] for p in s["packages"] if p["identifier"] == "imperal-mcp"] == [v]
    assert s["repository"]["url"] == "https://github.com/imperalcloud/imperal-mcp"


def test_claude_plugin_files_match_pyproject():
    v = _pyproject_version()
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert [p["version"] for p in market["plugins"] if p["name"] == "imperal-mcp"] == [v]
    assert plugin["version"] == v
