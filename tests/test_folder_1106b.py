"""Report 06.11 #2 on imperal-mcp from a folder root: cross-repository users, semantic null, one repository's
profile, grep refused, contracts four times."""
from __future__ import annotations

from pathlib import Path

from imperal_mcp.exoskeleton import ExoskeletonRuntime, _merge_folder_answers, _one_per_contract


def test_a_user_in_another_repository_is_named_from_the_folder():
    sdk = {"ok": True, "repo_key": "K_SDK", "summary": "1 file(s) use IRNode by resolved links",
           "resolved": ["src/wpanel_sdk/ui/__init__.py::IRNode"],
           "data": {"items": [
               {"id": "src/wpanel_sdk/x.py", "title": "src/wpanel_sdk/x.py", "kind": "file", "depth": 1,
                "targets": ["src/wpanel_sdk/ui/__init__.py::IRNode"]},
               {"id": "K_TIX:wpanel_tickets/screens.py", "title": "wpanel-tickets/wpanel_tickets/screens.py",
                "kind": "file", "origin": "package", "repo": "K_TIX", "repo_name": "wpanel-tickets",
                "path": "wpanel_tickets/screens.py", "targets": ["src/wpanel_sdk/ui/__init__.py::IRNode"]},
               {"id": "K_ELSE:app/use.py", "title": "else/app/use.py", "kind": "file", "origin": "package",
                "repo": "K_ELSE", "repo_name": "else", "path": "app/use.py", "targets": []}]}}
    tix = {"ok": True, "repo_key": "K_TIX", "resolved": [], "data": {"items": []}}
    out = _merge_folder_answers([("core/wpanel-sdk", sdk), ("modules/wpanel-tickets", tix)],
                                units_by_key={"K_SDK": "core/wpanel-sdk", "K_TIX": "modules/wpanel-tickets"})
    ids = [i["id"] for i in out["data"]["items"]]
    assert ids == ["core/wpanel-sdk/src/wpanel_sdk/x.py", "modules/wpanel-tickets/wpanel_tickets/screens.py",
                   "else/app/use.py"]
    assert out["data"]["items"][1]["targets"] == ["core/wpanel-sdk/src/wpanel_sdk/ui/__init__.py::IRNode"]
    assert out["data"]["items"][2]["outside_folder"] is True
    assert out["resolved"] == ["core/wpanel-sdk/src/wpanel_sdk/ui/__init__.py::IRNode"]
    assert out["summary"].startswith("core/wpanel-sdk: 1 file(s) use IRNode")


def test_the_semantic_arm_and_the_best_match_survive_the_merge():
    a = {"ok": True, "semantic": None, "data": {"items": [{"id": "x.py::other", "title": "other"}]}}
    b = {"ok": True, "semantic": "model2vec", "data": {"items": [{"id": "g.py::runGuard", "title": "runGuard"}]}}
    out = _merge_folder_answers([("a", a), ("b", b)], query="runGuard", k=5)
    assert out["semantic"] == "model2vec" and out["best_match"] == "runGuard"


def test_a_contract_held_under_several_keys_is_listed_once():
    ep = {"method": "GET", "route": "/v1/x", "path": "app/api.py", "handler": "get_x"}
    cat = [{**ep, "repo_key": k} for k in ("k1", "k2", "k3", "k4")] + [{**ep, "route": "/v1/y", "repo_key": "k1"}]
    got = _one_per_contract(cat)
    assert len(got) == 2 and got[0]["held_by"] == ["k1", "k2", "k3", "k4"]


def test_grep_from_a_folder_of_repositories(tmp_path: Path):
    for r in ("core/sdk", "modules/tickets"):
        (tmp_path / r / ".git").mkdir(parents=True)
    (tmp_path / "core/sdk/a.py").write_text("NEEDLE = 1\n")
    (tmp_path / "modules/tickets/b.py").write_text("x = 'NEEDLE'\n")
    out = ExoskeletonRuntime(workspace=str(tmp_path)).grep_code("NEEDLE")
    assert out["status"] == "ok" and sorted(m["path"] for m in out["matches"]) == ["core/sdk/a.py",
                                                                                   "modules/tickets/b.py"]



def test_a_repository_that_did_not_answer_is_said_and_never_read_as_not_defined(tmp_path: Path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=object())
    ans = {"ok": True, "repo_key": "a,b", "resolved": False, "data": {"items": []},
           "partial": ["imperal-sdk: the vault graph could not be asked: 502 memory store unavailable"]}
    monkeypatch.setattr(exo, "_ask", lambda *a, **k: ans)
    out = exo.impact_of_change(["impact_summary"])
    assert out["partial"] == ans["partial"]
    assert "did not answer" in out["note"] and "not a definition in the graph" not in out["note"]
