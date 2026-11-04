from __future__ import annotations
import os
import pytest

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_MCP_ROOT = _TESTS_DIR.parent
_REPO_ROOT = _MCP_ROOT.parent

py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
for venv_sp in (
    _MCP_ROOT / ".venv" / "lib" / py_ver / "site-packages",
    _REPO_ROOT / "webbee" / ".venv" / "lib" / py_ver / "site-packages",
):
    s = str(venv_sp)
    if venv_sp.is_dir() and s not in sys.path:
        sys.path.insert(0, s)

for src_dir in (
    _REPO_ROOT / "imperal-sdk" / "src",
    _REPO_ROOT / "webbee" / "src",
    _MCP_ROOT / "src",
):
    s = str(src_dir)
    if src_dir.is_dir():
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)


@pytest.fixture(autouse=True)
def _private_spool(tmp_path, monkeypatch):
    """Every test gets its own hook spool -- never the real one in the home folder."""
    if not os.environ.get("IMPERAL_MCP_SPOOL", "").startswith(str(tmp_path)):
        monkeypatch.setenv("IMPERAL_MCP_SPOOL", str(tmp_path / "spool-auto"))


@pytest.fixture(autouse=True)
def _no_real_server_head(monkeypatch):
    """A test never opens an SSH connection: the server's HEAD is "cannot tell" unless a test says otherwise."""
    try:
        import webbee.tools as wt
    except Exception:
        return

    async def unknown(host, root):
        return {"commit": "", "branch": "", "root": root, "why": ""}
    if hasattr(wt, "remote_head"):
        monkeypatch.setattr(wt, "remote_head", unknown)


@pytest.fixture(autouse=True)
def _private_index_cache(tmp_path_factory, monkeypatch):
    """The local index caches every unit (a folder without git too, since 0.9.0) under ``~/.cache/webbee`` -- a
    test's caches go to its own home (outside the test's workspace), never the real one."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home-auto")))


@pytest.fixture(autouse=True)
def _never_a_real_server(monkeypatch):
    """A test never reaches a real server over ssh (2026-11-04: a host test ran git grep on whm-jump)."""
    try:
        import webbee.tools as wt
    except Exception:
        return

    async def refuse(host, argv, timeout=0, cap=0):
        return -1, b"", f"tests never reach a server ({host})"
    monkeypatch.setattr(wt, "remote_run", refuse, raising=False)
