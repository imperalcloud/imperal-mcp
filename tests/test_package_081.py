"""Live 2026-10-25 after 0.8.0 (an MCP session's own report): a blocked item with its reason held the final three
times (the kernel met the plan only at the next frame), a tool's own name in an answer was called made up, a release
stamp went into the vault as "rel-<CARD>", and an install that lost its code extra failed task() without a word."""
from pathlib import Path

import pytest

from imperal_mcp import hooks as H
from imperal_mcp.exoskeleton import ExoskeletonRuntime


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("IMPERAL_MCP_SPOOL", str(tmp_path / "spool"))
    return tmp_path / "spool"


class _Gw:
    def __init__(self):
        self.calls = []

    def me(self):
        return "imp_u_ME"

    def record(self, body):
        self.calls.append(("record", body))
        return {}

    def final(self, body):
        self.calls.append(("final", body))
        return {"hold": False, "open": []}


def test_a_turn_s_record_carries_the_plan_and_the_final_the_tool_names(spool, tmp_path, monkeypatch):
    monkeypatch.setattr(H, "session_repo", lambda cwd: "")
    items = [{"content": "next package", "status": "blocked", "blocked_on": "waits for the user: yes"}]
    H.Spool("s1").update(step=3, goal="the package", items=items)
    gw = _Gw()
    H.run_hook("stop", {"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "Stop",
                        "last_assistant_message": "Done; the next waits for you."}, gateway=gw)
    rec = next(b for n, b in gw.calls if n == "record")
    fin = next(b for n, b in gw.calls if n == "final")
    assert rec["items"] == items and rec["goal"] == "the package"
    assert "search_history" in fin["tools"] and "task" in fin["tools"]


@pytest.mark.asyncio
async def test_the_tool_names_the_hooks_send_are_the_server_s(tmp_path: Path):
    from imperal_mcp.server import build_server
    from tests.test_exoskeleton import MemoryFakeClient
    srv = build_server(MemoryFakeClient(), workspace=str(tmp_path))
    assert set(H.MCP_TOOL_NAMES) == set(srv._tool_manager._tools)


def test_task_records_the_plan_at_once_with_the_calls_before_it(spool, tmp_path, monkeypatch):
    from tests.test_exoskeleton import _Cloud
    cloud = _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"}, "/v1/memory/frame/record": {"ok": True}})
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    monkeypatch.setattr(ExoskeletonRuntime, "_shell_session", staticmethod(lambda ws: "s2"))
    monkeypatch.setattr(H, "session_repo", lambda cwd: "")
    sp = H.Spool("s2")
    sp.update(step=4)
    sp.add_items([{"tool": "bash", "args": {"command": "./scripts/check.sh"}, "ok": True, "text": "passed"}])
    items = [{"content": "run (./scripts/check.sh)", "status": "completed"}]
    out = exo.task("g", items)
    assert out["ok"] and out["recorded"]
    [body] = [c[3] for c in cloud.calls if c[1] == "/v1/memory/frame/record"]
    assert body["items"] == items and body["goal"] == "g" and body["step"] == 4
    assert [e["args"]["command"] for e in body["exchange"]] == ["./scripts/check.sh"]   # the work it reports
    assert sp.drain() == ([], [])


def test_a_plan_that_cannot_be_recorded_loses_nothing(spool, tmp_path, monkeypatch):
    from tests.test_exoskeleton import _Cloud
    cloud = _Cloud({"/v1/auth/me": {"imperal_id": "imp_u_ME"}})            # the record path answers nothing
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=cloud)
    monkeypatch.setattr(ExoskeletonRuntime, "_shell_session", staticmethod(lambda ws: "s3"))
    monkeypatch.setattr(H, "session_repo", lambda cwd: "")

    def down(*a, **k):
        raise ConnectionError("gateway down")
    monkeypatch.setattr(exo, "_vault", lambda method, path, **k: {"imperal_id": "imp_u_ME"} if path == "/v1/auth/me"
                        else down())
    sp = H.Spool("s3")
    sp.add_items([{"tool": "bash", "args": {"command": "ls"}, "ok": True, "text": "a"}])
    out = exo.task("g", [{"content": "x", "status": "in_progress"}])
    assert out["ok"] and not out["recorded"]
    assert [i["args"]["command"] for i in sp.drain()[0]] == ["ls"]
    assert H.Spool("s3").state()["items"] == [{"content": "x", "status": "in_progress"}]


def test_task_stands_without_the_code_tools(spool, tmp_path, monkeypatch):
    exo = ExoskeletonRuntime(workspace=str(tmp_path), client=None)
    monkeypatch.setattr(ExoskeletonRuntime, "_shell_session", staticmethod(lambda ws: ""))

    def no_webbee(root):
        raise RuntimeError("Code intelligence tools require the optional 'webbee' dependency.")
    monkeypatch.setattr(exo, "_baseline", no_webbee)
    assert exo.task("g", [{"content": "x", "status": "pending"}])["ok"]


def test_the_session_start_says_when_the_code_tools_are_off(spool, tmp_path, monkeypatch):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "webbee" else real(name, *a))

    class _G:
        def recall_context(self, q):
            return ""
    out = H.run_hook("session-start", {"session_id": "s4", "cwd": str(tmp_path), "hook_event_name": "SessionStart"},
                     gateway=_G())
    assert "code tools are OFF" in out["hookSpecificOutput"]["additionalContext"]
    assert "imperal-mcp[code]" in out["systemMessage"]
    monkeypatch.setattr(importlib.util, "find_spec", real)
    ok = H.run_hook("session-start", {"session_id": "s4", "cwd": str(tmp_path), "hook_event_name": "SessionStart"},
                    gateway=_G())
    assert "systemMessage" not in ok


def test_a_release_stamp_is_no_card_and_no_phone():
    from imperal_mcp.mask import PIIRedactionLevel, apply_pii_redaction
    for s in ("rel-20261025-094552", "/home/ipw-releases/rel-20261025-094552 is live", "built 20261025T094552"):
        assert apply_pii_redaction(s, PIIRedactionLevel.MASK_PII) == s
    assert "<CARD>" in apply_pii_redaction("card 4111 1111 1111 1111", PIIRedactionLevel.MASK_PII)
    assert "<CARD>" in apply_pii_redaction("pay 5555555555554444", PIIRedactionLevel.MASK_PII)
    assert "<CARD>" in apply_pii_redaction("order 1234567890123", PIIRedactionLevel.MASK_PII)   # fail-closed
    assert "4111" not in apply_pii_redaction("visa-4111111111111111", PIIRedactionLevel.MASK_PII)     # glued: a card
    assert "<CARD>" in apply_pii_redaction("20261025094552", PIIRedactionLevel.MASK_PII)   # bare: the card check holds
    for s in ("4111 1111 1111 1111 123", "acct 12 4111 1111 1111 1111"):              # a card beside other digits
        assert "1111 1111" not in apply_pii_redaction(s, PIIRedactionLevel.MASK_PII), s
