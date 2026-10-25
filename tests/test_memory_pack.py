"""Live check 2026-10-25 (a fresh Claude Code session): what the hooks and the server must do so MCP memory works.

- a past conversation (Webbee's audit) could not be found from an MCP session: recall takes another conversation,
  search_history finds one;
- the Stop check called names "never seen" that were in a 14K Bash output (only 8000 chars reached the kernel) and
  in an `ssh -i ~/.ssh/<key> ...` run (the whole command was withheld as a secret-file read);
- an external session's vault project is the repo it started in (owner: "проект на репо"), pinned once.
"""
import subprocess
from pathlib import Path

import pytest

from imperal_mcp import hooks as H
from imperal_mcp.exoskeleton import ExoskeletonRuntime, exchange_item


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPERAL_MCP_SPOOL", str(tmp_path / "spool"))
    return tmp_path / "spool"


def test_a_long_bash_output_reaches_the_kernel_up_to_what_the_model_saw():
    out = "\n".join(f"line {i}" for i in range(1500)) + "\nexternal_final_activity is not idempotent"
    [it] = H.tool_items({"session_id": "s1", "cwd": "/w", "tool_name": "Bash", "tool_input": {"command": "tail -40 f"},
                         "tool_response": {"stdout": out, "stderr": ""}})
    assert len(out) < 20000 and "external_final_activity" in it["text"]


def test_an_ssh_key_given_to_ssh_is_used_not_read():
    cmd = "ssh -i ~/.ssh/whm-mcp-key -J whm-jump root@104.224.88.2 'cd /opt/x && ./deploy.sh status'"
    it = exchange_item("bash", {"command": cmd}, True, "commit b05e9b5 running")
    assert it["args"]["command"] == cmd and it["text"] == "commit b05e9b5 running"
    glued = exchange_item("bash", {"command": "ssh -i ~/.ssh/k h;cat ~/.ssh/k"}, True, "KEY")
    assert "withheld" in glued["text"]                     # a separator: no exemption at all (security review)
    scp = exchange_item("bash", {"command": "scp -i ~/.ssh/k -o IdentityFile=~/.ssh/k2 a.txt h:/tmp/"}, True, "ok")
    assert scp["text"] == "ok"
    sys_ssh = exchange_item("bash", {"command": "/usr/bin/ssh -i ~/.ssh/k h uptime"}, True, "up 3 days")
    assert sys_ssh["text"] == "up 3 days"


def test_a_secret_file_named_beside_the_key_is_still_withheld():
    for cmd in ("ssh -i ~/.ssh/k h cat ~/.ssh/authorized_keys", "cat ~/.ssh/id_rsa", "ssh h 'cat /srv/app/.env'",
                "sed -i s/a/b/ .env",
                # the key's own path outside its -i slot is a read of the key (security review)
                "ssh -i ~/.ssh/k h uptime; cat ~/.ssh/k", "ssh -i ~/.ssh/k h uptime && base64 ~/.ssh/k",
                "ssh -o IdentityFile=~/.ssh/k h 'cat ~/.ssh/k'",
                # the identity slot is ssh's own option area only -- never a word of the remote command
                "ssh h cat -i ~/.ssh/id_rsa", "ssh -J j h cat -i~/.ssh/id_rsa",
                # a newline, $( ), backticks: no exemption at all (security review)
                "ssh -i ~/.ssh/k h true\ncat ~/.ssh/k", "ssh -i ~/.ssh/k h \"$(cat ~/.ssh/k)\"",
                "ssh -i ~/.ssh/k h `cat ~/.ssh/k`",
                # shlex comments and unknown options never hide a read (security review)
                "ssh -i ~/.ssh/k h true #; cat ~/.ssh/k", "ssh -Z -i ~/.ssh/k h 'cat ~/.ssh/k'",
                "ssh -i -o h 'cat ~/.ssh/k'",
                # an escape, a look-alike program, a function or an alias give no exemption (security review)
                "ssh -i ~/.ssh/k h true; cat ~/.ssh/\\k", "./ssh -i ~/.ssh/k x", "ssh(){ cat \"$2\"; }; ssh -i ~/.ssh/k h",
                "alias ssh=cat; ssh -i ~/.ssh/k h", "function ssh { cat $2; }; ssh -i ~/.ssh/k h"):
        it = exchange_item("bash", {"command": cmd}, True, "SECRET=1")
        assert "SECRET" not in it["text"] and "withheld" in it["text"], cmd


def test_the_session_s_repo_is_its_git_work_tree_or_none(tmp_path):
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    key = H.session_repo(str(repo / "sub"))
    assert len(key) == 12 and key == H.session_repo(str(repo))
    assert H.session_repo(str(tmp_path)) == ""                     # a folder of repositories is no repository


def test_the_repo_is_pinned_once_and_sent_on_every_door(spool, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(H, "session_repo", lambda cwd: seen.append(cwd) or "ab12cd34ef56")

    class _Gw:
        calls = []

        def me(self):
            return "imp_u_ME"

        def frame(self, body):
            self.calls.append(("frame", body))
            return {"frame": "F"}

        def record(self, body):
            self.calls.append(("record", body))
            return {}

        def final(self, body):
            self.calls.append(("final", body))
            return {"hold": False, "open": []}
    gw = _Gw()
    base = {"session_id": "s9", "cwd": str(tmp_path), "transcript_path": ""}
    H.run_hook("prompt", {**base, "hook_event_name": "UserPromptSubmit", "prompt": "a"}, gateway=gw)
    H.run_hook("prompt", {**base, "cwd": "/elsewhere", "hook_event_name": "UserPromptSubmit", "prompt": "b"},
               gateway=gw)
    H.run_hook("stop", {**base, "hook_event_name": "Stop", "last_assistant_message": "done"}, gateway=gw)
    assert seen == [str(tmp_path)]                                   # pinned at the first prompt, never moved
    assert [b.get("session_repo") for _n, b in gw.calls] == ["ab12cd34ef56"] * len(gw.calls)


def test_recall_takes_another_conversation_and_search_history_finds_one(tmp_path: Path):
    from tests.test_exoskeleton import _Cloud
    cloud = _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"},
                    "/v1/memory/frame/lens": {"ok": True, "content": "hits"}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    exo.lens("recall", {"ref": "A12", "conversation": "marathon-imp_u_ME-rab-s1"})
    exo.lens("search_history", {"query": "audit"})
    bodies = [c[3] for c in cloud.calls if c[1] == "/v1/memory/frame/lens"]
    assert bodies[0]["args"] == {"ref": "A12", "conversation": "marathon-imp_u_ME-rab-s1"}
    assert bodies[1]["tool"] == "search_history" and bodies[1]["args"] == {"query": "audit"}
    assert all("session_repo" in b for b in bodies)


@pytest.mark.asyncio
async def test_the_server_offers_search_history_and_recall_of_a_conversation(tmp_path: Path):
    import inspect
    from imperal_mcp.server import build_server
    from tests.test_exoskeleton import MemoryFakeClient
    srv = build_server(MemoryFakeClient(), workspace=str(tmp_path))
    tools = srv._tool_manager._tools
    assert "search_history" in tools
    assert "conversation" in inspect.signature(tools["recall"].fn).parameters


def test_what_does_not_fit_one_request_waits_for_the_next(spool):
    """Review 2026-10-25: past one request's size the older calls were dropped for good."""
    sp = H.Spool("big")
    sp.add_items([{"tool": "bash", "args": {}, "ok": True, "text": "x" * 19000, "n": i} for i in range(40)])
    sent = []
    H._send(sp, lambda items, memory: sent.append(items))
    left, _mem = sp.drain()
    assert 0 < len(sent[0]) < 40 and len(sent[0]) + len(left) == 40
    assert [i["n"] for i in left] == list(range(40 - len(sent[0])))           # the older ones, in order


def test_a_final_names_its_step(spool, tmp_path, monkeypatch):
    monkeypatch.setattr(H, "session_repo", lambda cwd: "")

    class _Gw:
        calls = []

        def me(self):
            return "imp_u_ME"

        def record(self, body):
            return {}

        def final(self, body):
            self.calls.append(body)
            return {"hold": False, "open": []}
    gw = _Gw()
    H.Spool("s5").update(step=7)
    H.run_hook("stop", {"session_id": "s5", "cwd": str(tmp_path), "hook_event_name": "Stop",
                        "last_assistant_message": "Done."}, gateway=gw)
    assert gw.calls[0]["step"] == 7
