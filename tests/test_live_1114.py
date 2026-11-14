"""Live findings of 2026-11-14 (imperal-mcp 0.9.16 in use), each held by a test."""
import subprocess

from imperal_mcp import hooks as H


class _Spool:
    def __init__(self):
        self.st = {}

    def state(self):
        return self.st

    def update(self, **kw):
        self.st.update(kw)


def test_a_head_measure_is_marked_as_the_hooks_own_not_the_agents_call(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    (repo / "a.txt").write_text("1")
    run("add", "-A")
    run("-c", "user.name=u", "-c", "user.email=u@x", "commit", "-qm", "first")
    got = H.head_items(_Spool(), str(tmp_path))
    assert len(got) == 1 and got[0]["measure"] is True and got[0]["tool"] == "bash"


def test_toolsearch_keeps_its_query_so_two_searches_are_two_calls():
    a = H.tool_items({"tool_name": "ToolSearch", "tool_input": {"query": "select:a", "max_results": 1},
                      "tool_response": "loaded"})
    b = H.tool_items({"tool_name": "ToolSearch", "tool_input": {"query": "select:b", "max_results": 1},
                      "tool_response": "loaded"})
    assert a[0]["args"] == {"query": "select:a"} and b[0]["args"] == {"query": "select:b"}
    assert a[0]["text"] == ""                       # never the answer of a tool the hooks do not know


def test_another_servers_tool_still_sends_nothing_but_its_name():
    got = H.tool_items({"tool_name": "mcp__other__thing", "tool_input": {"secret": "x"}, "tool_response": "y"})
    assert got == [{"app_id": "", "tool": "mcp__other__thing", "args": {}, "ok": True, "text": ""}]


def test_the_shells_cwd_line_is_not_the_commands_output():
    got = H.tool_items({"tool_name": "Bash", "tool_input": {"command": "cat >> f <<'EOF'\nx\nEOF"},
                        "tool_response": {"stdout": "Shell cwd was reset to /Users/u/w", "stderr": "", "exit_code": 0}})
    assert got[0]["text"] == ""
    got = H.tool_items({"tool_name": "Bash", "tool_input": {"command": "ls"},
                        "tool_response": {"stdout": "a\nb\nShell cwd was reset to /x\n", "exit_code": 0}})
    assert got[0]["text"] == "a\nb"


def test_each_call_carries_the_seconds_since_the_sessions_previous_event(monkeypatch):
    sp = _Spool()
    clock = iter([100.0, 103.5, 110.0])
    monkeypatch.setattr(H.time, "time", lambda: next(clock))
    assert "duration_s" not in H._timed(sp, [{"tool": "bash"}])[0]          # nothing before it: not measured
    got = H._timed(sp, [{"tool": "bash"}, {"tool": "grep"}])
    assert got[0]["duration_s"] == 3.5 and "duration_s" not in got[1]      # one gap, counted once
    assert H._timed(sp, [{"tool": "bash"}])[0]["duration_s"] == 6.5


def test_a_git_move_over_ssh_names_the_servers_repository():
    assert H.host_git_moves("ssh whm-jump 'cd /home/ipw-repo && git commit -qm x && git push'") == \
        [("whm-jump", "/home/ipw-repo")]
    assert H.host_git_moves("ssh -p 22 -o BatchMode=yes root@gw 'git -C /opt/gw/ pull -q'") == [("gw", "/opt/gw")]
    assert H.host_git_moves("ssh whm-jump 'cd /home/ipw-repo && git log --oneline -3; git status'") == []
    assert H.host_git_moves("git -C /home/ipw-repo commit -m x") == []          # no ssh: a local repository
    assert H.host_git_moves("ssh h 'echo \"unclosed") == []


def test_a_moved_server_repository_gets_one_detached_sync(monkeypatch):
    started = []

    class _P:
        def __init__(self, argv, **kw):
            started.append((argv[-3:], kw.get("start_new_session")))
    monkeypatch.setattr(subprocess, "Popen", _P)
    sp = _Spool()
    item = {"tool": "bash", "ok": True, "args": {"command": "ssh whm-jump 'cd /home/ipw-repo && git commit -m x'"}}
    assert H.sync_moved_hosts(sp, [item]) == 1
    assert started == [(["sync-host", "whm-jump", "/home/ipw-repo"], True)]
    assert H.sync_moved_hosts(sp, [item]) == 0                           # once per window
    assert H.sync_moved_hosts(_Spool(), [dict(item, ok=False)]) == 0     # a failed command moved nothing
