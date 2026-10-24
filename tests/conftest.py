from __future__ import annotations

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
