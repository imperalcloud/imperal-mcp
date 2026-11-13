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
    """Final review I6: SECRET_PATTERNS is in imperal-sdk 6.2.0+, the snapshot's changed paths in webbee 0.5.9+;
    2026-11-04: the string-aware tsconfig reader and the parallel SFTP sync are in imperal-sdk 6.3.8+; the universal
    index (any folder, every file kind) is in imperal-sdk 6.4.1+ with its readers and webbee 0.7.0+; 2026-11-06: one
    link resolver for the vault and the clients, a folder of repositories resolved per repository in 6.5.1+; contract_slice
    through callers (code_links.contracts_reached) in 6.5.3+."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert "imperal-sdk>=6.5.3" in text and "webbee>=0.7.0" in text and "imperal-sdk[universal-index]>=6.5.3" in text


def _pyproject_description() -> str:
    return re.search(r'^description = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def test_every_listing_says_what_pypi_says():
    """2026-11-13: the MCP Registry and the Claude Code plugin files still said "build and deploy Imperal IR apps"
    (the 0.2 pitch) while PyPI already said what the package is -- the version moved on every release, the words never.
    The registry takes at most 100 characters: its line is the promise inside the PyPI description, word for word."""
    d = _pyproject_description()
    s = json.loads((ROOT / "server.json").read_text())
    assert len(s["description"]) <= 100 and s["description"].lower() in d.lower()
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["description"] == d
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert [p["description"].startswith(d) for p in market["plugins"] if p["name"] == "imperal-mcp"] == [True]


def test_the_registry_install_brings_the_code_tools():
    """2026-11-13: `uvx imperal-mcp`, the registry's install, listed every code tool and each one failed without the
    [code] extra ("No module named 'webbee'"). `uvx --with imperal-mcp[code] imperal-mcp==<v>` installs it; the extra
    is not a plain dependency because webbee's own environment carries imperal-mcp without it."""
    s = json.loads((ROOT / "server.json").read_text())
    (pkg,) = [p for p in s["packages"] if p["identifier"] == "imperal-mcp"]
    assert pkg["runtimeHint"] == "uvx"
    assert {"type": "named", "name": "--with", "value": "imperal-mcp[code]"}.items() <= pkg["runtimeArguments"][0].items()
