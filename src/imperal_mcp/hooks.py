"""One command for every shell's hooks (memory plan Task 4): ``imperal-mcp hook <event>``.

Claude Code, Codex, Antigravity CLI and Gemini CLI call a command on four moments and hand it JSON on stdin with
the same fields (``session_id``, ``cwd``, ``tool_name``, ``tool_input``, ``tool_response``, ``prompt``, the last
answer); they differ in event names and in the words of a "hold the final" answer. This module turns any of them
into the kernel's exchange items and turn memory, keeps them in a spool per shell session (a file, flock'd -- the
MCP server drains the same spool into its frames), and answers in the shell's own words:

- ``post-tool``     a tool call -> the spool (no network, never slows the shell)
- ``prompt``        the user's request -> the spool, then the kernel's frame -> the model's context
- ``stop``          the final answer -> recorded, then asked about: open plan items hold it (the todo gate)
- ``session-start`` the imperal-mcp protocol and where this work stands -> the model's context

A hook never breaks its shell: any failure answers nothing (exit 0) and what was not sent stays in the spool.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from typing import Any, Callable

from .exoskeleton import EXOSKELETON_INSTRUCTIONS, exchange_item

EXCHANGE_MAX, MEMORY_MAX, MEMORY_CHARS = 60, 20, 4000     # the gateway's bounds on one step
READ_CHARS, OUTPUT_CHARS = 20000, 8000                    # what of a read / an output reaches the kernel
_IMPERAL_TOOL = re.compile(r"^mcp_{1,2}imperal_{1,2}")    # imperal-mcp's own calls: the server records those
_SHELL_TOOLS = {"bash", "shell", "run_shell_command", "run_command", "exec_command", "execute_command", "terminal"}
_EDIT_TOOLS = {"edit", "multiedit", "replace", "edit_file", "str_replace"}
_WRITE_TOOLS = {"write", "write_file", "create_file"}
_READ_TOOLS = {"read", "read_file", "view", "view_file", "read_many_files"}
_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)


def spool_dir() -> str:
    return os.environ.get("IMPERAL_MCP_SPOOL") or os.path.join(os.path.expanduser("~"), ".local", "share",
                                                                "imperal-mcp", "spool")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "default"))[:120] or "default"


def _private(path: str, mode: str = "a"):
    """A spool file only this user can read (security review: the spool holds what the session saw)."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "a" else os.O_TRUNC)
    return os.fdopen(os.open(path, flags, 0o600), mode, encoding="utf-8")


@contextlib.contextmanager
def _locked(path: str):
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    with _private(path + ".lock") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except (ImportError, OSError):     # no flock (Windows): one writer at a time is the shells' own order
            pass
        yield


class Spool:
    """A shell session's pending exchange items and memory, and its shared state (step, goal, plan, repo key) --
    read and written by the hooks and by the MCP server alike."""

    def __init__(self, session: str):
        self.base = os.path.join(spool_dir(), _safe(session))

    def _append(self, kind: str, obj: dict) -> None:
        with _locked(self.base):
            with _private(self.base + ".jsonl") as f:
                f.write(json.dumps({"k": kind, "v": obj}, ensure_ascii=False) + "\n")

    def add_items(self, items: list) -> None:
        for it in items:
            self._append("item", it)

    def add_memory(self, entry: dict) -> None:
        self._append("memory", entry)

    def drain(self) -> tuple[list, list]:
        items, memory = [], []
        with _locked(self.base):
            try:
                with open(self.base + ".jsonl", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                os.remove(self.base + ".jsonl")
            except FileNotFoundError:
                return [], []
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            (items if rec.get("k") == "item" else memory).append(rec.get("v"))
        return items, memory

    def restore(self, items: list, memory: list) -> None:
        """What a failed send drained goes back (in front of anything newer)."""
        with _locked(self.base):
            try:
                with open(self.base + ".jsonl", encoding="utf-8") as f:
                    newer = f.read()
            except FileNotFoundError:
                newer = ""
            with _private(self.base + ".jsonl", "w") as f:
                for it in items:
                    f.write(json.dumps({"k": "item", "v": it}, ensure_ascii=False) + "\n")
                for m in memory:
                    f.write(json.dumps({"k": "memory", "v": m}, ensure_ascii=False) + "\n")
                f.write(newer)

    def state(self) -> dict:
        try:
            with open(self.base + ".state.json", encoding="utf-8") as f:
                got = json.load(f)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def update(self, **fields: Any) -> dict:
        with _locked(self.base):
            st = {**self.state(), **fields}
            tmp = self.base + ".state.tmp"
            with _private(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, self.base + ".state.json")
        return st


def announce(cwd: str, session: str) -> None:
    """The shell session working in ``cwd`` now -- the MCP server finds its spool by it."""
    path = os.path.join(spool_dir(), "current.json")
    with _locked(path):
        try:
            with open(path, encoding="utf-8") as f:
                cur = json.load(f)
        except (OSError, ValueError):
            cur = {}
        cur = {k: v for k, v in (cur if isinstance(cur, dict) else {}).items()
               if isinstance(v, dict) and time.time() - float(v.get("at") or 0) < 7 * 86400}
        cur[os.path.realpath(cwd or ".")] = {"session": session, "at": time.time()}
        tmp = path + ".tmp"
        with _private(tmp, "w") as f:
            json.dump(cur, f)
        os.replace(tmp, path)


def current_session(workspace: str) -> str:
    """The shell session last seen working in ``workspace`` (or a folder inside it, or one containing it)."""
    try:
        with open(os.path.join(spool_dir(), "current.json"), encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        return ""
    ws = os.path.realpath(workspace or ".")
    best = ("", 0.0)
    for cwd, v in (cur if isinstance(cur, dict) else {}).items():
        near = cwd == ws or cwd.startswith(ws + os.sep) or ws.startswith(cwd + os.sep)
        if near and isinstance(v, dict) and float(v.get("at") or 0) > best[1]:
            best = (str(v.get("session") or ""), float(v.get("at") or 0))
    return best[0]


def mcp_session(me: str, shell_session: str) -> str:
    """The kernel's session for a shell session -- the same id from the hooks and from the MCP server."""
    return "mcp-" + me + "-" + hashlib.sha1(f"shell|{shell_session}".encode()).hexdigest()[:12]


def normalize(payload: dict) -> dict:
    """Antigravity CLI names its fields its own way (``conversationId``, ``workspacePaths``, ``toolCall``): the same
    payload in the common words (the other shells already use them)."""
    if "conversationId" not in payload:
        return payload
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    paths = payload.get("workspacePaths") if isinstance(payload.get("workspacePaths"), list) else []
    err = str(payload.get("error") or "")
    out = {**payload, "session_id": str(payload.get("conversationId") or ""), "cwd": str(paths[0]) if paths else "",
           "transcript_path": str(payload.get("transcriptPath") or ""), "_shell": "antigravity"}
    if call:
        out.update(tool_name=str(call.get("name") or ""),
                   tool_input=call.get("args") if isinstance(call.get("args"), dict) else {},
                   tool_response={"error": err} if err else "")
    return out


def _event(payload: dict) -> str:
    return str(payload.get("hook_event_name") or "")


def _shell(payload: dict) -> str:
    if payload.get("_shell") == "antigravity" or "conversationId" in payload:
        return "antigravity"
    ev = _event(payload)
    if ev in ("AfterTool", "BeforeTool", "AfterAgent", "BeforeAgent") or (
            isinstance(payload.get("tool_response"), dict) and "llmContent" in payload["tool_response"]):
        return "gemini"
    return "codex" if "turn_id" in payload or "model" in payload else "claude"


def _text_of(resp: Any) -> tuple[str, bool]:
    """A tool's answer as text, and whether it went well."""
    if isinstance(resp, str):
        return resp, True
    if not isinstance(resp, dict):
        return (json.dumps(resp, ensure_ascii=False)[:OUTPUT_CHARS] if resp is not None else ""), True
    bad = bool(resp.get("error") or resp.get("is_error") or resp.get("isError"))
    if isinstance(resp.get("file"), dict):
        return str(resp["file"].get("content") or ""), not bad
    for k in ("llmContent", "output", "content", "result", "text"):
        if isinstance(resp.get(k), str):
            return resp[k], not bad
    out = "\n".join(str(resp.get(k) or "") for k in ("stdout", "stderr") if resp.get(k))
    if out or "stdout" in resp:
        code = resp.get("exit_code", resp.get("exitCode", 0))
        return out, not bad and not resp.get("interrupted") and code in (0, None)
    return json.dumps(resp, ensure_ascii=False)[:OUTPUT_CHARS], not bad


def _command(inp: dict) -> str:
    cmd = inp.get("command", inp.get("CommandLine", inp.get("cmd", "")))
    if isinstance(cmd, list):
        cmd = cmd[-1] if len(cmd) >= 3 and cmd[1] in ("-lc", "-c") else " ".join(str(c) for c in cmd)
    return str(cmd or "")


def tool_items(payload: dict) -> list:
    """A shell's tool call as the kernel's exchange items (``[]`` for imperal-mcp's own -- the server has them)."""
    payload = normalize(payload)
    name = str(payload.get("tool_name") or "")
    if not name or _IMPERAL_TOOL.match(name):
        return []
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    text, ok = _text_of(payload.get("tool_response"))
    low = name.lower()
    path = str(inp.get("file_path") or inp.get("path") or inp.get("absolute_path") or inp.get("AbsolutePath") or "")
    if low == "apply_patch":
        patch = str(inp.get("input") or inp.get("patch") or "")
        return [exchange_item("edit_file", {"path": p.strip(), "old_string": "", "new_string": ""}, ok, text)
                for p in _PATCH_FILE.findall(patch)]
    if low in _SHELL_TOOLS or (not path and _command(inp)):
        return [exchange_item("bash", {"command": _command(inp)}, ok, text, text_limit=OUTPUT_CHARS)]
    if low in _EDIT_TOOLS:
        return [exchange_item("edit_file", {"path": path, "old_string": str(inp.get("old_string") or ""),
                                            "new_string": str(inp.get("new_string") or "")}, ok, text)]
    if low in _WRITE_TOOLS:
        body = str(inp.get("content") or "")
        return [exchange_item("write_file", {"path": path, "content": body, "content_chars": len(body)}, ok, text)]
    if low in _READ_TOOLS and path:
        return [exchange_item("read_file", {"path": path}, ok, text, text_limit=READ_CHARS)]
    if low in ("grep", "glob", "search_file_content", "ls", "list_directory"):
        return [exchange_item("grep" if low != "glob" else "glob", {k: str(v) for k, v in inp.items()}, ok, text,
                              text_limit=OUTPUT_CHARS)]
    # any other tool (another MCP server's, a web fetch...): its name and whether it went well -- never its args or
    # its answer, which may carry anything (final review C1)
    return [{"app_id": "", "tool": name, "args": {}, "ok": bool(ok), "text": ""}]


def last_answer(payload: dict) -> str:
    """The model's final answer: Codex ``last_assistant_message``, Gemini ``prompt_response``, Claude Code's
    transcript (its last assistant text)."""
    for k in ("last_assistant_message", "prompt_response"):
        if str(payload.get(k) or "").strip():
            return str(payload[k])
    path = str(payload.get("transcript_path") or "")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[-200:]
    except OSError:
        return ""
    for ln in reversed(lines):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        texts = [c.get("text") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"] \
            if isinstance(content, list) else [content]
        got = "\n".join(str(t) for t in texts if t)
        if got.strip():
            return got
    return ""


def context_output(payload: dict, text: str) -> dict:
    if _shell(payload) == "antigravity":
        return {"injectSteps": [{"ephemeralMessage": text}]}
    return {"hookSpecificOutput": {"hookEventName": _event(payload), "additionalContext": text}}


def block_output(payload: dict, reason: str) -> dict:
    """Hand the final back to the model, in the shell's words (Gemini: deny; Antigravity: continue; else block)."""
    word = {"gemini": "deny", "antigravity": "continue"}.get(_shell(payload), "block")
    return {"decision": word, "reason": reason}


def _session_of(payload: dict, gateway) -> tuple[Spool, str, str]:
    shell_session = str(payload.get("session_id") or "default")
    spool = Spool(shell_session)
    me = spool.state().get("me") or ""
    if not me:
        me = str(gateway.me() or "")
        if me:
            spool.update(me=me)
    return spool, shell_session, mcp_session(me, shell_session) if me else ""


def _send(spool: Spool, send: Callable[[list, list], Any]) -> Any:
    items, memory = spool.drain()
    try:
        return send(items[-EXCHANGE_MAX:], memory[-MEMORY_MAX:])
    except Exception:
        spool.restore(items, memory)
        raise


def run_hook(event: str, payload: dict, gateway=None) -> dict | None:
    """One hook event; the answer to print (or ``None``). Never raises."""
    try:
        return _run(event, normalize(payload if isinstance(payload, dict) else {}), gateway or _Gateway())
    except Exception:
        return None


def _clean(text: str) -> str:
    """A prompt or an answer as it may leave the machine: PII masked, credentials redacted (final review C1)."""
    from .mask import defensive_scrub
    from .secrets_scrub import scrub_secrets
    return str(scrub_secrets(str(defensive_scrub(str(text or "")))))


def ignored(cwd: str) -> bool:
    """A folder the user keeps out of the vault (``IMPERAL_MCP_IGNORE``, paths joined by the OS separator)."""
    here = os.path.realpath(cwd or ".")
    for r in os.environ.get("IMPERAL_MCP_IGNORE", "").split(os.pathsep):
        root = os.path.realpath(os.path.expanduser(r)) if r.strip() else ""
        if root and (here == root or here.startswith(root + os.sep)):
            return True
    return False


def _run(event: str, payload: dict, gateway) -> dict | None:
    shell_session = str(payload.get("session_id") or "default")
    if event != "session-start" and ignored(str(payload.get("cwd") or os.getcwd())):
        return None
    announce(str(payload.get("cwd") or os.getcwd()), shell_session)
    spool = Spool(shell_session)
    if event == "post-tool":
        spool.add_items(tool_items(payload))
        return None
    if event == "session-start":
        try:
            where = str(gateway.recall_context(os.path.basename(os.path.realpath(payload.get("cwd") or "."))) or "")
        except Exception:
            where = ""
        text = EXOSKELETON_INSTRUCTIONS.strip() + ("\n\nWHERE THIS WORK STANDS (from the vault):\n" + where
                                                    if where.strip() else "")
        return context_output(payload, text)
    if event == "prompt":
        prompt = str(payload.get("prompt") or "")
        if prompt.strip():
            spool.add_memory({"kind": "user_request", "content": _clean(prompt)[:MEMORY_CHARS]})
        spool, _ss, sess = _session_of(payload, gateway)
        st = spool.state()
        step = int(st.get("step") or 0) + 1

        def _frame(items, memory):
            return gateway.frame({"session_id": sess, "step": step, "goal": str(st.get("goal") or _clean(prompt))[:4000],
                                  "items": list(st.get("items") or []), "exchange": items, "memory": memory,
                                  "repo_key": str(st.get("repo_key") or "")})
        ans = _send(spool, _frame)
        spool.update(step=step)
        frame = str((ans or {}).get("frame") or (ans or {}).get("content") or "")
        return context_output(payload, frame) if frame.strip() else None
    if event == "stop":
        final = last_answer(payload)
        if final.strip():
            spool.add_memory({"kind": "final", "content": _clean(final)[:MEMORY_CHARS]})
        spool, _ss, sess = _session_of(payload, gateway)
        st = spool.state()
        _send(spool, lambda items, memory: gateway.record({"session_id": sess, "step": int(st.get("step") or 0),
                                                           "exchange": items, "memory": memory,
                                                           "repo_key": str(st.get("repo_key") or "")}))
        got = gateway.final({"session_id": sess, "final_text": _clean(final)[:20000],
                             "repo_key": str(st.get("repo_key") or "")})
        if (got or {}).get("hold") and str(got.get("reason") or "").strip():
            return block_output(payload, str(got["reason"]))
        return None
    return None


class _Gateway:
    """The gateway as the hooks use it -- the user's own stored sign-in, short timeouts."""
    TIMEOUT_S = 25.0

    def __init__(self):
        from .client import ImperalClient
        from .config import Config
        self._client = ImperalClient(Config.from_env())

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        import asyncio
        return asyncio.run(self._client._request(method, path, json=body, timeout=self.TIMEOUT_S))

    def me(self) -> str:
        return str((self._call("GET", "/v1/auth/me") or {}).get("imperal_id") or "")

    def frame(self, body: dict) -> dict:
        try:
            return self._call("POST", "/v1/memory/frame", body) or {}
        except Exception as exc:
            if getattr(exc, "status_code", None) == 402:      # not charged: the model hears why, the step stays
                from .exoskeleton import _detail_of
                return {"content": _detail_of(str(exc))}
            raise

    def record(self, body: dict) -> dict:
        return self._call("POST", "/v1/memory/frame/record", body) or {}

    def final(self, body: dict) -> dict:
        return self._call("POST", "/v1/memory/frame/final", body) or {}

    def recall_context(self, query: str) -> str:
        """The user's directives and this work's notes (the ``recall_context`` tool's own source: memory-index)."""
        import asyncio
        from .mask import defensive_scrub
        got = asyncio.run(self._client.run_tool("memory-index", "recall_context",
                                                {"query": query, "limit": 5, "include_user_facts": True,
                                                 "include_repo_memory": True, "include_resolved": False}))
        text = got if isinstance(got, str) else json.dumps(got, ensure_ascii=False, default=str)
        return str(defensive_scrub(text))[:4000]
