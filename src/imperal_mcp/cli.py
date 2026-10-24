from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from pathlib import Path

from .config import Config
from . import auth
from .exoskeleton import EXOSKELETON_INSTRUCTIONS, ExoskeletonRuntime, MissingCodeDependencyError, NotARepositoryError

_CLAUDE_MD_START = "<!-- IMPERAL-MCP-EXOSKELETON:START -->"
_CLAUDE_MD_END = "<!-- IMPERAL-MCP-EXOSKELETON:END -->"


def _resolve_cli_executable() -> tuple[str, list[str]]:
    """Resolve the imperal-mcp executable belonging to the current Python environment.

    Avoids picking up a stale global/Homebrew `imperal-mcp` from PATH when running
    inside a virtualenv or isolated interpreter.
    """
    exe_dir = Path(sys.executable).parent
    for name in ("imperal-mcp", "imperal-mcp.exe"):
        cand = exe_dir / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand), []
    prefix_bin = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    for name in ("imperal-mcp", "imperal-mcp.exe"):
        cand = prefix_bin / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand), []
    return sys.executable, ["-m", "imperal_mcp.cli"]


def _format_cli_command(cmd: str, args: list[str]) -> str:
    parts = [cmd, *args]
    return " ".join(shlex.quote(p) for p in parts)


def _load_json_dict_strict(path: Path) -> dict:
    """Load an existing JSON object file without silently wiping it on syntax error."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Refusing to overwrite {path}: existing file contains invalid JSON ({exc})"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError(
            f"Refusing to overwrite {path}: expected top-level JSON object, got {type(loaded).__name__}"
        )
    return loaded


def install_claude_hooks(workspace: str | os.PathLike[str] | None = None) -> dict:
    """Idempotently configure Claude Code hooks in `.claude/settings.local.json`."""
    ws = Path(workspace or os.getcwd()).resolve()
    claude_dir = ws / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.local.json"
    exe, exe_args = _resolve_cli_executable()
    cli_cmd = _format_cli_command(exe, exe_args)
    hook_cmd = f"{cli_cmd} hook post-tool-use"

    data = _load_json_dict_strict(settings_path)
    hooks = data.get("hooks")
    if hooks is None:
        hooks = {}
        data["hooks"] = hooks
    elif not isinstance(hooks, dict):
        raise ValueError(
            f"Refusing to overwrite {settings_path}: 'hooks' must be a JSON object"
        )

    post_list = hooks.get("PostToolUse")
    if post_list is None:
        post_list = []
        hooks["PostToolUse"] = post_list
    elif not isinstance(post_list, list):
        raise ValueError(
            f"Refusing to overwrite {settings_path}: 'hooks.PostToolUse' must be a list"
        )

    imperal_entry = {
        "matcher": "Edit|MultiEdit|Write",
        "hooks": [
            {
                "type": "command",
                "command": hook_cmd,
            }
        ],
    }

    already_present = False
    for entry in post_list:
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        if not isinstance(inner, list):
            continue
        for h in inner:
            if isinstance(h, dict) and "hook post-tool-use" in str(h.get("command", "")):
                h["command"] = hook_cmd
                already_present = True
                break
        if already_present:
            break

    if not already_present:
        post_list.append(imperal_entry)

    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "workspace": str(ws),
        "settings_path": str(settings_path),
        "hook_command": hook_cmd,
    }


def run_claude_hook(
    event: str = "post-tool-use",
    *,
    workspace: str | os.PathLike[str] | None = None,
    payload: dict | None = None,
    stdin_data: str | None = None,
) -> dict:
    """Execute a Claude Code hook event without silently swallowing syntax errors."""
    ws = str(Path(workspace or os.getcwd()).resolve())
    data_payload: dict = dict(payload) if isinstance(payload, dict) else {}
    if not data_payload:
        raw = stdin_data
        if raw is None and not sys.stdin.isatty():
            try:
                raw = sys.stdin.read()
            except Exception:
                raw = ""
        if raw and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data_payload = parsed
            except Exception:
                data_payload = {}

    tool_input = data_payload.get("tool_input") if isinstance(data_payload.get("tool_input"), dict) else {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or data_payload.get("file_path")
        or data_payload.get("path")
    )
    out: dict = {"status": "ok", "event": event, "workspace": ws, "exit_code": 0}
    if file_path:
        try:
            exo = ExoskeletonRuntime(workspace=ws)
            chk = exo.check_syntax(str(file_path), root=ws)
            out["syntax_check"] = chk
            if chk.get("clean") is False and chk.get("errors"):
                errs = chk.get("errors") or []
                lines = [f"Imperal MCP syntax check failed for {chk.get('path') or file_path}:"]
                for err in errs:
                    lines.append(
                        f"  line {err.get('line', '?')}, col {err.get('column', '?')}: {err.get('message', 'syntax error')}"
                    )
                msg = "\n".join(lines)
                out["status"] = "syntax_error"
                out["message"] = msg
                out["exit_code"] = 2
                print(msg, file=sys.stderr)
            elif chk.get("status") == "error" and chk.get("error"):
                msg = f"Imperal MCP syntax check warning for {file_path}: {chk['error']}"
                out["message"] = msg
                print(msg, file=sys.stderr)
        except Exception as exc:
            out["syntax_check"] = {"status": "skipped", "reason": str(exc)}
    return out


def setup_claude_code(
    workspace: str | os.PathLike[str] | None = None,
    *,
    write_mcp_json: bool = True,
    write_claude_md: bool = True,
    with_hooks: bool = False,
) -> dict:
    """Configure Claude Code (.mcp.json and CLAUDE.md) for the Imperal Exoskeleton.

    Idempotent and non-destructive: preserves existing MCP servers in `.mcp.json`
    and existing user instructions in `CLAUDE.md`, and refuses to overwrite
    malformed JSON files.
    """
    ws = Path(workspace or os.getcwd()).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    cmd, cmd_args = _resolve_cli_executable()
    result: dict = {"workspace": str(ws), "mcp_json": None, "claude_md": None, "hooks": None}

    if write_mcp_json:
        mcp_path = ws / ".mcp.json"
        data = _load_json_dict_strict(mcp_path)
        servers = data.get("mcpServers")
        if servers is None:
            servers = {}
            data["mcpServers"] = servers
        elif not isinstance(servers, dict):
            raise ValueError(
                f"Refusing to overwrite {mcp_path}: 'mcpServers' must be a JSON object"
            )
        servers["imperal"] = {
            "command": cmd,
            "args": cmd_args,
            "env": {
                "IMPERAL_WORKSPACE": str(ws),
            },
        }
        mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result["mcp_json"] = str(mcp_path)

    if write_claude_md:
        claude_path = ws / "CLAUDE.md"
        block = (
            f"{_CLAUDE_MD_START}\n"
            f"## Imperal MCP Exoskeleton Protocol\n\n"
            f"{EXOSKELETON_INSTRUCTIONS.strip()}\n"
            f"{_CLAUDE_MD_END}\n"
        )
        if claude_path.exists():
            existing = claude_path.read_text(encoding="utf-8")
            if _CLAUDE_MD_START in existing and _CLAUDE_MD_END in existing:
                pre, _, rest = existing.partition(_CLAUDE_MD_START)
                _, _, post = rest.partition(_CLAUDE_MD_END)
                updated = pre.rstrip() + "\n\n" + block + post.lstrip()
            else:
                updated = existing.rstrip() + "\n\n" + block
            claude_path.write_text(updated, encoding="utf-8")
        else:
            claude_path.write_text(f"# CLAUDE.md\n\n{block}", encoding="utf-8")
        result["claude_md"] = str(claude_path)

    if with_hooks:
        hook_res = install_claude_hooks(ws)
        result["hooks"] = hook_res["settings_path"]

    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="imperal-mcp",
        description="Imperal MCP server & AI Exoskeleton for Claude Code",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_login = sub.add_parser("login", help="Sign in via browser (device code + PKCE)")
    p_login.add_argument("--no-browser", action="store_true", help="Print URL instead of opening browser")

    sub.add_parser("logout", help="Revoke refresh token and remove local credentials")

    p_setup = sub.add_parser(
        "claude-setup",
        help="Configure Claude Code (.mcp.json and CLAUDE.md) for the Imperal Exoskeleton",
    )
    p_setup.add_argument("--workspace", default=None, help="Target project directory (default: current directory)")
    p_setup.add_argument("--no-mcp-json", action="store_true", help="Do not touch .mcp.json")
    p_setup.add_argument("--no-claude-md", action="store_true", help="Do not touch CLAUDE.md")
    p_setup.add_argument("--with-hooks", action="store_true", help="Also configure Claude Code PostToolUse hooks")

    p_hooks = sub.add_parser(
        "install-hooks",
        help="Install Claude Code PostToolUse hooks into .claude/settings.local.json",
    )
    p_hooks.add_argument("--workspace", default=None, help="Target project directory (default: current directory)")

    p_hook = sub.add_parser(
        "hook",
        help="Run a Claude Code hook event handler (e.g. post-tool-use)",
    )
    p_hook.add_argument("event", nargs="?", default="post-tool-use", help="Hook event name")
    p_hook.add_argument("--workspace", default=None, help="Target project directory (default: current directory)")

    p_status = sub.add_parser("status", help="Show workspace Exoskeleton readiness and index profile")
    p_status.add_argument("--workspace", default=None, help="Target project directory (default: current directory)")

    args = parser.parse_args(argv)
    cfg = Config.from_env()

    if args.cmd == "login":
        email = asyncio.run(auth.login_device(cfg, open_browser=not args.no_browser))
        print(f"Logged in as {email}.")
        return
    if args.cmd == "logout":
        asyncio.run(auth.logout(cfg))
        print("Logged out.")
        return
    if args.cmd == "claude-setup":
        res = setup_claude_code(
            args.workspace,
            write_mcp_json=not args.no_mcp_json,
            write_claude_md=not args.no_claude_md,
            with_hooks=args.with_hooks,
        )
        print(json.dumps({"status": "ok", **res}, indent=2))
        return
    if args.cmd == "install-hooks":
        res = install_claude_hooks(args.workspace)
        print(json.dumps({"status": "ok", **res}, indent=2))
        return
    if args.cmd == "hook":
        res = run_claude_hook(args.event, workspace=args.workspace)
        print(json.dumps(res, indent=2))
        exit_code = int(res.get("exit_code", 0) or 0)
        if exit_code != 0:
            raise SystemExit(exit_code)
        return
    if args.cmd == "status":
        exo = ExoskeletonRuntime(workspace=args.workspace)
        try:
            prof = exo.repo_profile()
            print(json.dumps({"status": "ok", "workspace": prof.get("workspace"), "profile": prof.get("profile")}, indent=2))
        except MissingCodeDependencyError as exc:
            print(json.dumps({"status": "error", "workspace": exo.resolve_workspace(), "error": str(exc)}, indent=2))
        except NotARepositoryError as exc:
            # the setup is fine; a folder of projects has no profile of its own (its repositories do)
            print(json.dumps({"status": "ok", "workspace": exo.resolve_workspace(), "profile": None,
                              "note": str(exc)}, indent=2))
        return

    from .server import build_server
    from .client import ImperalClient

    mcp = build_server(ImperalClient(cfg))
    mcp.run()


if __name__ == "__main__":
    main()
