"""Defects found by the imperal-mcp 0.9.14 field test (2026-11-13), each held by a test."""
import asyncio

import pytest

from imperal_mcp.irkit import LINK_SAVER_EXAMPLE, validate_ir
from imperal_mcp.server import run_read_tool_logic, run_write_tool_logic, Autopilot, build_server


class _Apps:
    def __init__(self, tools):
        self.tools, self.ran = tools, []

    async def get_app(self, app_id):
        return {"tools_json": self.tools}

    async def get_marketplace_app(self, app_id):
        return {"tools": []}

    async def run_tool(self, app_id, function, args):
        self.ran.append(function)
        return {"ok": True}

    async def operate(self, *a, **k):
        self.ran.append(a[1])
        return {"kind": "tool_result", "content": {}}


@pytest.mark.asyncio
async def test_an_unknown_tool_is_named_as_unknown_with_the_apps_tools():
    c = _Apps([{"name": "list_links", "action_type": "read"}, {"name": "save_link", "action_type": "write"}])
    out = await run_read_tool_logic(c, "link-saver", "no_such_tool", {})
    assert out["refused"] and "has no tool 'no_such_tool'" in out["reason"] and "list_links" in out["reason"]
    out = await run_write_tool_logic(c, None, "link-saver", "no_such_tool", {}, Autopilot())
    assert "has no tool 'no_such_tool'" in out["reason"]
    out = await run_read_tool_logic(c, "link-saver", "save_link", {})     # a real write tool keeps its tier refusal
    assert out["refused"] and "read-only" in out["reason"]
    assert c.ran == []


def test_the_shipped_example_validates_and_stores_the_url_it_was_given():
    from imperal_sdk.runtime.interpreter import run_steps
    assert validate_ir(LINK_SAVER_EXAMPLE).get("valid") is True

    class _Store:
        docs = []

        async def create(self, coll, data):
            self.docs.append((coll, data))
            return {"id": "1"}

    class _Ctx:
        store = _Store()

    steps = LINK_SAVER_EXAMPLE["app"]["functions"][0]["impl"]["steps"]
    asyncio.run(run_steps(steps, _Ctx(), event={"url": "https://imperal.io"}))
    assert _Ctx.store.docs == [("link", {"url": "https://imperal.io"})]


@pytest.mark.asyncio
async def test_remember_fact_refuses_an_unknown_scope_without_a_call(tmp_path):
    class _NoCall:
        async def run_tool(self, *a, **k):
            raise AssertionError("no network call for an invalid scope")
    srv = build_server(_NoCall(), workspace=str(tmp_path))
    res = await srv.call_tool("remember_fact", {"fact": "x", "scope": "wpanel"})
    text = str(res)
    assert "global, task, surface" in text


@pytest.mark.asyncio
async def test_recall_keeps_this_repos_note_when_others_rank_first(tmp_path, monkeypatch):
    class _Mem:
        def __init__(self):
            self.asked = None

        async def run_tool(self, app, fn, params):
            self.asked = params["limit"]
            return {"data": {"snippets": [
                {"category": "repo_knowledge", "source_id": "other", "content": "a"},
                {"category": "repo_knowledge", "source_id": "mine", "content": "b"},
                {"category": "repo_knowledge", "source_id": "mine", "content": "c"}]}}
    c = _Mem()
    srv = build_server(c, workspace=str(tmp_path))
    monkeypatch.setattr(srv._exoskeleton, "current_repo_keys", lambda root=None: {"mine"})
    res = await srv.call_tool("recall_context", {"query": "q", "limit": 1})
    text = str(res)
    assert c.asked == 3 and '\"content\": \"b\"' in text
    assert '\"content\": \"a\"' not in text and '\"content\": \"c\"' not in text


@pytest.mark.asyncio
async def test_an_upload_without_document_id_says_so(tmp_path, monkeypatch):
    from imperal_mcp.client import ImperalClient
    from imperal_mcp.config import Config
    f = tmp_path / "a.txt"
    f.write_text("hi")
    c = ImperalClient(Config(api_url="http://gw", token="t"))

    async def who():
        return "imp_u_1"

    async def req(*a, **k):
        return {"data": {"items": [{"file_id": 5, "document_id": None, "status": "indexing"}]}}
    monkeypatch.setattr(c, "whoami", who)
    monkeypatch.setattr(c, "_request", req)
    out = await c.upload_file(str(f))
    assert out["file_id"] == 5 and "no document_id" in out["document_id_missing"]


def test_a_russian_quote_of_a_comment_finds_its_function_first(tmp_path):
    from imperal_mcp.exoskeleton import _normalize_search_matches
    (tmp_path / "auth.py").write_text("def complete_sign_in():\n    # Завершить вход пользователя\n    return 1\n")
    (tmp_path / "bill.py").write_text("def charge():\n    # Списать деньги со счёта\n    return 2\n")
    by_meaning = [{"id": "x:chunk:bill.py:1", "path": "bill.py", "match": "strong", "text": "def charge(): ..."}]
    got = _normalize_search_matches(by_meaning, str(tmp_path), "Завершить вход пользователя", k=5)
    assert got[0]["path"] == "auth.py" and got[0]["line"] == 2
    assert [g for g in got if g["path"] == "bill.py"][0]["match"] == "weak"


def test_hits_that_hold_a_query_word_are_kept_as_they_are(tmp_path):
    from imperal_mcp.exoskeleton import _normalize_search_matches
    hits = [{"id": "x", "path": "a.py", "name": "complete_sign_in", "match": "strong"}]
    assert _normalize_search_matches(hits, str(tmp_path), "complete_sign_in", k=5) == [
        {**hits[0], "file": "a.py"}]


def test_a_huge_graph_slice_symbol_fits_the_bound_and_says_what_was_cut():
    import json
    from imperal_mcp.exoskeleton import bounded, lean_slice_item, ANSWER_CHARS
    callers = [{"path": f"m{i}.py", "line": i, "name": f"caller_{i}"} for i in range(40)]
    item = {"qualname": "big", "text": "x = 1\n" * 20000, "callers": [c["name"] for c in callers],
            "callers_detail": callers}
    lean = lean_slice_item(item)
    assert "callers" not in lean and len(lean["callers_detail"]) == 15 and lean["callers_total"] == 40
    assert lean["text_lines_total"] == 20001 and lean["text"].count("\n") <= 81
    raw = {"status": "ok", "symbols": [item]}
    out = bounded(raw)
    assert len(json.dumps(out, ensure_ascii=False)) <= ANSWER_CHARS and "truncated" in out


def test_four_copies_of_one_contract_are_one_held_by_four():
    from imperal_mcp.exoskeleton import _one_per_contract
    base = {"kind": "endpoint", "method": "GET", "route": "/v1/panel/redirect", "handler": "redirect"}
    copies = [{**base, "repo_key": "k1", "path": "app/r.py", "line": 10},
              {**base, "repo_key": "k2", "path": "gw/app/r.py", "line": 10},
              {**base, "repo_key": "k3", "path": "app/r.py", "line": 7},
              {**base, "repo_key": "k4", "path": "app/r.py", "line": 10}]
    out = _one_per_contract(copies)
    assert len(out) == 1 and out[0]["held_by"] == ["k1", "k2", "k3", "k4"]


def test_a_web_search_fetch_or_subagent_report_reaches_the_kernel_scrubbed():
    from imperal_mcp import hooks as H
    for name, inp, resp in [
        ("WebSearch", {"query": "imperal mcp"}, {"results": [{"title": "Imperal MCP", "url": "https://x"}]}),
        ("WebFetch", {"url": "https://claude.com/docs", "prompt": "list rules"}, {"result": "Anyone on a paid plan"}),
        ("Agent", {"description": "Root-cause index", "prompt": "..."}, {"content": "Root cause: code_index.py:1649"}),
    ]:
        (item,) = H.tool_items({"tool_name": name, "tool_input": inp, "tool_response": resp})
        assert item["tool"] == name.lower() and item["text"], name
    (item,) = H.tool_items({"tool_name": "WebFetch", "tool_input": {"url": "https://x"},
                            "tool_response": {"result": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890"}})
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in item["text"]
    (other,) = H.tool_items({"tool_name": "mcp__other__thing", "tool_input": {"x": 1}, "tool_response": "secret"})
    assert other["text"] == "" and other["args"] == {}


# ── field test report 2, 2026-11-13 ──

def test_a_root_that_is_not_there_is_refused_never_answered_as_the_workspace(tmp_path):
    from imperal_mcp.exoskeleton import ExoskeletonRuntime, OutsideWorkspaceError
    (tmp_path / "sub").mkdir()
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    assert exo.resolve_workspace("sub") == str((tmp_path / "sub").resolve())          # relative: from the workspace
    with pytest.raises(OutsideWorkspaceError, match="does not exist"):
        exo.resolve_workspace("non_existent_dir")


def test_a_bad_regex_says_where_and_how_to_fix_it(tmp_path):
    import subprocess
    from imperal_mcp.exoskeleton import ExoskeletonRuntime
    (tmp_path / "a.py").write_text("x = (1)\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    got = ExoskeletonRuntime(workspace=str(tmp_path)).grep_code("(1", regex=True)
    assert got["status"] == "error" and "not a valid regular expression" in got["error"]
    assert "<HERE>" in got["error"] and "regex=false" in got["error"]


def test_token_savings_claims_nothing_for_grep_like_tools_and_only_definitions_for_graph_slice(tmp_path):
    import json
    from imperal_mcp.exoskeleton import ExoskeletonRuntime
    (tmp_path / "defs.py").write_text("def f():\n    return 1\n" * 50)
    (tmp_path / "caller.py").write_text("from defs import f\nf()\n" * 200)
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo._record_read("impact_of_change", returned_text=json.dumps([{"id": "caller.py"}]))
    exo._record_read("graph_slice", returned_text=json.dumps(
        [{"path": "defs.py", "callers_detail": [{"path": "caller.py"}]}]))
    s = exo.token_savings()
    assert s["unmeasured_calls"] == 1 and s["files_behind_answers"] == 1
    assert s["would_read_chars"] == len((tmp_path / "defs.py").read_text())


@pytest.mark.asyncio
async def test_live_sessions_is_an_overview_unless_asked_whole(tmp_path, monkeypatch):
    import json
    from imperal_mcp import server as S
    srv = build_server(None, workspace=str(tmp_path))
    big = {"sessions": [{"id": f"s{i}", "last_answer": "x" * 3000} for i in range(8)]}
    def lens(**kw):          # the server knows the runtime's lens by its name
        return big
    monkeypatch.setattr(srv._exoskeleton, "lens", lens)
    lean = _text_of(await srv.call_tool("live_sessions", {}))
    whole = _text_of(await srv.call_tool("live_sessions", {"full": True}))
    assert len(lean) < S.LIVE_SESSIONS_CHARS + 2000 < len(whole)


def _text_of(res):
    content = res[0] if isinstance(res, tuple) else res
    return " ".join(getattr(c, "text", "") for c in content) if not isinstance(content, dict) else str(content)


@pytest.mark.asyncio
async def test_a_project_scope_is_pointed_to_repository_notes(tmp_path):
    class _NoCall:
        async def run_tool(self, *a, **k):
            raise AssertionError("no call")
    srv = build_server(_NoCall(), workspace=str(tmp_path))
    assert "save_repo_note" in _text_of(await srv.call_tool("remember_fact", {"fact": "x", "scope": "wpanel"}))
