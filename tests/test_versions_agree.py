"""Every place that states the release version agrees with pyproject.toml.

server.json once stayed at 0.2.3 and the Claude Code plugin files at 0.2.1 while PyPI shipped
0.5.3: the MCP Registry refused the stale version on every release and kept listing 0.2.3.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    # read without tomllib: the package supports Python 3.10, which has none
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


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


def test_the_pins_carry_what_the_frame_needs():
    """Final review I6: SECRET_PATTERNS is in imperal-sdk 6.2.0+, the snapshot's changed paths in webbee 0.5.9+."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert "imperal-sdk>=6.2.0" in text and "webbee>=0.5.11" in text
