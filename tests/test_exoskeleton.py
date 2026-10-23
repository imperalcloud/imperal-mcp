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


def test_token_savings_tracker_records_and_summarizes():
    tracker = TokenSavingsTracker()
    rec = tracker.record(
        "outline",
        returned_chars=400,
        baseline_chars=4000,
        returned_lines=15,
        baseline_lines=150,
        baseline_files=1,
    )
    assert rec["tool"] == "outline"
    assert rec["baseline_basis"] == "matched_files_on_disk"
    assert rec["baseline_files"] == 1
    assert rec["returned_chars"] == 400
    assert rec["baseline_chars"] == 4000
    assert rec["saved_chars"] == 3600
    assert "saved_tokens_est" not in rec
    assert "estimated_cost_saved_usd" not in rec

    summary = tracker.summary()
    assert summary["baseline_basis"] == "matched_files_on_disk"
    assert summary["calls"] == 1
    assert summary["baseline_files"] == 1
    assert summary["saved_chars"] == 3600
    assert summary["saved_lines"] == 135
    assert "saved_tokens_est" not in summary
    assert "estimated_cost_saved_usd" not in summary
    assert summary["by_tool"]["outline"]["calls"] == 1
    assert summary["by_tool"]["outline"]["baseline_files"] == 1


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
    assert savings["baseline_basis"] == "matched_files_on_disk"
    assert savings["calls"] >= 7
    assert "saved_tokens_est" not in savings
    assert "estimated_cost_saved_usd" not in savings
    math_ops_size = len((sample_workspace / "pkg" / "math_ops.py").read_text(encoding="utf-8"))
    caller_size = len((sample_workspace / "pkg" / "caller.py").read_text(encoding="utf-8"))
    assert savings["by_tool"]["outline"]["baseline_chars"] == math_ops_size
    assert savings["by_tool"]["graph_slice"]["baseline_chars"] == math_ops_size + caller_size


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

    # CLI hook subcommand
    cli_main(["hook", "post-tool-use", "--workspace", str(sample_workspace)])
    cli_hook_out = json.loads(capsys.readouterr().out)
    assert cli_hook_out["status"] == "ok"
    assert cli_hook_out["event"] == "post-tool-use"


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




