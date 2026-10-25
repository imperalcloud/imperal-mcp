from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from imperal_mcp import auth
from imperal_mcp.cli import (
    install_claude_hooks,
    main as cli_main,
    run_claude_hook,
    setup_claude_code,
)
from imperal_mcp.client import ImperalClient
from imperal_mcp.config import Config
from imperal_mcp.exoskeleton import (
    EXOSKELETON_INSTRUCTIONS,
    MISSING_CODE_DEPENDENCY_MESSAGE,
    ExoskeletonRuntime,
    MissingCodeDependencyError,
    OutsideWorkspaceError,
    TokenSavingsTracker,
)
from imperal_mcp.server import build_server


class MemoryFakeClient(ImperalClient):
    def __init__(self):
        super().__init__(Config(api_url="http://gw", token="tok_test"))
        self.calls: list[tuple[str, str, dict]] = []

    async def run_tool(self, app_id: str, function: str, params: dict | None = None):
        self.calls.append((app_id, function, dict(params or {})))
        return {
            "status": "success",
            "data": {
                "app_id": app_id,
                "function": function,
                "params": params or {},
                "email": "user@example.com",
            },
        }


@pytest.fixture()
def sample_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "demo_repo"
    ws.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.email", "test@imperal.io"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "Imperal Test"], cwd=ws, check=True)

    pkg = ws / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "math_ops.py").write_text(
        "def compute_total(price: float, tax: float = 0.2) -> float:\n"
        "    \"\"\"Compute total price including tax.\"\"\"\n"
        "    return round(price * (1.0 + tax), 2)\n\n"
        "class InvoiceCalculator:\n"
        "    def bill(self, amount: float) -> float:\n"
        "        return compute_total(amount)\n",
        encoding="utf-8",
    )
    (pkg / "caller.py").write_text(
        "from pkg.math_ops import compute_total\n\n"
        "def checkout_order(items: list[float]) -> float:\n"
        "    return sum(compute_total(x) for x in items)\n",
        encoding="utf-8",
    )
    (ws / "pyproject.toml").write_text(
        '[project]\nname = "demo-repo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=ws, check=True)
    return ws


def test_token_savings_has_no_baseline_claim():
    """frame phase A (spec A6): a useless list must never pass for savings -- calls and returned size only."""
    tracker = TokenSavingsTracker()
    rec = tracker.record("outline", returned_chars=400, baseline_chars=4000, returned_lines=15,
                         baseline_lines=150, baseline_files=1)
    assert rec == {"tool": "outline", "returned_chars": 400, "returned_lines": 15}
    summary = tracker.summary()
    assert summary == {"calls": 1, "returned_chars": 400, "returned_lines": 15,
                       "by_tool": {"outline": {"calls": 1, "returned_chars": 400, "returned_lines": 15}}}


def test_exoskeleton_code_graph_and_ast_tools(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace))

    prof = exo.repo_profile()
    assert prof["status"] == "ok"
    assert "profile" in prof
    assert "rendered" not in prof
    assert "_roi" not in prof and "roi" not in prof

    ori = exo.orient("compute_total invoice")
    assert ori["status"] == "ok"
    assert "profile" in ori and "matches" in ori
    assert "rendered" not in ori
    assert any("compute_total" in json.dumps(m) for m in ori["matches"])
    assert "_roi" not in ori

    srch = exo.search_code("compute_total")
    assert srch["status"] == "ok"
    assert any("math_ops.py" in (m.get("path") or m.get("file") or "") for m in srch.get("matches", []))
    assert "rendered" not in srch

    slc = exo.graph_slice(["compute_total"])
    assert slc["status"] == "ok"
    assert any("compute_total" in json.dumps(s) for s in slc["symbols"])
    assert "_roi" not in slc and "slice" not in slc and "rendered" not in slc

    imp = exo.impact_of_change(["compute_total"])
    assert imp["status"] == "ok"
    assert "_roi" not in imp and "impact" not in imp and "rendered" not in imp
    assert "dependent_files" in imp

    cslice = exo.contract_slice(symbols=["compute_total"])
    assert cslice["status"] == "ok"
    assert any("compute_total" in json.dumps(s) for s in cslice["symbols"])
    assert "_roi" not in cslice and "rendered" not in cslice

    out = exo.outline("pkg/math_ops.py")
    assert out["status"] == "ok"
    assert out["symbol_count"] >= 2
    names = [s["name"] for s in out["symbols"]]
    assert "compute_total" in names
    assert "_roi" not in out

    sym = exo.read_symbol("pkg/math_ops.py", "compute_total")
    assert sym["status"] == "ok"
    assert "def compute_total" in sym["rendered"]
    assert "_roi" not in sym

    span = exo.read_symbol("pkg/math_ops.py", "L1-L3")
    assert span["status"] == "ok"
    assert span["symbol"] == "L1-3"
    assert "def compute_total" in span["rendered"]

    missing = exo.read_symbol("pkg/math_ops.py", "nonexistent_symbol")
    assert missing["status"] == "error"
    assert "available_outline" in missing

    syn_ok = exo.check_syntax("pkg/math_ops.py")
    assert syn_ok["status"] == "ok" and syn_ok["clean"] is True

    bad_file = sample_workspace / "pkg" / "broken.py"
    bad_file.write_text("def broken(:\n    pass\n", encoding="utf-8")
    syn_bad = exo.check_syntax("pkg/broken.py")
    assert syn_bad["status"] == "ok" and syn_bad["clean"] is False
    assert syn_bad["error_count"] >= 1
    bad_file.unlink()

    cctx = exo.coding_context()
    assert cctx["status"] == "ok"
    assert "demo_repo" in cctx["workspace"]
    assert "context" not in cctx

    savings = exo.token_savings()
    assert savings["status"] == "ok"
    assert savings["calls"] >= 7
    assert "baseline_basis" not in savings and "saved_chars" not in savings      # spec A6: no savings claim
    assert savings["by_tool"]["outline"]["calls"] >= 1 and savings["by_tool"]["outline"]["returned_chars"] > 0


def test_exoskeleton_rejects_outside_workspace_path(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace))
    with pytest.raises(OutsideWorkspaceError):
        exo.outline("../outside.py")
    with pytest.raises(OutsideWorkspaceError):
        exo.resolve_workspace("~/.zshrc")
    with pytest.raises(OutsideWorkspaceError):
        exo.repo_profile(root=str(sample_workspace.parent))


def test_exoskeleton_shadowgit_checkpoint_diff_and_rollback(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace))
    target_file = sample_workspace / "pkg" / "math_ops.py"
    original = target_file.read_text(encoding="utf-8")

    cp = exo.checkpoint(label="before-edit", touched_paths=["pkg/math_ops.py"])
    assert cp["status"] == "ok"
    assert cp["step"] == 1

    target_file.write_text(original + "\n# mutated\n", encoding="utf-8")
    diff = exo.checkpoint_diff(target=1)
    assert diff["status"] == "ok"
    assert "+# mutated" in diff["diff"]

    rb = exo.checkpoint_rollback(target=1)
    assert rb["status"] == "ok" and rb["restored"] is True
    assert target_file.read_text(encoding="utf-8") == original


def test_claude_setup_and_status_cli(tmp_path: Path, capsys):
    ws = tmp_path / "claude_ws"
    ws.mkdir()
    # Pre-populate .mcp.json with another server and CLAUDE.md with user notes
    (ws / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "other-mcp"}}}),
        encoding="utf-8",
    )
    (ws / "CLAUDE.md").write_text("# My Custom Project Rules\n\nKeep code clean.\n", encoding="utf-8")

    res = setup_claude_code(ws)
    assert Path(res["mcp_json"]).exists()
    assert Path(res["claude_md"]).exists()

    mcp_data = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    assert "other" in mcp_data["mcpServers"]
    assert "imperal" in mcp_data["mcpServers"]
    assert mcp_data["mcpServers"]["imperal"]["env"]["IMPERAL_WORKSPACE"] == str(ws.resolve())

    claude_md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "# My Custom Project Rules" in claude_md
    assert "IMPERAL-MCP-EXOSKELETON:START" in claude_md

    # Idempotent re-run must not duplicate block
    setup_claude_code(ws)
    claude_md_2 = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md_2.count("IMPERAL-MCP-EXOSKELETON:START") == 1

    # CLI status command
    cli_main(["status", "--workspace", str(ws)])
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_build_server_registers_exoskeleton_and_memory_tools(sample_workspace: Path):
    client = MemoryFakeClient()
    srv = build_server(client, workspace=str(sample_workspace))
    assert srv is not None
    assert EXOSKELETON_INSTRUCTIONS in (getattr(srv, "instructions", "") or EXOSKELETON_INSTRUCTIONS)

    tm = getattr(srv, "_tool_manager", None)
    tools = getattr(tm, "_tools", None) or {}
    if not tools and hasattr(srv, "list_tools"):
        listed = await srv.list_tools()
        tool_names = {t.name for t in listed}
    else:
        tool_names = set(tools.keys())

    expected_tools = {
        "orient",
        "repo_profile",
        "search_code",
        "outline",
        "read_symbol",
        "graph_slice",
        "contract_slice",
        "impact_of_change",
        "check_syntax",
        "coding_context",
        "checkpoint",
        "checkpoint_diff",
        "checkpoint_rollback",
        "token_savings",
        "recall_context",
        "remember_fact",
        "save_repo_note",
    }
    assert expected_tools.issubset(tool_names)

    if tools:
        # Verify cloud memory tools dispatch to memory-index and apply PII defensive_scrub
        recall_fn = tools["recall_context"].fn
        recall_res = await recall_fn(query="standing rules", limit=3)
        assert recall_res["data"]["app_id"] == "memory-index"
        assert recall_res["data"]["function"] == "recall_context"
        assert recall_res["data"]["email"] != "user@example.com"

        remember_fn = tools["remember_fact"].fn
        rem_res = await remember_fn(fact="Always run pytest", category="directive", tags=["testing"])
        assert rem_res["data"]["app_id"] == "memory-index"
        assert rem_res["data"]["function"] == "add_user_fact"

        note_fn = tools["save_repo_note"].fn
        note_res = await note_fn(note="Monorepo uses ShadowGit", citations=["exoskeleton.py:1"])
        assert note_res["data"]["app_id"] == "memory-index"
        assert note_res["data"]["function"] == "add_note"
        assert note_res["data"]["params"]["repo"] == "demo_repo"


def test_cli_login_and_logout_subcommands(monkeypatch, capsys):
    assert hasattr(auth, "login_device")
    assert callable(auth.login_device)

    called: dict = {}

    async def fake_login_device(cfg, *, open_browser: bool = True):
        called["login"] = (cfg.api_url, open_browser)
        return "dev@imperal.io"

    async def fake_logout(cfg):
        called["logout"] = cfg.api_url

    monkeypatch.setattr(auth, "login_device", fake_login_device)
    monkeypatch.setattr(auth, "logout", fake_logout)

    cli_main(["login", "--no-browser"])
    out_login = capsys.readouterr().out
    assert "Logged in as dev@imperal.io." in out_login
    assert called["login"][1] is False

    cli_main(["logout"])
    out_logout = capsys.readouterr().out
    assert "Logged out." in out_logout
    assert "logout" in called


def test_cli_install_hooks_and_hook_subcommands(sample_workspace: Path, capsys):
    cli_main(["install-hooks", "--workspace", str(sample_workspace)])
    out_hooks = json.loads(capsys.readouterr().out)
    assert out_hooks["status"] == "ok"
    settings_path = Path(out_hooks["settings_path"])
    assert settings_path.exists()

    # Re-running install-hooks is idempotent
    install_claude_hooks(sample_workspace)
    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
    post_hooks = settings_data["hooks"]["PostToolUse"]
    assert len(post_hooks) == 1
    assert "hook post-tool-use" in post_hooks[0]["hooks"][0]["command"]

    # claude-setup --with-hooks also configures hooks
    cli_main(["claude-setup", "--workspace", str(sample_workspace), "--with-hooks"])
    setup_out = json.loads(capsys.readouterr().out)
    assert setup_out["status"] == "ok"
    assert setup_out["hooks"] == str(settings_path)

    # Direct hook invocation checks syntax when file_path is provided
    hook_res = run_claude_hook(
        "post-tool-use",
        workspace=sample_workspace,
        payload={"tool_input": {"file_path": "pkg/math_ops.py"}},
    )
    assert hook_res["status"] == "ok"
    assert hook_res["syntax_check"]["clean"] is True

    # CLI hook subcommand: a shell hook prints nothing when it has nothing to tell the model (memory plan Task 4)
    with pytest.raises(SystemExit) as ended:
        cli_main(["hook", "post-tool-use", "--workspace", str(sample_workspace)])
    assert ended.value.code == 0 and capsys.readouterr().out == ""


def test_search_code_without_semantic_vectors(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace))
    _, svc, _ = exo._get_indexer()
    # Simulate an environment where model2vec / semantic vectors are unavailable
    svc.vectors = None

    srch = exo.search_code("compute_total")
    assert srch["status"] == "ok"
    assert any("math_ops.py" in (m.get("path") or m.get("file") or "") for m in srch.get("matches", []))

    srch_file = exo.search_code("math_ops.py")
    assert srch_file["status"] == "ok"
    assert any("math_ops.py" in (m.get("path") or m.get("file") or "") for m in srch_file.get("matches", []))


def test_missing_webbee_dependency_error_and_status(tmp_path: Path, monkeypatch, capsys):
    import sys

    monkeypatch.setitem(sys.modules, "webbee", None)
    monkeypatch.setitem(sys.modules, "webbee.intel", None)
    monkeypatch.setitem(sys.modules, "webbee.intel.outline", None)
    monkeypatch.setitem(sys.modules, "webbee.intel.query", None)
    monkeypatch.setitem(sys.modules, "webbee.intel.service", None)

    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    with pytest.raises(MissingCodeDependencyError) as exc_info:
        exo.repo_profile()
    assert "imperal-mcp[code]" in str(exc_info.value)
    assert str(exc_info.value) == MISSING_CODE_DEPENDENCY_MESSAGE

    cli_main(["status", "--workspace", str(tmp_path)])
    status_out = json.loads(capsys.readouterr().out)
    assert status_out["status"] == "error"
    assert "imperal-mcp[code]" in status_out["error"]

    broken_py = tmp_path / "broken_without_ts.py"
    broken_py.write_text("def broken(\n", encoding="utf-8")
    hook_out = run_claude_hook(
        "post-tool-use",
        workspace=tmp_path,
        payload={"tool_input": {"file_path": "broken_without_ts.py"}},
    )
    assert hook_out["status"] == "syntax_error"
    assert hook_out["exit_code"] == 2
    assert hook_out["syntax_check"]["clean"] is False
    assert hook_out["syntax_check"]["error_count"] >= 1
    err_out = capsys.readouterr().err
    assert "broken_without_ts.py" in err_out

    unknown_file = tmp_path / "notes.unknown_ext"
    unknown_file.write_text("hello ???", encoding="utf-8")
    chk_unknown = exo.check_syntax("notes.unknown_ext")
    assert chk_unknown["status"] == "ok"
    assert chk_unknown["supported"] is False
    assert chk_unknown["clean"] is None


def test_malformed_json_configs_are_not_overwritten(tmp_path: Path):
    mcp_path = tmp_path / ".mcp.json"
    bad_mcp = '{"mcpServers": {"existing": {}}, INVALID_JSON'
    mcp_path.write_text(bad_mcp, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        setup_claude_code(tmp_path)
    assert mcp_path.read_text(encoding="utf-8") == bad_mcp

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.local.json"
    bad_settings = '{"permissions": {"allow": ["Bash(git:*)"]}, BROKEN'
    settings_path.write_text(bad_settings, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        install_claude_hooks(tmp_path)
    assert settings_path.read_text(encoding="utf-8") == bad_settings


def test_root_parameter_cannot_escape_workspace(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace))
    with pytest.raises(OutsideWorkspaceError):
        exo.resolve_workspace("~/.zshrc")
    with pytest.raises(OutsideWorkspaceError):
        exo.repo_profile(root="/etc")
    with pytest.raises(OutsideWorkspaceError):
        exo.outline("math_ops.py", root="../")






# ── frame phase A, Task 7: the code tools ask the vault graph ──

class _Cloud:
    """The gateway as a fake: records every call; answers by path."""
    def __init__(self, answers=None, fail=False):
        self.calls, self.answers, self.fail = [], dict(answers or {}), fail

    async def _request(self, method, path, *, json=None, params=None, timeout=60):
        self.calls.append((method, path, params, json))
        if self.fail and "/code/sync/" not in path:
            raise RuntimeError("gateway down")
        if path.endswith("/sync/plan"):
            return {"repo_key": "rk1", "changed": [i["path"] for i in json["listing"]], "removed": [], "have_blobs": []}
        if path.endswith("/sync/apply"):
            return {"files": len(json["files"]), "links": 0}
        for key, ans in self.answers.items():
            if path.endswith(key):
                return ans
        return {"ok": True, "data": {"items": []}}


def _impact_answer():
    return {"ok": True, "repo_key": "rk1", "synced_at": 9.0,
            "data": {"items": [{"id": "pkg/caller.py", "title": "pkg/caller.py", "kind": "file", "via": "scope",
                                "group": "code", "callers": [{"user": "checkout_order", "line": 4}]}]}}


def test_impact_asks_vault_and_returns_its_items(sample_workspace: Path):
    cloud = _Cloud({"/code/impact": _impact_answer()})
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud)
    out = exo.impact_of_change(["compute_total"])
    assert out["dependent_files"] == ["pkg/caller.py"] and out["source"] == "vault graph" and "coarse" not in out
    impact = [c for c in cloud.calls if c[1].endswith("/code/impact")][0]
    assert impact[3]["repo_key"] == "rk1" and impact[3]["symbols"] == ["compute_total"]


def test_search_code_sends_vector_when_embedder_present(sample_workspace: Path, monkeypatch):
    import imperal_sdk.code_index as ci
    monkeypatch.setattr(ci, "embed_query", lambda text: b"\x00\x00\x80?")
    cloud = _Cloud({"/code/search": {"ok": True, "semantic": "on", "data": {"items": [
        {"id": "pkg/math_ops.py::compute_total", "title": "compute_total", "kind": "function",
         "path": "pkg/math_ops.py", "start_line": 1, "end_line": 3, "match": "exact"}]}}})
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud)
    out = exo.search_code("compute_total")
    search = [c for c in cloud.calls if c[1].endswith("/code/search")][0]
    assert search[2]["vector"] and search[2]["q"] == "compute_total"
    assert out["matches"][0]["title"] == "compute_total" and out["semantic"] == "on"


def test_vault_error_falls_back_marked_coarse(sample_workspace: Path):
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=_Cloud(fail=True))
    out = exo.impact_of_change(["compute_total"])
    assert out["coarse"] == "vault graph unavailable: links by name" and out["status"] == "ok"


def test_no_cloud_is_coarse(sample_workspace: Path):
    out = ExoskeletonRuntime(workspace=str(sample_workspace)).impact_of_change(["compute_total"])
    assert out["coarse"] == "vault graph unavailable: links by name"


def test_orient_profile_once_top_symbols_by_use(sample_workspace: Path):
    cloud = _Cloud({"/code/search": {"ok": True, "semantic": "off", "data": {"items": [
        {"id": "pkg/math_ops.py::compute_total", "title": "compute_total", "path": "pkg/math_ops.py",
         "kind": "function", "start_line": 1, "end_line": 3}]}},
        "/code/profile": {"ok": True, "data": {"items": [{"repo_key": "rk1", "file_count": 3, "def_count": 4,
                                                           "languages": {"python": 3},
                                                           "top_symbols": ["compute_total @ pkg/math_ops.py (used by 1 files)"]}]}}})
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud)
    out = exo.orient("compute total")
    assert out["profile"] == {"repo_key": "rk1", "file_count": 3, "def_count": 4, "languages": {"python": 3},
                              "top_symbols": ["compute_total @ pkg/math_ops.py (used by 1 files)"]}
    assert out["matches"][0]["title"] == "compute_total"


def test_remote_target_resolves_repo_from_catalog(sample_workspace: Path):
    cloud = _Cloud({"/code/repos": {"repos": [{"repo_key": "1a1a308590ae", "root_path": "/home/ipw-repo",
                                               "machine_label": "whm-jump"},
                                              {"repo_key": "other", "root_path": "/home/x"}]},
                    "/code/impact": _impact_answer()})
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud)
    exo.impact_of_change(["f"], target="host:whm-jump", root="/home/ipw-repo")
    impact = [c for c in cloud.calls if c[1].endswith("/code/impact")][0]
    assert impact[3]["repo_key"] == "1a1a308590ae"
    assert not [c for c in cloud.calls if "/code/sync/" in c[1]]          # a remote repo is never synced from here


def test_recall_drops_other_repo_notes_and_duplicates():
    from imperal_mcp.exoskeleton import scope_recall
    res = {"data": {"snippets": [
        {"category": "repo_knowledge", "source_id": "rk1", "content": "a"},
        {"category": "repo_knowledge", "source_id": "rk1", "content": "a"},
        {"category": "repo_knowledge", "source_id": "other", "content": "b"},
        {"category": "preference", "source_id": "u", "content": "c"}]}}
    out = scope_recall(res, "rk1")
    assert [s["content"] for s in out["data"]["snippets"]] == ["a", "c"]


def test_recall_outside_a_known_repo_keeps_every_note():
    from imperal_mcp.exoskeleton import scope_recall
    res = {"data": {"snippets": [{"category": "repo_knowledge", "source_id": "x", "content": "a"},
                                 {"category": "repo_knowledge", "source_id": "y", "content": "b"}]}}
    assert [s["content"] for s in scope_recall(res, {"not-a-repo"})["data"]["snippets"]] == ["a", "b"]


def test_vault_calls_run_on_the_server_loop(sample_workspace: Path):
    """review I5: one event loop for the Imperal client (its token refresh lock assumes it) -- a code tool run on a
    worker thread drives its cloud calls on the server's loop."""
    import asyncio
    import threading
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    seen = []

    class _LoopCloud(_Cloud):
        async def _request(self, method, path, **kw):
            seen.append(asyncio.get_running_loop())
            return await super()._request(method, path, **kw)
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=_LoopCloud({"/code/impact": _impact_answer()}))
    exo.loop = loop
    exo.impact_of_change(["compute_total"])
    loop.call_soon_threadsafe(loop.stop)
    assert seen and all(s is loop for s in seen)


def test_orient_syncs_the_workspace_once(sample_workspace: Path):
    cloud = _Cloud({"/code/profile": {"ok": True, "data": {"items": [{"repo_key": "rk1"}]}}})
    ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud).orient("compute total")
    assert len([c for c in cloud.calls if c[1].endswith("/sync/plan")]) == 1


def test_an_unknown_symbol_says_it_is_not_in_the_graph(sample_workspace: Path):
    cloud = _Cloud({"/code/impact": {"ok": True, "repo_key": "rk1", "resolved": [], "data": {"items": []}}})
    out = ExoskeletonRuntime(workspace=str(sample_workspace), client=cloud).impact_of_change(["no_such_fn"])
    assert out["dependent_files"] == [] and out["note"] == "no_such_fn: not a definition in the graph"


# ── frame phase B, Task 10: the kernel's frame and the task tool for an external agent ──

def _frame_cloud():
    return _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"},
                   "/v1/memory/frame": {"frame": "=== DECISION ===\nTASK (fix alpha)", "tool_groups": ["code"]}})


def _frame_body(cloud):
    return [c[3] for c in cloud.calls if c[1] == "/v1/memory/frame"][-1]


def test_frame_sends_own_calls_and_measured_changes(tmp_path: Path):
    (tmp_path / "a.py").write_text("x=1\n")
    cloud = _frame_cloud()
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    exo.task("fix alpha", [{"content": "edit alpha", "status": "in_progress"}])
    exo.record_call("search_code", {"query": "alpha"}, ok=True, text="alpha in a.py")
    (tmp_path / "a.py").write_text("x=2\n")
    out = exo.frame()
    assert out["frame"].startswith("=== DECISION ===")
    body = _frame_body(cloud)
    assert body["session_id"].startswith("mcp-imp_u_ME-") and body["goal"] == "fix alpha" and body["step"] == 1
    assert [e["tool"] for e in body["exchange"]] == ["search_code", "edit_file"]
    assert body["exchange"][1]["args"]["path"] == "a.py" and "measured" in body["exchange"][1]["text"]
    exo.frame()
    again = _frame_body(cloud)
    assert again["exchange"] == [] and again["step"] == 2 and again["session_id"] == body["session_id"]


def test_a_failed_frame_keeps_the_exchange_for_the_next(tmp_path: Path):
    cloud = _Cloud(fail=True)
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    exo.record_call("search_code", {"query": "alpha"}, ok=True, text="")
    out = exo.frame()
    assert out["ok"] is False and out["content"].startswith("frame unavailable:")
    assert [e["tool"] for e in exo._exchange] == ["search_code"]


def test_a_frame_refused_for_credits_says_why_and_keeps_its_step(tmp_path: Path):
    """Phase D: the frame is paid (system pricing); a refusal names its reason, and the retry asks for the same step
    (the kernel charges once per step)."""
    from imperal_mcp.client import ImperalError
    why = "not enough credits for a frame (5 credits, balance 2) -- top up in the panel"

    class _Broke(_Cloud):
        async def _request(self, method, path, *, json=None, params=None, timeout=60):
            if path == "/v1/memory/frame":
                self.calls.append((method, path, params, json))
                raise ImperalError(f'POST {path} -> 402: {{"detail":"{why}"}}', status_code=402)
            return await super()._request(method, path, json=json, params=params, timeout=timeout)
    cloud = _Broke({"/v1/auth/me": {"imperal_id": "imp_u_ME"}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    out = exo.frame()
    assert out == {"ok": False, "content": why}
    exo.frame()
    assert [c[3]["step"] for c in cloud.calls if c[1] == "/v1/memory/frame"] == [1, 1]


def test_the_exchange_never_carries_a_secret_file_or_raw_pii(tmp_path: Path):
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo.record_call("read_symbol", {"path": "config/.env.local", "name": "L1-5"}, ok=True, text="DB_PASS=hunter2")
    exo.record_call("search_code", {"query": "mail"}, ok=True, text="owner: someone@example.com")
    assert exo._exchange[0]["text"] == "(withheld: a secret file)" and "hunter2" not in str(exo._exchange[0])
    assert "someone@example.com" not in exo._exchange[1]["text"]


def test_a_secret_directory_or_a_windows_path_is_withheld_too(tmp_path: Path):
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo.record_call("read_symbol", {"path": "deploy/secrets/db.yaml", "name": "L1-3"}, ok=True, text="pw: x1")
    exo.record_call("read_symbol", {"path": "C:\\Users\\me\\.ssh\\config", "name": "L1-3"}, ok=True, text="Host x")
    exo.record_call("read_symbol", {"path": "keys\\ID_RSA", "name": "L1-3"}, ok=True, text="-----BEGIN")
    assert [e["text"] for e in exo._exchange] == ["(withheld: a secret file)"] * 3


def test_a_secret_folder_named_by_the_root_is_withheld(tmp_path: Path):
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo.record_call("outline", {"path": "config", "root": "/home/me/.ssh"}, ok=True, text="Host x")
    exo.record_call("outline", {"root": "deploy/secrets"}, ok=True, text="pw")
    assert [e["text"] for e in exo._exchange] == ["(withheld: a secret file)"] * 2


def test_recording_never_breaks_a_tool_and_withholds_when_it_cannot_check(tmp_path: Path, monkeypatch):
    """Final review I6: an older imperal-sdk without SECRET_PATTERNS must not fail the code tools."""
    import sys
    monkeypatch.setitem(sys.modules, "imperal_sdk.code_index", None)      # import fails like an old sdk
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo.record_call("outline", {"path": "a.py"}, ok=True, text="def x(): pass")
    assert exo._exchange[-1]["tool"] == "outline" and exo._exchange[-1]["text"] == "(withheld: secrets not checked)"


def test_the_frame_pointers_reach_the_kernel_for_this_session(tmp_path: Path):
    cloud = _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"},
                    "/v1/memory/frame/lens": {"ok": True, "content": "reality rows"}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    out = exo.lens("state_lens", {"section": "reality"})
    assert out == {"ok": True, "content": "reality rows"}
    body = [c[3] for c in cloud.calls if c[1] == "/v1/memory/frame/lens"][-1]
    assert body["session_id"].startswith("mcp-imp_u_ME-") and body["tool"] == "state_lens"
    assert body["args"] == {"section": "reality"}


# ── a remote repo (host:<alias>) is synced before the question, like the local one (design §5.1) ──

def test_a_host_target_syncs_its_repo_before_the_question(tmp_path: Path, monkeypatch):
    import webbee.tools as wt
    calls = []

    async def fake_remote_sync(client, host, root, paths):
        calls.append((host, root, list(paths)))
        return {"repo_key": "rk_remote", "root": root, "host": host}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_remote"
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_remote"       # within the window: no second sync
    assert calls == [("whm-jump", "/home/ipw-repo", [])]


def test_a_host_sync_that_fails_falls_back_to_the_catalog(tmp_path: Path, monkeypatch):
    import webbee.tools as wt

    async def broken(client, host, root, paths):
        return {"repo_key": "", "partial_reason": "needs interactive login"}
    monkeypatch.setattr(wt, "remote_sync", broken)
    cloud = _Cloud({"/v1/memory/code/repos": {"repos": [{"repo_key": "rk_cat", "root_path": "/home/ipw-repo",
                                                          "machine_label": "whm-jump"}]}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_cat"


def test_a_known_host_repo_answers_at_once_while_it_refreshes(tmp_path: Path, monkeypatch):
    """A remote sync lists the tree over SFTP (~1 min live); after the first, a question never waits for it."""
    import threading
    import webbee.tools as wt
    from imperal_mcp import exoskeleton as ex
    gate, calls = threading.Event(), []

    async def slow_sync(client, host, root, paths):
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", slow_sync)
    monkeypatch.setattr(ex, "_HOST_SYNC_REUSE_S", 0.0)
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_remote"      # the first sync is waited for
    import time
    t = time.monotonic()
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_remote"      # the refresh runs behind
    assert time.monotonic() - t < 1.0
    gate.set()


def test_a_host_repo_in_the_catalog_never_waits_for_its_first_sync_here(tmp_path: Path, monkeypatch):
    import threading
    import time
    import webbee.tools as wt
    gate = threading.Event()

    async def slow_sync(client, host, root, paths):
        gate.wait(5)
        return {"repo_key": "rk_cat"}
    monkeypatch.setattr(wt, "remote_sync", slow_sync)
    cloud = _Cloud({"/v1/memory/code/repos": {"repos": [{"repo_key": "rk_cat", "root_path": "/home/ipw-repo",
                                                          "machine_label": "whm-jump"}]}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    t = time.monotonic()
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk_cat"
    assert time.monotonic() - t < 1.0
    gate.set()


# ── owner 2026-10-25: a folder that is no repository is never indexed whole; frame and file reads follow the target ──

def test_a_folder_that_is_no_repository_is_never_indexed(tmp_path: Path):
    import pytest
    from imperal_mcp.exoskeleton import NotARepositoryError
    (tmp_path / "Photos").mkdir()
    (tmp_path / "Photos" / "gallery.js").write_text("function show() {}\n")
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    with pytest.raises(NotARepositoryError) as e:
        exo.search_code("show")
    assert "not a repository" in str(e.value) and "root=" in str(e.value) and exo._indexers == {}


def test_frame_takes_the_repo_of_its_target(tmp_path: Path, monkeypatch):
    import webbee.tools as wt

    async def fake_remote_sync(client, host, root, paths):
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    cloud = _frame_cloud()
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    out = exo.frame(root="/home/ipw-repo", target="host:whm-jump")
    body = _frame_body(cloud)
    assert out["ok"] and body["repo_key"] == "rk_remote" and body["repo_root"] == "/home/ipw-repo"


def test_outline_and_read_symbol_of_a_host_target_read_the_graph(tmp_path: Path, monkeypatch):
    import webbee.tools as wt

    async def fake_remote_sync(client, host, root, paths):
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    cloud = _Cloud({"/v1/memory/code/outline": {"ok": True, "data": {"items": [
                        {"name": "run", "kind": "function", "start": 3, "end": 9, "depth": 0}]}, "synced_at": 1.0},
                    "/v1/memory/code/slice": {"ok": True, "data": {"items": [
                        {"path": "a.py", "qualname": "run", "start_line": 3, "end_line": 9,
                         "text": "def run():\n    return 1\n"}]}, "synced_at": 1.0}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    ol = exo.outline("a.py", root="/home/ipw-repo", target="host:whm-jump")
    assert ol["symbols"][0]["name"] == "run" and ol["source"] == "vault graph"
    rs = exo.read_symbol("a.py", "run", root="/home/ipw-repo", target="host:whm-jump")
    assert "def run()" in rs["rendered"] and rs["start_line"] == 3 and rs["source"] == "vault graph"
    slice_call = [c for c in cloud.calls if c[1] == "/v1/memory/code/slice"][-1]
    assert slice_call[3]["symbols"] == ["a.py::run"]


def test_a_server_call_is_recorded_with_its_full_path(tmp_path: Path):
    """The kernel finds a server's repo by the full path (resolve_path): a relative path plus its root."""
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo.record_call("read_symbol", {"path": "core/a.py", "name": "run", "root": "/home/ipw-repo", "target": "host:whm-jump"})
    exo.record_call("read_symbol", {"path": "core/a.py", "name": "run"})
    assert exo._exchange[0]["args"]["path"] == "/home/ipw-repo/core/a.py"
    assert exo._exchange[1]["args"]["path"] == "core/a.py"


def test_an_unavailable_answer_names_its_real_cause(tmp_path: Path, monkeypatch):
    """Live 2026-10-25: "no synced copy" hid what failed -- the repo WAS synced; the answer now says why."""
    import webbee.tools as wt

    async def fake_remote_sync(client, host, root, paths):
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())

    def boom(*a, **k):
        raise RuntimeError("the gateway timed out")
    monkeypatch.setattr(exo, "_vault", boom)
    out = exo.search_code("x", root="/home/ipw-repo", target="host:whm-jump")
    assert out["status"] == "unavailable" and "the gateway timed out" in out["content"]
    assert "no synced copy" not in out["content"]


def test_impact_shows_users_by_name(sample_workspace: Path):
    ans = {**_impact_answer(), "by_name_count": 1, "by_name": [{"path": "pkg/other.py", "line": 7, "user": "go", "name": "x"}]}
    exo = ExoskeletonRuntime(workspace=str(sample_workspace), client=_Cloud({"/code/impact": ans}))
    out = exo.impact_of_change(["compute_total"])
    assert out["by_name"] == [{"path": "pkg/other.py", "line": 7, "user": "go", "name": "x"}] and out["by_name_count"] == 1


# ── frame phase C Task 5: an exact text and a server's line range ──

def test_grep_code_on_a_server_and_locally(tmp_path: Path, monkeypatch):
    import webbee.tools as wt

    async def fake_remote_sync(client, host, root, paths):
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    cloud = _Cloud({"/v1/memory/code/grep": {"ok": True, "items": [{"path": "core/n.py", "line": 3, "text": "x"}],
                                             "total": 1, "truncated": False, "synced_at": 1.0}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    out = exo.grep_code("UNEXPECTED EFFECT", root="/home/ipw-repo", target="host:whm-jump")
    assert out["matches"] == [{"path": "core/n.py", "line": 3, "text": "x"}] and out["source"] == "vault graph"
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / "a.py").write_text("def f():\n    return f\"UNEXPECTED EFFECT: {1}\"\n")
    (repo / ".env").write_text("UNEXPECTED EFFECT=secret\n")
    loc = ExoskeletonRuntime(workspace=str(tmp_path)).grep_code("UNEXPECTED EFFECT", root="r")
    assert [(m["path"], m["line"]) for m in loc["matches"]] == [("a.py", 2)]
    bad = ExoskeletonRuntime(workspace=str(tmp_path)).grep_code(r"(a+)+$", root="r", regex=True)
    assert bad["status"] == "error" and "nested" in bad["error"]


def test_a_server_line_range_is_read_from_the_file_text(tmp_path: Path, monkeypatch):
    import webbee.tools as wt

    async def fake_remote_sync(client, host, root, paths):
        return {"repo_key": "rk_remote"}
    monkeypatch.setattr(wt, "remote_sync", fake_remote_sync)
    text = "".join(f"line {i}\n" for i in range(1, 21))
    cloud = _Cloud({"/v1/memory/code/file": {"ok": True, "path": "a.py", "total_lines": 20, "text": text}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    out = exo.read_symbol("a.py", "L5-7", root="/home/ipw-repo", target="host:whm-jump")
    assert out["status"] == "ok" and out["start_line"] == 5 and out["end_line"] == 7
    assert "line 5\nline 6\nline 7" in out["rendered"] and "line 8" not in out["rendered"]


def test_local_grep_never_follows_a_link_out_of_the_repo(tmp_path: Path):
    import os
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET_TOKEN = 'leak'\n")
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / "a.py").write_text("x = 1\n")
    os.symlink(outside, repo / "leak.py")
    out = ExoskeletonRuntime(workspace=str(tmp_path)).grep_code("SECRET_TOKEN", root="r")
    assert out["matches"] == []


def test_a_server_grep_is_literal_only(tmp_path: Path):
    out = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud()).grep_code("a.*b", root="/r", target="host:h",
                                                                                 regex=True)
    assert out["status"] == "error" and "exact text" in out["error"]


# ── 2026-10-25 MCP audit: a server's copy is checked against its HEAD; an unknown host or a missing folder says so ──

def _head(commit="", why=""):
    async def head(host, root):
        return {"commit": commit, "branch": "master", "root": root, "why": why}
    return head


def test_a_copy_behind_the_servers_head_is_synced_before_the_answer(tmp_path: Path, monkeypatch):
    import webbee.tools as wt
    cat = {"repos": [{"repo_key": "rk", "root_path": "/home/ipw-repo", "machine_label": "whm-jump",
                      "git_ref": "711e5630aaaa"}]}
    cloud = _Cloud({"/v1/memory/code/repos": cat})
    calls = []

    async def sync(client, host, root, paths):
        calls.append(host)
        cat["repos"][0]["git_ref"] = "fd751713bbbb"
        return {"repo_key": "rk"}
    monkeypatch.setattr(wt, "remote_sync", sync)
    monkeypatch.setattr(wt, "remote_head", _head("fd751713bbbb"))
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    assert exo._repo_key("/home/ipw-repo", "host:whm-jump") == "rk" and calls == ["whm-jump"]
    assert exo._fresh == {"server": "host:whm-jump", "server_head": "fd751713bbbb", "copy_commit": "fd751713bbbb"}


def test_a_copy_that_stays_behind_is_named_stale_with_the_reason(tmp_path: Path, monkeypatch):
    import webbee.tools as wt
    cloud = _Cloud({"/v1/memory/code/repos": {"repos": [{"repo_key": "rk", "root_path": "/r", "machine_label": "h",
                                                          "git_ref": "aaaaaaa1"}]}})

    async def sync(client, host, root, paths):
        raise OSError("sftp broke")
    monkeypatch.setattr(wt, "remote_sync", sync)
    monkeypatch.setattr(wt, "remote_head", _head("bbbbbbb2"))
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    assert exo._repo_key("/r", "host:h") == "rk"
    assert "the copy is at aaaaaaa1, the server at bbbbbbb2" in exo._fresh["stale"] and "sftp broke" in exo._fresh["stale"]
    assert exo._vault_meta({"repo_key": "rk"})["freshness"]["stale"] == exo._fresh["stale"]


def test_an_unknown_host_never_borrows_another_machines_copy(tmp_path: Path, monkeypatch):
    import webbee.tools as wt
    cloud = _Cloud({"/v1/memory/code/repos": {"repos": [{"repo_key": "rk", "root_path": "/home/ipw-repo",
                                                          "machine_label": "whm-jump"}]}})
    monkeypatch.setattr(wt, "remote_head", _head(why="no-such-host: OSError: Name or service not known"))
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    assert exo._repo_key("/home/ipw-repo", "host:no-such-host") == ""
    assert "Name or service not known" in exo._last_miss


def test_a_sync_that_never_ends_is_bounded(tmp_path: Path, monkeypatch):
    import threading
    import webbee.tools as wt
    from imperal_mcp import exoskeleton as ex
    gate = threading.Event()

    async def endless(client, host, root, paths):
        gate.wait(5)
        return {"repo_key": "late"}
    monkeypatch.setattr(wt, "remote_sync", endless)
    monkeypatch.setattr(ex, "_HOST_SYNC_WAIT_S", 0.2)
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    assert exo._repo_key("/nope", "host:h") == ""
    assert "did not finish in 0 s" in exo._last_miss
    gate.set()


def test_a_regex_looking_exact_search_without_hits_says_so(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "a.py").write_text("def alpha():\n    pass\ndef beta():\n    pass\n")
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    out = exo.grep_code("def alpha|def beta")
    assert out["total"] == 0 and "EXACT text" in out["note"]
    assert exo.grep_code("def alpha|def beta", regex=True)["total"] == 2


def test_a_folder_inside_a_repository_narrows_the_search(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n")
    (tmp_path / "b.py").write_text("needle = 2\n")
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    out = exo.grep_code("needle", root=str(tmp_path / "src"))
    assert [m["path"] for m in out["matches"]] == ["src/a.py"]


def test_a_servers_repo_takes_literal_alternatives(tmp_path: Path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    asked = []

    def ask(method, path, root, target, params=None, body=None):
        asked.append(params["q"])
        return {"items": [{"path": "k.py", "line": len(asked), "text": params["q"]}], "total": 1, "repo_key": "rk"}
    monkeypatch.setattr(exo, "_ask", ask)
    out = exo.grep_code("def a|def b", root="/r", target="host:h", regex=True)
    assert asked == ["def a", "def b"] and out["total"] == 2
    assert exo.grep_code("de.f", root="/r", target="host:h", regex=True)["status"] == "error"


def test_graph_slice_names_a_symbol_it_does_not_hold(tmp_path: Path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    monkeypatch.setattr(exo, "_ask", lambda *a, **k: {"data": {"items": []}, "repo_key": "rk"})
    out = exo.graph_slice(["no_such_symbol_xyz"], root="/r", target="host:h")
    assert out["not_found"] == ["no_such_symbol_xyz"] and "not a definition" in out["note"]


def test_impact_names_changed_together_files_apart(tmp_path: Path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    items = [{"id": "a.py", "title": "a.py", "via": "scope", "origin": "binding"},
             {"id": "b.py", "title": "b.py", "via": "measured", "origin": "changed together", "confidence": 0.2}]
    monkeypatch.setattr(exo, "_ask", lambda *a, **k: {"data": {"items": items}, "repo_key": "rk"})
    out = exo.impact_of_change(["f"], root="/r", target="host:h")
    assert out["dependent_files"] == ["a.py"] and out["changed_together"] == ["b.py (0.2)"]


def test_get_app_names_its_callable_tools_never_a_skeleton_entry():
    import json as _j
    from imperal_mcp.exoskeleton import app_summary
    app = {"app_id": "web-search", "display_name": "Web Search", "manifest_json": _j.dumps({"version": "1.1.0", "tools": [
        {"name": "skeleton_refresh_web_search", "description": "status"},
        {"name": "web_search", "action_type": "read", "description": "WEB SEARCH -- find pages " * 30}]})}
    got = app_summary(app)
    assert [t["name"] for t in got["tools"]] == ["web_search"] and got["tools"][0]["action_type"] == "read"
    assert got["version"] == "1.1.0" and len(got["tools"][0]["about"]) <= 241 and "manifest_json" not in got


# ── MCP audit 2 (after 0.8.4): the reason stays, freshness is the call's own, second-depth users are real ──

def test_an_unknown_hosts_reason_reaches_the_answer(tmp_path: Path, monkeypatch):
    import webbee.tools as wt
    monkeypatch.setattr(wt, "remote_head", _head(why="no-such-host: OSError: Name or service not known"))
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud({"/v1/memory/code/repos": {"repos": []}}))
    out = exo.grep_code("x", root="/home/ipw-repo", target="host:no-such-host")
    assert out["status"] == "unavailable" and "Name or service not known" in out["content"]


def test_freshness_belongs_to_the_call_that_asked(tmp_path: Path):
    import threading
    exo = ExoskeletonRuntime(workspace=str(tmp_path))
    exo._fresh = {"server": "host:whm-jump", "server_head": "abc"}
    seen = {}

    def other():
        seen["fresh"], seen["miss"] = exo._fresh, exo._last_miss
    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert seen == {"fresh": {}, "miss": ""} and exo._fresh["server_head"] == "abc"


def test_a_second_depth_user_counts_only_through_a_real_first_depth_user(tmp_path: Path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud())
    items = [{"id": "a.py", "title": "a.py", "via": "scope", "depth": 1, "targets": ["x.py::f"]},
             {"id": "t_a.py", "title": "t_a.py", "via": "scope", "depth": 2, "uses": "a.py", "targets": ["a.py::g"]},
             {"id": "c.py", "title": "c.py", "via": "measured", "origin": "changed together", "depth": 1},
             {"id": "t_c.py", "title": "t_c.py", "via": "scope", "depth": 2, "uses": "C", "targets": ["c.py::C"]}]
    monkeypatch.setattr(exo, "_ask", lambda *a, **k: {"data": {"items": items}, "repo_key": "rk"})
    out = exo.impact_of_change(["f"], root="/r", target="host:h")
    assert out["dependent_files"] == ["a.py", "t_a.py"] and out["changed_together"] == ["c.py (0.0)"]


def test_the_only_copy_of_a_path_answers_for_a_host_named_otherwise(tmp_path: Path, monkeypatch):
    """Live 2026-10-25: the gateway's repo is catalogued as "imperal-gateway", asked as host:10.88.0.1 -- one copy of
    the path on a host that exists answers (marked); a host that does not exist still never borrows."""
    import webbee.tools as wt
    cat = {"repos": [{"repo_key": "rk_gw", "root_path": "/opt/imperal-auth-gateway", "machine_label": "imperal-gateway",
                      "git_ref": "fd6d2efac60c"}]}
    monkeypatch.setattr(wt, "remote_head", _head(why="10.88.0.1: TimeoutError: "))
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud({"/v1/memory/code/repos": cat}))
    assert exo._repo_key("/opt/imperal-auth-gateway", "host:10.88.0.1") == "rk_gw"
    assert exo._fresh["copy_of_machine"] == "imperal-gateway" and "could not be asked" in exo._fresh["stale"]
    monkeypatch.setattr(wt, "remote_head", _head(why="nope: OSError: Name or service not known"))
    exo2 = ExoskeletonRuntime(workspace=str(tmp_path), client=_Cloud({"/v1/memory/code/repos": cat}))
    assert exo2._repo_key("/opt/imperal-auth-gateway", "host:nope") == ""
