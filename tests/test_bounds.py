"""Memory plan Task 8: bounded answers by default; extra roots by name."""
import json

import pytest

from imperal_mcp.exoskeleton import ANSWER_CHARS, ExoskeletonRuntime, OutsideWorkspaceError, bounded


def test_a_big_answer_is_bounded_and_counted():
    big = {"status": "ok", "dependent_files": [f"pkg/m{i}.py" for i in range(3000)],
           "items": [{"id": f"pkg/m{i}.py", "callers": [{"user": "f", "line": i}] * 5} for i in range(800)]}
    out = bounded(big)
    assert len(json.dumps(out)) <= ANSWER_CHARS
    assert out["items_total"] == 800 and 0 < out["items_shown"] < 800 and out["dependent_files_total"] == 3000
    assert "full=true" in out["truncated"]
    small = {"status": "ok", "items": [1, 2]}
    assert bounded(small) == small


def test_an_extra_root_is_allowed_and_nothing_else(tmp_path, monkeypatch):
    ws, extra, other = tmp_path / "ws", tmp_path / "mirror", tmp_path / "other"
    for d in (ws, extra, other):
        d.mkdir()
    monkeypatch.setenv("IMPERAL_MCP_EXTRA_ROOTS", str(extra))
    exo = ExoskeletonRuntime(workspace=str(ws))
    assert exo.resolve_workspace(str(extra)) == str(extra.resolve())
    assert exo.resolve_workspace(str(extra / "sub")) == str((extra / "sub").resolve())
    with pytest.raises(OutsideWorkspaceError):
        exo.resolve_workspace(str(other))
