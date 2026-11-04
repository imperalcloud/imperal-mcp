"""Final review 2026-11-04 of the universal index: outline / read_symbol never open a never-read file, big files are
read by lines, units see new and deleted files, document search answers locally when the vault answers code."""
import os
import time
from pathlib import Path

import pytest

from imperal_mcp.exoskeleton import ExoskeletonRuntime


@pytest.mark.parametrize("rel", [".env", "config/.env.production", "id_rsa", "deploy/credentials.json",
                                 ".aws/credentials", "keys/server.pem"])
def test_outline_and_read_symbol_never_open_a_secret(tmp_path: Path, rel):
    ws = tmp_path / "work"
    (ws / rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / rel).write_text("API_KEY=sk-live-123\n")
    exo = ExoskeletonRuntime(workspace=str(ws))
    for out in (exo.outline(rel), exo.read_symbol(rel, "L1-1")):
        assert out["status"] == "error" and "never read" in out["error"]
        assert "sk-live" not in str(out)


def test_a_workspace_inside_a_secret_store_is_never_read(tmp_path: Path):
    """A unit or workspace rooted at the store itself names its files without the store's name."""
    ws = tmp_path / "secrets"
    ws.mkdir()
    (ws / "notes.md").write_text("# the vault password is hunter2\n")
    exo = ExoskeletonRuntime(workspace=str(ws))
    out = exo.read_symbol("notes.md", "L1-1")
    assert out["status"] == "error" and "hunter2" not in str(out)


def test_a_big_file_is_read_by_lines_never_whole(tmp_path: Path):
    ws = tmp_path / "work"
    ws.mkdir()
    (ws / "app.log").write_text("".join(f"line {i}\n" for i in range(300_000)))      # ~3 MB
    exo = ExoskeletonRuntime(workspace=str(ws))
    out = exo.read_symbol("app.log", "L1000-1002")
    assert out["status"] == "ok" and "line 999" in out["rendered"] and "line 1002" not in out["rendered"]
    assert "over 1 MB" in exo.outline("app.log")["error"]


def _wait(exo, ws, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        units = exo.units_progress(str(ws))
        if units and all(u["done"] for u in units):
            return
        time.sleep(0.05)
    raise AssertionError("units never finished")


def test_units_see_new_and_deleted_files(tmp_path: Path, monkeypatch):
    from imperal_mcp import exoskeleton
    monkeypatch.setattr(exoskeleton, "_UNIT_REFRESH_S", 0.0)
    monkeypatch.setattr(exoskeleton, "_LOCAL_REFRESH_S", 0.0)
    home = tmp_path / "h"
    (home / "Documents").mkdir(parents=True)
    (home / "Documents" / "old.md").write_text("# Quarterly budget\n")
    exo = ExoskeletonRuntime(workspace=str(home))
    exo.search_code("warm up")
    _wait(exo, home)
    (home / "Documents" / "fresh.md").write_text("# Migration runbook\n")
    (home / "Documents" / "old.md").unlink()
    found = exo.search_code("Migration runbook")
    assert any(m["path"] == "Documents/fresh.md" for m in found["matches"])
    gone = exo.search_code("Quarterly budget")
    assert not any(m["path"] == "Documents/old.md" for m in gone["matches"])


def test_document_search_is_local_when_the_vault_answers_code(tmp_path: Path, monkeypatch):
    ws = tmp_path / "repo"
    ws.mkdir()
    os.system(f"git init -q {ws}")
    (ws / "plan.md").write_text("# Rollout plan\nship on monday\n")
    exo = ExoskeletonRuntime(workspace=str(ws))
    monkeypatch.setattr(exo, "_vault_search", lambda *a, **k: {"data": {"items": [{"path": "x.py"}]}})
    out = exo.search_code("Rollout plan", kind="document")
    assert any(m["path"] == "plan.md" for m in out["matches"])
