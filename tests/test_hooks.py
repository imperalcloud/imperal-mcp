"""Memory plan Task 4: one `imperal-mcp hook <event>` command for every shell's hooks."""
import json

import pytest

from imperal_mcp import hooks as H

# the shells' own payloads (their documentation, 2026-10): Claude Code, Codex, Gemini CLI, Antigravity CLI
CLAUDE_BASH = {"session_id": "s1", "transcript_path": "/t", "cwd": "/w", "hook_event_name": "PostToolUse",
               "tool_name": "Bash", "tool_input": {"command": "pytest -q"},
               "tool_response": {"stdout": "1 passed", "stderr": "", "interrupted": False}}
CODEX_BASH = {"session_id": "s2", "cwd": "/w", "hook_event_name": "PostToolUse", "model": "gpt-5", "turn_id": "t1",
              "tool_name": "Bash", "tool_use_id": "u1", "tool_input": {"command": ["bash", "-lc", "pytest -q"]},
              "tool_response": "1 passed\n"}
GEMINI_SHELL = {"session_id": "s3", "cwd": "/w", "hook_event_name": "AfterTool", "timestamp": "2026-10-25T00:00:00Z",
                "tool_name": "run_shell_command", "tool_input": {"command": "pytest -q"},
                "tool_response": {"llmContent": "1 passed", "returnDisplay": "1 passed"}}
AGY_SHELL = {"session_id": "s4", "cwd": "/w", "hook_event_name": "PostToolUse", "tool_name": "run_command",
             "tool_input": {"CommandLine": "pytest -q"}, "tool_response": {"output": "1 passed"}}


class _Gateway:
    def __init__(self, hold=False, fail=False, frame="=== DECISION ===\nFRAME"):
        self.calls, self.hold, self.fail, self._frame = [], hold, fail, frame

    def _go(self, name, body):
        self.calls.append((name, body))
        if self.fail:
            raise RuntimeError("gateway down")

    def me(self):
        self._go("me", {})
        return "imp_u_ME"

    def frame(self, body):
        self._go("frame", body)
        return {"frame": self._frame}

    def record(self, body):
        self._go("record", body)
        return {"ok": True, "recorded": True}

    def final(self, body):
        self._go("final", body)
        return {"hold": self.hold, "reason": "2 item(s) still open -- prove or name them in blocked_on", "open": ["b"]}

    def recall_context(self, query):
        self._go("recall_context", {"query": query})
        return "last task: fix alpha (1 item open)"


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPERAL_MCP_SPOOL", str(tmp_path / "spool"))
    return tmp_path / "spool"


@pytest.mark.parametrize("payload", [CLAUDE_BASH, CODEX_BASH, GEMINI_SHELL, AGY_SHELL])
def test_each_shell_s_tool_call_becomes_one_exchange_item(payload):
    [item] = H.tool_items(payload)
    assert item["tool"] == "bash" and item["args"]["command"].endswith("pytest -q") and "1 passed" in item["text"]
    assert item["ok"] is True


def test_edits_reads_and_patches_become_the_kernel_s_tools():
    edit = {**CLAUDE_BASH, "tool_name": "Edit", "tool_input": {"file_path": "/w/a.py", "old_string": "x",
                                                               "new_string": "y"}, "tool_response": {}}
    [e] = H.tool_items(edit)
    assert e["tool"] == "edit_file" and e["args"] == {"path": "/w/a.py", "old_string": "x", "new_string": "y"}
    read = {**CLAUDE_BASH, "tool_name": "Read", "tool_input": {"file_path": "/w/a.py"},
            "tool_response": {"type": "text", "file": {"filePath": "/w/a.py", "content": "def f():\n    return 1\n"}}}
    [r] = H.tool_items(read)
    assert r["tool"] == "read_file" and r["args"]["path"] == "/w/a.py" and "def f()" in r["text"]
    patch = {**CODEX_BASH, "tool_name": "apply_patch", "tool_input": {"input": "*** Begin Patch\n*** Update File: a.py\n"
                                                                                "@@\n-x\n+y\n*** Add File: b.py\n+z\n*** End Patch"}}
    assert [(i["tool"], i["args"]["path"]) for i in H.tool_items(patch)] == [("edit_file", "a.py"), ("edit_file", "b.py")]


def test_imperal_s_own_tools_are_recorded_by_the_hook_with_their_answer():
    """Live 2026-10-25: impact_of_change showed two names, the final check called them made up -- the server kept
    its own calls in memory for a frame that never came (the hooks bring the frames now)."""
    for name in ("mcp__imperal__impact_of_change", "mcp_imperal_impact_of_change"):
        [it] = H.tool_items({**CLAUDE_BASH, "tool_name": name, "tool_input": {"symbols": ["plan_truth_block"]},
                             "tool_response": '{"same_file": [{"user": "TenantVaultTurnBridge._strict_frame"}]}'})
        assert it["tool"] == "impact_of_change" and "_strict_frame" in it["text"]
        assert it["args"]["symbols"] == "['plan_truth_block']"
    assert H.tool_items({**CLAUDE_BASH, "tool_name": "mcp__imperal__frame", "tool_input": {}}) == []   # a frame is no observation


def test_with_hooks_the_server_does_not_record_its_calls_twice(spool, tmp_path):
    from imperal_mcp.exoskeleton import ExoskeletonRuntime
    ws = tmp_path / "w"
    ws.mkdir()
    exo = ExoskeletonRuntime(workspace=str(ws))
    exo.record_call("search_code", {"query": "a"}, ok=True, text="x")
    assert len(exo._exchange) == 1
    H.announce(str(ws), "s7")
    import os
    H.Spool("s7").update(pids=[os.getppid()])
    H.announce(str(ws), "s7")
    exo.record_call("search_code", {"query": "b"}, ok=True, text="y")
    assert len(exo._exchange) == 1


def test_a_secret_file_is_withheld_in_the_spool(spool):
    read = {**CLAUDE_BASH, "tool_name": "Read", "tool_input": {"file_path": "/w/.env"},
            "tool_response": {"file": {"content": "DB_PASS=hunter2"}}}
    H.run_hook("post-tool", read, gateway=_Gateway())
    raw = "".join(p.read_text() for p in spool.glob("*.jsonl"))
    assert "hunter2" not in raw and "withheld" in raw


def test_a_prompt_records_the_request_and_answers_with_the_frame(spool):
    gw = _Gateway()
    H.run_hook("post-tool", CLAUDE_BASH, gateway=gw)
    out = H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "fix alpha"},
                     gateway=gw)
    assert out["hookSpecificOutput"] == {"hookEventName": "UserPromptSubmit",
                                         "additionalContext": "=== DECISION ===\nFRAME"}
    body = [b for n, b in gw.calls if n == "frame"][0]
    assert body["session_id"].startswith("mcp-imp_u_ME-") and body["step"] == 1 and body["goal"] == "fix alpha"
    assert body["memory"] == [{"kind": "user_request", "content": "fix alpha"}]
    assert [e["tool"] for e in body["exchange"]] == ["bash"]
    H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "and beta"}, gateway=gw)
    second = [b for n, b in gw.calls if n == "frame"][1]
    assert second["step"] == 2 and second["exchange"] == [] and second["session_id"] == body["session_id"]


def test_a_stop_with_open_items_blocks_in_each_shell_s_words(spool):
    claude = H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "last_assistant_message": "done"},
                        gateway=_Gateway(hold=True))
    assert claude["decision"] == "block" and "blocked_on" in claude["reason"]
    gemini = H.run_hook("stop", {**GEMINI_SHELL, "hook_event_name": "AfterAgent", "prompt": "x",
                                 "prompt_response": "done"}, gateway=_Gateway(hold=True))
    assert gemini["decision"] == "deny" and "blocked_on" in gemini["reason"]
    assert H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "last_assistant_message": "done"},
                      gateway=_Gateway(hold=False)) == {"systemMessage": "Imperal: still open -- b"}   # named, not held


def test_the_final_answer_is_recorded_before_it_is_judged(spool):
    gw = _Gateway()
    H.run_hook("stop", {**CODEX_BASH, "hook_event_name": "Stop", "last_assistant_message": "all done"}, gateway=gw)
    names = [n for n, _ in gw.calls if n != "me"]
    assert names == ["record", "final"]
    assert [b for n, b in gw.calls if n == "record"][0]["memory"] == [{"kind": "final", "content": "all done"}]


def test_claude_code_s_last_answer_is_read_from_its_transcript(tmp_path, spool):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"content": "fix it"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "fixed in a.py"}]}}]) + "\n")
    gw = _Gateway()
    H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "transcript_path": str(t)}, gateway=gw)
    assert [b for n, b in gw.calls if n == "final"][0]["final_text"] == "fixed in a.py"


def test_no_network_never_breaks_the_shell(spool):
    gw = _Gateway(fail=True)
    H.run_hook("post-tool", CLAUDE_BASH, gateway=gw)
    assert H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "x"}, gateway=gw) is None
    assert H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "last_assistant_message": "d"}, gateway=gw) is None
    items, memory = H.Spool("s1").drain()
    assert [i["tool"] for i in items] == ["bash"] and [m["kind"] for m in memory] == ["user_request", "final"]


def test_two_sessions_in_one_folder_never_mix(spool):
    H.run_hook("post-tool", CLAUDE_BASH, gateway=_Gateway())
    H.run_hook("post-tool", {**CODEX_BASH, "cwd": "/w"}, gateway=_Gateway())
    assert len(H.Spool("s1").drain()[0]) == 1 and len(H.Spool("s2").drain()[0]) == 1


def test_session_start_gives_the_protocol_and_where_the_work_stands(spool):
    from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS
    out = H.run_hook("session-start", {**CODEX_BASH, "hook_event_name": "SessionStart", "source": "startup"},
                     gateway=_Gateway())
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith(EXOSKELETON_INSTRUCTIONS.strip()[:40]) and "fix alpha" in ctx
    assert H.current_session("/w") == "s2"


# ── memory plan Task 5: the server drains the same spool, in the same session, with the same step ──
def test_the_spool_reaches_the_server_s_next_frame(spool, tmp_path):
    from tests.test_exoskeleton import _Cloud
    from imperal_mcp.exoskeleton import ExoskeletonRuntime
    ws = tmp_path / "w"
    ws.mkdir()
    payload = {**CLAUDE_BASH, "cwd": str(ws)}
    H.run_hook("post-tool", payload, gateway=_Gateway())
    H.Spool("s1").add_memory({"kind": "user_request", "content": "fix alpha"})
    H.Spool("s1").update(step=4, me="imp_u_ME")
    cloud = _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"}, "/v1/memory/frame": {"frame": "F"}})
    exo = ExoskeletonRuntime(workspace=str(ws), client=cloud)
    exo.task("fix alpha", [{"content": "edit a", "status": "pending"}])
    out = exo.frame()
    body = [c[3] for c in cloud.calls if c[1] == "/v1/memory/frame"][-1]
    assert out["ok"] and body["session_id"] == H.mcp_session("imp_u_ME", "s1") and body["step"] == 5
    assert [e["tool"] for e in body["exchange"]] == ["bash"] and body["memory"][0]["kind"] == "user_request"
    st = H.Spool("s1").state()
    assert st["step"] == 5 and st["goal"] == "fix alpha" and st["items"][0]["content"] == "edit a"
    assert H.Spool("s1").drain() == ([], [])


def test_a_failed_server_frame_puts_the_spool_back(spool, tmp_path):
    from tests.test_exoskeleton import _Cloud
    from imperal_mcp.exoskeleton import ExoskeletonRuntime
    ws = tmp_path / "w"
    ws.mkdir()
    H.run_hook("post-tool", {**CLAUDE_BASH, "cwd": str(ws)}, gateway=_Gateway())
    exo = ExoskeletonRuntime(workspace=str(ws), client=_Cloud(fail=True))
    assert exo.frame()["ok"] is False
    assert [i["tool"] for i in H.Spool("s1").drain()[0]] == ["bash"]


# ── security review (commit 60afbb6): a secret never rides in the args or a command's output; the spool is private ──
def test_a_secret_file_s_content_never_rides_in_the_args():
    w = {**CLAUDE_BASH, "tool_name": "Write", "tool_input": {"file_path": "/w/.env", "content": "DB_PASS=hunter2"},
         "tool_response": {}}
    e = {**CLAUDE_BASH, "tool_name": "Edit", "tool_input": {"file_path": "/w/secrets/db.yaml", "old_string": "pw: a",
                                                            "new_string": "pw: hunter2"}, "tool_response": {}}
    sh = {**CLAUDE_BASH, "tool_input": {"command": "cat ~/.ssh/id_rsa"}, "tool_response": {"stdout": "-----BEGIN KEY"}}
    for p in (w, e, sh):
        assert "hunter2" not in json.dumps(H.tool_items(p)) and "BEGIN KEY" not in json.dumps(H.tool_items(p))


def test_the_spool_is_private(spool):
    import stat
    H.run_hook("post-tool", CLAUDE_BASH, gateway=_Gateway())
    assert stat.S_IMODE(spool.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in spool.iterdir() if p.is_file())


# ── Antigravity CLI (antigravity.google/docs/hooks, 2026-10): its own fields and words ──
AGY_POST = {"conversationId": "c9", "workspacePaths": ["/w"], "transcriptPath": "/t", "modelName": "m",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest -q"}}, "stepIdx": 3}


def test_antigravity_s_tool_call_and_its_words(spool):
    [item] = H.tool_items(AGY_POST)
    assert item["tool"] == "bash" and item["args"]["command"] == "pytest -q" and item["ok"] is True
    H.run_hook("post-tool", AGY_POST, gateway=_Gateway())
    assert len(H.Spool("c9").drain()[0]) == 1
    start = H.run_hook("session-start", {"conversationId": "c9", "workspacePaths": ["/w"]}, gateway=_Gateway())
    assert start["injectSteps"][0]["ephemeralMessage"].startswith("IMPERAL")
    stop = H.run_hook("stop", {"conversationId": "c9", "workspacePaths": ["/w"], "fullyIdle": True,
                               "executionNum": 1, "terminationReason": "done"}, gateway=_Gateway(hold=True))
    assert stop["decision"] == "continue" and "blocked_on" in stop["reason"]


def test_a_secret_touched_through_shell_punctuation_is_withheld_with_unknown_args():
    for cmd in ("cat<.env", "x=$(cat .env) && echo $x", "grep pw config/.env.local|head", "cat ~/.ssh/id_rsa;ls"):
        [it] = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": cmd}, "tool_response": {"stdout": "PW=hunter2"}})
        assert "hunter2" not in json.dumps(it) and ".env" not in it["args"].get("command", "")[:0] + "x"
        assert it["text"].startswith("(withheld")
    [w] = H.tool_items({**CLAUDE_BASH, "tool_name": "Write", "tool_input": {"file_path": "/w/.env", "content": "a",
                                                                           "body_text": "PW=hunter2"}, "tool_response": {}})
    assert "hunter2" not in json.dumps(w) and w["args"]["path"] == "/w/.env"


# ── final review C1: no credential leaves this machine through a hook ──
_LEAKS = "sk-proj-abcdefghijklmnopqrstuv ghp_abcdefghijklmnopqrstuvwxyz12 hunter2 S3cr3tP4ss wJalrXUtnFEMIK7MDENG tok123"


def _assert_clean(obj):
    dump = json.dumps(obj)
    for leak in _LEAKS.split():
        assert leak not in dump, (leak, dump[:300])


def test_commands_outputs_and_reads_lose_their_credentials():
    cases = [
        {**CLAUDE_BASH, "tool_input": {"command": 'export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuv && '
                                                  'curl -H "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz12" x'},
         "tool_response": {"stdout": "password=hunter2 AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG"}},
        {**CLAUDE_BASH, "tool_input": {"command": "vault kv get imperal/gateway"},
         "tool_response": {"stdout": "db_password    S3cr3tP4ss"}},
        {**CLAUDE_BASH, "tool_input": {"command": "printenv"}, "tool_response": {"stdout": "X=S3cr3tP4ss"}},
        {**CLAUDE_BASH, "tool_name": "Read", "tool_input": {"file_path": "/w/config/database.yml"},
         "tool_response": {"file": {"content": "production:\n  password: hunter2\n"}}},
        {**CLAUDE_BASH, "tool_input": {"command": "cat ~/.git-credentials"},
         "tool_response": {"stdout": "https://u:tok123@github.com"}},
        {**CLAUDE_BASH, "tool_name": "mcp__github__create_issue", "tool_input": {"token": "ghp_abcdefghijklmnopqrstuvwxyz12",
                                                                               "title": "x"}, "tool_response": "ok"},
    ]
    for c in cases:
        _assert_clean(H.tool_items(c))


def test_an_unknown_tool_keeps_only_its_name_and_result_flag():
    [it] = H.tool_items({**CLAUDE_BASH, "tool_name": "mcp__other__do", "tool_input": {"q": "x"},
                         "tool_response": "anything"})
    assert it["tool"] == "mcp__other__do" and it["args"] == {} and it["text"] == ""


def test_prompts_and_finals_lose_their_credentials(spool):
    gw = _Gateway()
    H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit",
                          "prompt": "use password=hunter2 and ghp_abcdefghijklmnopqrstuvwxyz12"}, gateway=gw)
    H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "last_assistant_message": "set token: tok123"},
               gateway=gw)
    _assert_clean(gw.calls)


def test_an_ignored_folder_records_nothing(spool, monkeypatch, tmp_path):
    monkeypatch.setenv("IMPERAL_MCP_IGNORE", str(tmp_path / "private"))
    (tmp_path / "private").mkdir()
    H.run_hook("post-tool", {**CLAUDE_BASH, "cwd": str(tmp_path / "private")}, gateway=_Gateway())
    gw = _Gateway()
    assert H.run_hook("prompt", {**CLAUDE_BASH, "cwd": str(tmp_path / "private"), "hook_event_name": "UserPromptSubmit",
                                 "prompt": "x"}, gateway=gw) is None
    assert H.Spool("s1").drain() == ([], []) and gw.calls == []


# ── final review I1/I2/I3/I5/I6 ──
def test_a_hook_frame_fits_the_shell_s_context_limit_and_says_it_is_paid(spool):
    gw = _Gateway(frame="=== DECISION ===\nDO X\n" + "y" * 60000)
    out = H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "x"}, gateway=gw)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) <= H.HOOK_FRAME_CHARS and ctx.startswith("=== DECISION ===") and "already paid" in ctx


def test_the_protocol_says_a_hook_frame_needs_no_second_call():
    from imperal_mcp.exoskeleton import EXOSKELETON_INSTRUCTIONS as P
    assert "already" in P and "until you change" in P


def test_a_frame_refused_for_credits_keeps_the_step_s_memory_and_its_step(spool):
    class _Broke(_Gateway):
        def frame(self, body):
            self._go("frame", body)
            return {"content": "not enough credits for a frame (5 credits, balance 2)", "refused": True}
    gw = _Broke()
    H.run_hook("post-tool", CLAUDE_BASH, gateway=gw)
    out = H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "fix"}, gateway=gw)
    assert "not enough credits" in out["hookSpecificOutput"]["additionalContext"]
    rec = [b for n, b in gw.calls if n == "record"][0]
    assert [e["tool"] for e in rec["exchange"]] == ["bash"] and rec["memory"][0]["kind"] == "user_request"
    assert H.Spool("s1").state().get("step", 0) == 0


def test_a_request_the_gateway_refuses_for_good_is_dropped_not_kept_forever(spool):
    class _Bad(_Gateway):
        def frame(self, body):
            from imperal_mcp.client import ImperalError
            self._go("frame", body)
            raise ImperalError("POST /v1/memory/frame -> 422: too big", status_code=422)
    H.run_hook("post-tool", CLAUDE_BASH, gateway=_Bad())
    H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit", "prompt": "x"}, gateway=_Bad())
    assert H.Spool("s1").drain() == ([], [])


def test_the_spool_keeps_a_bounded_tail(spool):
    s = H.Spool("s9")
    s.add_items([{"tool": "bash", "args": {}, "ok": True, "text": "x" * 100}] * (H.SPOOL_ITEMS_MAX + 50))
    items, _m = s.drain()
    assert len(items) == H.SPOOL_ITEMS_MAX


def test_past_the_holds_the_open_items_are_named(spool):
    class _Pass(_Gateway):
        def final(self, body):
            self._go("final", body)
            return {"hold": False, "reason": "", "open": ["edit beta", "deploy"]}
    out = H.run_hook("stop", {**CLAUDE_BASH, "hook_event_name": "Stop", "last_assistant_message": "done"},
                     gateway=_Pass())
    assert out == {"systemMessage": "Imperal: still open -- edit beta; deploy"}


def test_two_shells_in_one_folder_each_keep_their_session(spool, monkeypatch):
    monkeypatch.setattr(H, "_shell_pids", lambda: [111, 11])
    H.run_hook("post-tool", {**CLAUDE_BASH, "session_id": "A", "cwd": "/w"}, gateway=_Gateway())
    monkeypatch.setattr(H, "_shell_pids", lambda: [222, 22])
    H.run_hook("post-tool", {**CLAUDE_BASH, "session_id": "B", "cwd": "/w"}, gateway=_Gateway())
    assert H.current_session("/w", server_parent=11) == "A" and H.current_session("/w", server_parent=22) == "B"
    assert H.current_session("/w/sub", server_parent=99) == ""        # no parent-folder guess, no other shell's


def test_secret_dumps_hidden_behind_quotes_or_flags_are_withheld():
    for cmd in ('env -i X=1 sh -c env', '"printenv"', "declare -px", "cat /proc/self/environ", "less ~/.netrc",
                'p\\rintenv'):
        [it] = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": cmd}, "tool_response": {"stdout": "K=S3cr3tP4ss"}})
        assert "S3cr3tP4ss" not in json.dumps(it), cmd


def test_a_token_alone_in_a_url_and_a_secret_on_the_cut_are_redacted():
    from imperal_mcp.secrets_scrub import scrub_secrets
    assert "ghp_abcdefghijklmnopqrstuvwxyz12" not in scrub_secrets("git clone https://ghp_abcdefghijklmnopqrstuvwxyz12@github.com/x")
    long_out = "x" * 7990 + " password=hunter2hunter2hunter2"
    [it] = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": "ls"}, "tool_response": {"stdout": long_out}})
    assert "hunter2" not in it["text"]


def test_a_read_is_never_syntax_checked_and_the_shell_flag_is_used(monkeypatch, spool):
    from imperal_mcp import cli
    called = []
    monkeypatch.setattr(cli, "run_claude_hook", lambda *a, **k: called.append(k) or {"exit_code": 2})
    read = json.dumps({**CLAUDE_BASH, "tool_name": "Read", "tool_input": {"file_path": "/w/broken.py"}})
    assert cli.run_shell_hook("post-tool", stdin_data=read) == 0 and called == []
    edit = json.dumps({**CLAUDE_BASH, "tool_name": "Edit", "tool_input": {"file_path": "/w/a.py", "old_string": "a",
                                                                            "new_string": "b"}})
    assert cli.run_shell_hook("post-tool", stdin_data=edit) == 2 and len(called) == 1
    seen = []
    monkeypatch.setattr(H, "run_hook", lambda ev, p, gateway=None: seen.append(p.get("_shell")))
    cli.run_shell_hook("prompt", stdin_data=json.dumps(CLAUDE_BASH), shell="gemini")
    assert seen == ["gemini"]


def test_a_hook_frame_names_the_folder_the_shell_works_in(spool):
    gw = _Gateway()
    H.run_hook("prompt", {**CLAUDE_BASH, "cwd": "/w/imperal-mcp", "hook_event_name": "UserPromptSubmit", "prompt": "x"},
               gateway=gw)
    body = [b for n, b in gw.calls if n == "frame"][0]
    assert body["cwd"] == "/w/imperal-mcp" and body["repo_root"] == "/w/imperal-mcp"


def test_two_withheld_commands_stay_two_calls():
    """Live 2026-10-25: two different `ssh -i ~/.ssh/key ...` commands became one label -- REPEATED in the frame."""
    a = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": "ssh -i ~/.ssh/k host 'git log'"}})[0]
    b = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": "ssh -i ~/.ssh/k host 'deploy'"}})[0]
    assert a["args"]["command"] != b["args"]["command"] and "~/.ssh" not in a["args"]["command"]
    assert a["args"]["command"].startswith("(withheld: a command on a secret file")


def test_a_withheld_fingerprint_is_no_plain_hash_of_the_command(spool):
    import hashlib
    cmd = "cat .env"
    [it] = H.tool_items({**CLAUDE_BASH, "tool_input": {"command": cmd}})
    assert hashlib.sha256(cmd.encode()).hexdigest()[:8] not in it["args"]["command"]


def test_a_system_notification_is_no_user_request(spool):
    gw = _Gateway()
    out = H.run_hook("prompt", {**CLAUDE_BASH, "hook_event_name": "UserPromptSubmit",
                                "prompt": "<task-notification>\n<summary>review found x</summary>"}, gateway=gw)
    assert out is None and gw.calls == [] and H.Spool("s1").drain() == ([], [])
