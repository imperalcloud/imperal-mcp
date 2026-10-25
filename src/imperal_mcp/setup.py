"""`imperal-mcp setup` (memory plan Task 6): every shell gets the server, the hooks and the protocol.

User level, so imperal-mcp works in any folder. Per shell, three things, each only in its own marked place:
- the MCP server ``imperal`` (never over a server the user named ``imperal`` themselves);
- the four hooks -> ``imperal-mcp hook <event>`` (session-start, prompt, post-tool, stop), in the shell's format;
- the protocol block between markers in the shell's global instructions file.
``remove=True`` takes away exactly what setup put; a config that does not parse is never written.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil

from .exoskeleton import EXOSKELETON_INSTRUCTIONS

SHELLS = ("claude", "codex", "antigravity", "gemini")
_START, _END = "<!-- IMPERAL-MCP:START -->", "<!-- IMPERAL-MCP:END -->"
_TOML_START, _TOML_END = "# >>> imperal-mcp (managed: `imperal-mcp setup --remove` takes it away)", "# <<< imperal-mcp"
_OURS = re.compile(r"imperal[-_]mcp\S* hook (session-start|prompt|post-tool|stop)\b")
# seconds (Gemini CLI: milliseconds): a frame may take its time, a tool call never waits
_TIMEOUT = {"session-start": 20, "prompt": 40, "post-tool": 10, "stop": 40}


def _exe() -> tuple[str, list]:
    """The program the shells run: imperal-mcp's own console script (an absolute path), else its module in an
    interpreter that never puts the current folder on its path (security review: no module from a project wins)."""
    import sys
    from . import cli
    launcher = os.environ.get("IMPERAL_MCP_LAUNCHER", "")
    if launcher and os.path.isfile(launcher) and os.access(launcher, os.X_OK):
        return launcher, []        # started through the launcher: it picks the current release on every run
    exe, args = cli._resolve_cli_executable()
    if args[:1] == ["-m"]:
        args = ["-P" if sys.version_info >= (3, 11) else "-I", *args]
    return exe, args


def _cmd(event: str, shell: str) -> str:
    import shlex
    exe, args = _exe()
    return " ".join(shlex.quote(p) for p in [exe, *args, "hook", event, "--shell", shell])


def _server() -> dict:
    exe, args = _exe()
    return {"command": exe, "args": list(args)}


def installed_shells(home: str) -> list:
    """The shells on this machine: their program on PATH or their config folder in the home."""
    found = {"claude": shutil.which("claude") or os.path.isdir(os.path.join(home, ".claude")),
             "codex": shutil.which("codex") or os.path.isdir(os.path.join(home, ".codex")),
             "antigravity": shutil.which("agy") or os.path.isdir(os.path.join(home, ".gemini", "antigravity-cli")),
             "gemini": shutil.which("gemini")}
    return [s for s in SHELLS if found[s]]


def _load(path: str) -> dict:
    if not os.path.exists(path) or not open(path, encoding="utf-8").read().strip():
        return {}
    data = json.loads(open(path, encoding="utf-8").read())     # a broken file raises: never overwritten
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a JSON object")
    return data


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if os.path.exists(path) and open(path, encoding="utf-8").read() == text:
        return
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600   # its own mode kept; a new file private
    tmp = path + ".imperal-tmp"
    with contextlib.suppress(FileNotFoundError):
        os.remove(tmp)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _strip_ours(groups: list) -> list:
    """A hook event's groups without imperal-mcp's handlers (a group left empty goes too)."""
    out = []
    for g in groups if isinstance(groups, list) else []:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list):
            kept = [h for h in g["hooks"] if not (isinstance(h, dict) and _OURS.search(str(h.get("command") or "")))]
            if kept:
                out.append({**g, "hooks": kept})
        elif not (isinstance(g, dict) and _OURS.search(str(g.get("command") or ""))):
            out.append(g)
    return out


def _set_hooks(hooks: dict, events: dict, shell: str, remove: bool, ms: bool = False, grouped: bool = True) -> dict:
    """``events``: the shell's event name -> (our event, matcher or None)."""
    hooks = dict(hooks if isinstance(hooks, dict) else {})
    for name, (ours, matcher) in events.items():
        groups = _strip_ours(hooks.get(name) or [])
        if not remove:
            handler = {"type": "command", "command": _cmd(ours, shell),
                       "timeout": _TIMEOUT[ours] * (1000 if ms else 1)}
            if grouped:
                groups.append({**({"matcher": matcher} if matcher else {}), "hooks": [handler]})
            else:
                groups.append(handler)
        if groups:
            hooks[name] = groups
        else:
            hooks.pop(name, None)
    return hooks


def _set_server(data: dict, key: str, remove: bool) -> dict:
    servers = dict(data.get(key) or {}) if isinstance(data.get(key), dict) else {}
    mine = servers.get("imperal")
    ours = isinstance(mine, dict) and "imperal" in str(mine.get("command") or "") and "mcp" in str(mine.get("command") or "")
    if remove:
        if ours:
            servers.pop("imperal")
    elif mine is None or ours:
        servers["imperal"] = _server()
    data = dict(data)
    if servers:
        data[key] = servers
    else:
        data.pop(key, None)
    return data


def _block(path: str, remove: bool) -> None:
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if _START in text and _END in text:
        pre, _, rest = text.partition(_START)
        _, _, post = rest.partition(_END)
        text = (pre.rstrip() + "\n\n" + post.lstrip()).strip() + "\n" if (pre.strip() or post.strip()) else ""
    if not remove:
        block = f"{_START}\n{EXOSKELETON_INSTRUCTIONS.strip()}\n{_END}\n"
        text = (text.rstrip() + "\n\n" + block) if text.strip() else block
    if text.strip():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    elif os.path.exists(path):
        os.remove(path)


def _toml_server(path: str, remove: bool) -> str:
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if _TOML_START in text and _TOML_END in text:
        pre, _, rest = text.partition(_TOML_START)
        _, _, post = rest.partition(_TOML_END)
        text = (pre.rstrip() + "\n" + post.lstrip("\n")).strip()
        text = text + "\n" if text else ""
    note = ""
    if not remove:
        if re.search(r"^\[mcp_servers\.imperal\]", text, re.M):
            note = "an [mcp_servers.imperal] of your own is kept"
        else:
            srv = _server()
            block = (f"{_TOML_START}\n[mcp_servers.imperal]\ncommand = {json.dumps(srv['command'])}\n"
                     f"args = {json.dumps(srv['args'])}\n{_TOML_END}\n")
            text = (text.rstrip() + "\n\n" + block) if text.strip() else block
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if text.strip():
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    elif os.path.exists(path):
        os.remove(path)
    return note


def _claude(home: str, remove: bool) -> dict:
    cfg = os.path.join(home, ".claude.json")
    settings = os.path.join(home, ".claude", "settings.json")
    data, st = _load(cfg), _load(settings)
    _save(cfg, _set_server(data, "mcpServers", remove))
    st["hooks"] = _set_hooks(st.get("hooks"), {"SessionStart": ("session-start", None),
                                               "UserPromptSubmit": ("prompt", None),
                                               "PostToolUse": ("post-tool", "*"), "Stop": ("stop", None)},
                             "claude", remove)
    if not st["hooks"]:
        st.pop("hooks")
    _save(settings, st)
    _block(os.path.join(home, ".claude", "CLAUDE.md"), remove)
    return {"server": cfg, "hooks": settings, "protocol": os.path.join(home, ".claude", "CLAUDE.md")}


def _codex(home: str, remove: bool) -> dict:
    hooks_path = os.path.join(home, ".codex", "hooks.json")
    hk = _load(hooks_path)
    note = _toml_server(os.path.join(home, ".codex", "config.toml"), remove)
    hk["hooks"] = _set_hooks(hk.get("hooks"), {"SessionStart": ("session-start", "startup|resume|clear|compact"),
                                               "UserPromptSubmit": ("prompt", None),
                                               "PostToolUse": ("post-tool", None), "Stop": ("stop", None)},
                             "codex", remove)
    if not hk["hooks"]:
        hk.pop("hooks")
    if hk or os.path.exists(hooks_path):
        _save(hooks_path, hk)
    _block(os.path.join(home, ".codex", "AGENTS.md"), remove)
    trust = "" if remove else "run /hooks in Codex once and trust the imperal-mcp hooks (Codex runs a new hook only then)"
    return {"server": os.path.join(home, ".codex", "config.toml"), "hooks": hooks_path,
            "protocol": os.path.join(home, ".codex", "AGENTS.md"), "note": "; ".join(x for x in (note, trust) if x)}


def _antigravity(home: str, remove: bool) -> dict:
    mcp = os.path.join(home, ".gemini", "config", "mcp_config.json")
    hooks_path = os.path.join(home, ".gemini", "config", "hooks.json")
    _save(mcp, _set_server(_load(mcp), "mcpServers", remove))
    hk = _load(hooks_path)
    if remove:
        hk.pop("imperal-mcp", None)
    else:   # Antigravity: a named hook -> its events; tool events grouped by matcher, the others a plain list
        hk["imperal-mcp"] = {"SessionStart": [{"type": "command", "command": _cmd("session-start", "antigravity"),
                                               "timeout": _TIMEOUT["session-start"]}],
                             "PostToolUse": [{"matcher": ".*", "hooks": [{
                                 "type": "command", "command": _cmd("post-tool", "antigravity"),
                                 "timeout": _TIMEOUT["post-tool"]}]}],
                             "Stop": [{"type": "command", "command": _cmd("stop", "antigravity"),
                                       "timeout": _TIMEOUT["stop"]}]}
    _save(hooks_path, hk)
    _block(os.path.join(home, ".gemini", "GEMINI.md"), remove)
    return {"server": mcp, "hooks": hooks_path, "protocol": os.path.join(home, ".gemini", "GEMINI.md")}


def _gemini(home: str, remove: bool) -> dict:
    path = os.path.join(home, ".gemini", "settings.json")
    st = _set_server(_load(path), "mcpServers", remove)
    st["hooks"] = _set_hooks(st.get("hooks"), {"SessionStart": ("session-start", None),
                                               "BeforeAgent": ("prompt", None),
                                               "AfterTool": ("post-tool", ".*"), "AfterAgent": ("stop", None)},
                             "gemini", remove, ms=True)
    if not st["hooks"]:
        st.pop("hooks")
    _save(path, st)
    _block(os.path.join(home, ".gemini", "GEMINI.md"), remove)
    return {"server": path, "hooks": path, "protocol": os.path.join(home, ".gemini", "GEMINI.md")}


def setup(shells=None, home: str | None = None, remove: bool = False) -> dict:
    """Set up (or take away) imperal-mcp in ``shells`` (default: every shell found here). Per shell: the files
    written, or ``{"error": ...}`` (that shell is left exactly as it was)."""
    home = home or os.path.expanduser("~")
    todo = list(shells or installed_shells(home))
    out = {}
    for shell in todo:
        if shell not in SHELLS:
            out[shell] = {"error": f"unknown shell (one of {', '.join(SHELLS)})"}
            continue
        try:
            out[shell] = {"claude": _claude, "codex": _codex, "antigravity": _antigravity,
                          "gemini": _gemini}[shell](home, remove)
        except (ValueError, OSError) as exc:
            out[shell] = {"error": str(exc)}
    return out
