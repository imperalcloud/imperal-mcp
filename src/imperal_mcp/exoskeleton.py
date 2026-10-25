from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .mask import defensive_scrub


class MissingCodeDependencyError(ImportError, RuntimeError):
    """Raised when an Exoskeleton code-intelligence tool is called without `imperal-mcp[code]` (`webbee`) installed."""


MISSING_CODE_DEPENDENCY_MESSAGE = (
    "Code intelligence tools require the optional 'webbee' dependency. "
    "Install it with: pip install 'imperal-mcp[code]' (or: pip install webbee)"
)


def _ensure_webbee_importable() -> None:
    """Ensure `webbee` is importable, or raise MissingCodeDependencyError."""
    try:
        import webbee  # noqa: F401
    except ImportError as exc:
        raise MissingCodeDependencyError(MISSING_CODE_DEPENDENCY_MESSAGE) from exc


class TokenSavingsTracker:
    """Per-session telemetry: how many calls each tool answered and how much it returned. No "saved vs. whole
    files" figure -- a useless answer must never pass for savings (frame phase A, spec A6)."""

    def __init__(self) -> None:
        self.calls: int = 0
        self.lines_returned: int = 0
        self.chars_returned: int = 0
        self.by_tool: dict[str, dict[str, int]] = {}

    def record(self, tool: str, *, returned_chars: int, returned_lines: int = 0, **_baseline: Any) -> dict[str, Any]:
        ret_c, ret_l = max(0, int(returned_chars)), max(0, int(returned_lines))
        self.calls += 1
        self.chars_returned += ret_c
        self.lines_returned += ret_l
        slot = self.by_tool.setdefault(tool, {"calls": 0, "returned_chars": 0, "returned_lines": 0})
        slot["calls"] += 1
        slot["returned_chars"] += ret_c
        slot["returned_lines"] += ret_l
        return {"tool": tool, "returned_chars": ret_c, "returned_lines": ret_l}

    def summary(self) -> dict[str, Any]:
        return {"calls": self.calls, "returned_chars": self.chars_returned, "returned_lines": self.lines_returned,
                "by_tool": {k: dict(v) for k, v in self.by_tool.items()}}


COARSE = "vault graph unavailable: links by name"
_SYNC_REUSE_S = 3.0      # one tool call's questions share one sync of the workspace
_PROFILE_KEYS = ("repo_key", "file_count", "def_count", "languages", "top_symbols")


def _detail_of(message: str) -> str:
    """The gateway's ``detail`` out of an ``ImperalError`` message (``METHOD path -> code: {"detail": ...}``)."""
    _, _, body = message.partition(": ")
    try:
        return str(json.loads(body).get("detail") or body)
    except Exception:
        return body or message


def _off_thread(fn):
    """Run ``fn`` on a worker thread and return its result (an async client is driven there with its own loop:
    a sync MCP tool may be called on the server's loop thread, where ``asyncio.run`` cannot start)."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:          # re-raised on the caller's thread
            box["error"] = exc
    t = threading.Thread(target=run, name="imperal-mcp-vault", daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _OnLoop:
    """The Imperal client driven on one event loop -- the server's (its token-refresh lock assumes one loop): a
    call from a worker thread's own loop is handed to that loop and awaited from here."""

    def __init__(self, client: Any, runtime: Any) -> None:
        self._client, self._runtime = client, runtime

    async def _request(self, *args: Any, **kwargs: Any) -> Any:
        import asyncio
        loop = getattr(self._runtime, "loop", None)
        if loop is None or not loop.is_running():
            return await self._client._request(*args, **kwargs)
        try:
            if asyncio.get_running_loop() is loop:
                return await self._client._request(*args, **kwargs)
        except RuntimeError:
            pass
        fut = asyncio.run_coroutine_threadsafe(self._client._request(*args, **kwargs), loop)
        return await asyncio.wrap_future(fut)


def scope_recall(res: Any, repo_keys: Any) -> Any:
    """Cloud memory for this repo: a repo note of another repo is dropped, identical contents are kept once;
    user facts and directives always stay."""
    keys = {repo_keys} if isinstance(repo_keys, str) else set(repo_keys or ())
    data = (res or {}).get("data") if isinstance(res, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("snippets"), list):
        return res
    # outside any repo the recall knows (no note of it), every repo note stays
    mine = any(isinstance(x, dict) and str(x.get("source_id") or "") in keys for x in data["snippets"])
    out, seen = [], set()
    for snip in data["snippets"]:
        if not isinstance(snip, dict):
            continue
        if snip.get("category") == "repo_knowledge" and mine and str(snip.get("source_id") or "") not in keys:
            continue
        content = str(snip.get("content") or "")
        if content in seen:
            continue
        seen.add(content)
        out.append(snip)
    return {**res, "data": {**data, "snippets": out}}


def _normalize_search_matches(
    matches: list[dict[str, Any]],
    ws: str,
    query: str,
    k: int = 10,
    kind: str | None = None,
    path_glob: str | None = None,
) -> list[dict[str, Any]]:
    import fnmatch

    normalized: list[dict[str, Any]] = []
    for raw in matches or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        path_val = (
            item.get("path")
            or item.get("def_path")
            or item.get("file")
            or item.get("rel_path")
            or ""
        )
        if not path_val:
            item_id = str(item.get("id") or "")
            parts = item_id.split(":")
            if len(parts) >= 4 and parts[1] in ("sym", "chunk", "file"):
                path_val = parts[2]
        if path_val:
            item.setdefault("path", path_val)
            item.setdefault("file", path_val)
        normalized.append(item)

    if any(m.get("path") for m in normalized):
        return normalized[:k]

    # Fallback lexical scan across workspace files when vector/AST index has no path hits
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query or "") if len(t) >= 2]
    if not tokens:
        return normalized[:k]

    skip_dirs = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}
    root_path = Path(ws)
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".shadow")]
        for fname in sorted(filenames):
            full_p = Path(dirpath) / fname
            rel_p = full_p.relative_to(root_path).as_posix()
            if path_glob and not fnmatch.fnmatch(rel_p, path_glob):
                continue
            try:
                if full_p.stat().st_size > 512_000:
                    continue
                text = full_p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            low = text.lower()
            rel_low = rel_p.lower()
            if not any(tok in low or tok in rel_low for tok in tokens):
                continue
            matched_line = False
            for idx_line, line in enumerate(text.splitlines(), start=1):
                ll = line.lower()
                if any(tok in ll for tok in tokens):
                    normalized.append(
                        {
                            "id": f"lexical:{rel_p}:{idx_line}",
                            "title": fname,
                            "kind": kind or "lexical",
                            "path": rel_p,
                            "file": rel_p,
                            "line": idx_line,
                            "snippet": line.strip(),
                        }
                    )
                    matched_line = True
                    break
            if not matched_line and any(tok in rel_low for tok in tokens):
                first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
                normalized.append(
                    {
                        "id": f"file:{rel_p}:1",
                        "title": fname,
                        "kind": kind or "file",
                        "path": rel_p,
                        "file": rel_p,
                        "line": 1,
                        "snippet": first_line,
                    }
                )
            if len(normalized) >= k:
                return normalized[:k]
    return normalized[:k]


class NotARepositoryError(ValueError):
    """The folder asked about is no repository (no .git, no project manifest): never indexed or synced whole."""


def _is_repository(path: str) -> bool:
    try:
        from webbee.intel.service import is_repository
        return is_repository(path)
    except ImportError:          # webbee < 0.5.11: the same rule
        try:
            names = set(os.listdir(path))
        except OSError:
            return False
        return ".git" in names or bool(names & {"pyproject.toml", "setup.cfg", "jsconfig.json", "package.json",
                                                  "setup.py", "requirements.txt", "tsconfig.json"})


class OutsideWorkspaceError(ValueError):
    """Raised when a relative path escapes the configured workspace root."""


def _resolve_root(root: str | None = None) -> str:
    cand = (root or "").strip() or os.environ.get("IMPERAL_WORKSPACE", "").strip() or os.getcwd()
    return os.path.realpath(os.path.expanduser(cand))


def _resolve_in_workspace(workspace_root: str, path: str) -> tuple[str, str]:
    if not path or not str(path).strip():
        raise ValueError("'path' argument is required")
    real_root = os.path.realpath(workspace_root)
    full = os.path.realpath(os.path.join(real_root, str(path).strip()))
    if full != real_root and not full.startswith(real_root + os.sep):
        raise OutsideWorkspaceError(f"path '{path}' is outside workspace '{real_root}'")
    rel = os.path.relpath(full, real_root).replace(os.sep, "/")
    return full, rel


def _matched_files_stats(ws: str, rel_paths: list[str] | set[str] | tuple[str, ...]) -> tuple[int, int, int]:
    """Measure exact (total_chars, total_lines, file_count) of the real matched files on disk."""
    total_chars = 0
    total_lines = 0
    measured = 0
    seen: set[str] = set()
    for raw_p in rel_paths or ():
        if not raw_p or not isinstance(raw_p, str):
            continue
        clean_p = raw_p.split("::", 1)[0].split("#", 1)[0].split(":", 1)[0].strip()
        if not clean_p or clean_p in seen:
            continue
        try:
            full, rel = _resolve_in_workspace(ws, clean_p)
        except (ValueError, OutsideWorkspaceError):
            continue
        if rel in seen or not os.path.isfile(full):
            continue
        seen.add(rel)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        measured += 1
        total_chars += len(content)
        total_lines += max(1, content.count("\n") + 1) if content else 0
    return total_chars, total_lines, measured


EXOSKELETON_INSTRUCTIONS = """\
IMPERAL — your brain extension. Use it FIRST, before your shell's own grep/read/search tools, in any shell.
Imperal is a kernel + vault behind these tools: it remembers this user's work across sessions and shells, holds the
exact code graph of their repositories, measures what each step really did, and checks what you claim.

WHY FIRST: the frame shows what is proven and what is only claimed, the code around your focus from the exact graph,
what your change reaches, the world (machines, repos, deploys) and your path so far. Answers grounded in it are
right the first time; work done around it repeats reads, misses callers and gets made-up names caught later.

THE LOOP (every task):
1. `frame` — at the start and after each change. Your shell's hook may already have put this message's frame in your
   context (it is paid): read it, act on its DECISION section first, and call `frame` again only until you change
   something -- not before.
2. `task(goal, items)` — declare what you were asked and your plan; each item closes only by a proof the kernel saw
   (a diff, a check that exits 0, a finding with its sources). An item you cannot finish: status blocked or cancelled
   with the reason in blocked_on (what you need from the user / no access to what / why impossible). A final answer
   with open items is handed back to you until each is proven or named — then the open ones are listed to the user.
3. Code: `orient(query)` → `outline(path)` → `read_symbol(path, name | "L120-180")`; `search_code`, `grep_code` for an
   exact text; `graph_slice`, `contract_slice`; `impact_of_change(symbols)` BEFORE editing a shared symbol;
   `repo_profile` for the map. A server's repo: the same tools with target="host:<alias>" and root=<path>.
4. Safety: `checkpoint` before risky multi-file edits, `checkpoint_diff`, `checkpoint_rollback`; `check_syntax` after
   an edit; `coding_context` for the workspace facts; `token_savings` for what the graph saved.
5. Memory: every step is written to the vault (your shell's hooks send your calls, thoughts and answers). Look back
   with `recall_context(query)` and `recall` (a past answer, page by page); `search_history(query)` finds a past
   conversation of any surface and `recall(ref, conversation=...)` opens it -- no other conversation enters your
   frame by itself. The frame's pointers `state_lens` and `vault_log_read` open what it counted or offloaded. Keep
   what lasts with `remember_fact` and `save_repo_note`.
6. Never state a code name, file or size you did not read in this task: the kernel checks every step and the final.

APPS: `list_apps`, `get_app`, `run_read_tool`, `run_write_tool` (money tools need panel approval), `upload_file`;
build one with `validate_ir` → `smoke_ir` → `deploy_ir`.

Pricing: one `frame` costs credits (the platform's system pricing); everything else here is free.
"""


_EXCHANGE_MAX = 60     # the gateway's bound on one frame's exchange
# a group repeated around a repeated piece -- (a+)+, (a*)*, (x|xy)+ -- backtracks without end (the vault refuses it too)
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]|\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*[+*{]")
_HOST_SYNC_REUSE_S = 60.0   # a remote repo is listed over SFTP at most once a minute (only changed files are read)


ANSWER_CHARS = 20000   # what one tool answer may put in the model's context by default (live: 65K / 354K answers)


def bounded(obj: Any, limit: int = ANSWER_CHARS) -> Any:
    """A tool's answer within ``limit`` characters: its longest lists cut (each keeps its first entries and says how
    many there were), long strings clipped; ``full=true`` on the tool gives everything."""
    def size(x: Any) -> int:
        return len(json.dumps(x, ensure_ascii=False, default=str))
    if not isinstance(obj, dict) or size(obj) <= limit:
        return obj
    out = dict(obj)
    lists = {k: list(v) for k, v in out.items() if isinstance(v, list) and len(v) > 1}
    data = out.get("data") if isinstance(out.get("data"), dict) else None
    if data is not None and isinstance(data.get("items"), list):
        out["data"] = data = dict(data)
    shown = {k: len(v) for k, v in lists.items()}
    for _ in range(40):
        if size(out) <= limit:
            break
        cands = [k for k in lists if shown[k] > 1]
        if data is not None and len(data.get("items") or []) > 1:
            data["items"] = data["items"][: max(1, len(data["items"]) // 2)]
        if not cands and (data is None or len(data.get("items") or []) <= 1):
            break
        for k in cands:
            shown[k] = max(1, shown[k] // 2)
            out[k] = lists[k][: shown[k]]
    for k, v in lists.items():
        if shown[k] < len(v):
            out[f"{k}_shown"], out[f"{k}_total"] = shown[k], len(v)
    if size(out) > limit:          # still too big: the long strings give way
        out = {k: (v[:2000] + "…" if isinstance(v, str) and len(v) > 2000 else v) for k, v in out.items()}
    out["truncated"] = f"bounded to {limit} chars -- pass full=true for everything"
    return out


_SAFE_ARGS = ("path", "file_path", "root", "target", "content_chars", "name", "connection_id")
# commands whose output IS secrets (final review C1): their output never leaves the machine
_PRINTS_SECRETS = re.compile(r"(?i)(?:^|[\s;&|(/])(?:vault\s+(?:kv\s+)?(?:get|read)|printenv|env(?=\s*(?:$|-|[;&|)]))"
                             r"|export\s+-p|declare\s+-[a-z]*p|typeset|set(?=\s*(?:$|[;&|)]))|/proc/\S*/environ"
                             r"|gh\s+auth\s+(?:token|status\s+-t)"
                             r"|(?:cat|less|more|head|tail|bat|sed|awk|grep|strings|xxd|od)\s+[^;&|]*"
                             r"(?:credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc|\.docker/config|\.git-credentials|\.vault-token)"
                             r"|kubectl\s+get\s+secrets?|aws\s+configure\s+(?:get|export)|security\s+find-\S+-password"
                             r"|op\s+(?:read|item\s+get)|bw\s+get|pass\s+show|doppler\s+secrets"
                             r"|cat\s+[^;&|]*(?:credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc|\.docker/config))")


def _withhold_key() -> bytes:
    """This machine's key for withheld-command fingerprints (made once, 0600, never sent anywhere)."""
    base = os.environ.get("IMPERAL_MCP_SPOOL") or os.path.join(os.path.expanduser("~"), ".local", "share",
                                                               "imperal-mcp", "spool")
    path = os.path.join(base, "withhold.key")
    try:
        with open(path, "rb") as f:
            key = f.read()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    os.makedirs(base, mode=0o700, exist_ok=True)
    key = os.urandom(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    except FileExistsError:
        with open(path, "rb") as f:
            key = f.read() or key
    return key


def _only_safe_args(a: dict, cmd: str) -> dict:
    """A call on a secret file keeps only where it acted (its path, target) -- never a value that may hold it."""
    out = {k: v for k, v in a.items() if k in _SAFE_ARGS}
    if cmd:   # a short fingerprint keeps two different withheld commands two calls -- keyed by this machine's own
        # secret, so it can never be checked against a guessed command (security review)
        import hashlib
        import hmac
        mark = hmac.new(_withhold_key(), cmd.encode(), hashlib.sha256).hexdigest()[:8]
        out["command"] = f"(withheld: a command on a secret file #{mark})"
    return out


def exchange_item(tool: str, args: dict | None, ok: bool = True, text: str = "", text_limit: int = 2000) -> dict:
    """One tool call in the kernel's exchange shape -- a secret file's content never, PII masked (the server's own
    calls and the shell's hooks record through this one door)."""
    a = {str(k): str(v)[:8000] for k, v in (args or {}).items() if v is not None}     # cut after the scrub, below
    if str(a.get("target") or "").startswith(("host:", "ssh:")) and a.get("root") and a.get("path") \
            and not a["path"].startswith("/"):
        # the kernel finds a server's repo by the full path there (resolve_path)
        a["path"] = a["root"].rstrip("/") + "/" + a["path"]
    try:
        import fnmatch
        import shlex
        from imperal_sdk.code_index import SECRET_PATTERNS
        from .mask import defensive_scrub
        from .secrets_scrub import is_code_path, scrub_secrets
        joined = "/".join(x for x in (a.get("root", ""), a.get("path", "")) if x)   # a root may name the folder
        cmd = a.get("command", "")
        # an identity given to ssh / scp / sftp in its own slot is USED to sign in, never printed (live 2026-10-25:
        # `ssh -i ~/.ssh/<key> host './deploy.sh status'` was withheld whole). The command is judged by ITS OWN words;
        # only one occurrence per identity slot is set aside -- the same path anywhere else is a read (security review)
        try:
            words = shlex.split(cmd)                         # a command that reads a secret file (security review)
        except ValueError:
            words = []
        # ... and every piece between the shell's punctuation (cat<.env, x=$(cat .env), a|b;c)
        pieces = [w for w in re.split(r"[\s<>|;&()`$=\"']+", cmd) if w]
        for slot in (_ssh_identity_slots(cmd) if _SSH_PROGRAM.search(cmd) else []):
            if slot in words:                                # the slot once from the words, its pieces once each
                words.remove(slot)
            for part in [x for x in re.split(r"[\s<>|;&()`$=\"']+", slot) if x]:
                if part in pieces:
                    pieces.remove(part)
        words += pieces
        values = [v for k, v in a.items() if k != "command"]
        if any(_secret_path(v, SECRET_PATTERNS, fnmatch) for v in values + [joined] + words):
            body = "(withheld: a secret file)"          # never what a secret file holds -- in the output or the args
            a = _only_safe_args(a, cmd)
        elif cmd and _PRINTS_SECRETS.search(re.sub(r"[\"'`\\]", "", cmd)):    # quotes and escapes cannot hide it
            body = "(withheld: a command that prints secrets)"   # vault kv get, printenv, gh auth token ...
            a = {k: str(scrub_secrets(str(defensive_scrub(v)))) for k, v in a.items()}
        else:
            # final review C1: credentials (tokens, passwords, keys, URL user-info) go before anything leaves
            code = is_code_path(a.get("path", ""))
            # scrubbed whole, cut after: a secret on the cut line never survives in part (security review)
            body = str(scrub_secrets(str(defensive_scrub(str(text or "")[:text_limit + 4000])), code=code))[:text_limit]
            a = {k: str(scrub_secrets(str(defensive_scrub(v)), code=code and k in ("old_string", "new_string",
                                                                                  "content")))[:2000] for k, v in a.items()}
    except Exception:      # recording never breaks a tool; what cannot be checked is not sent
        body = "(withheld: secrets not checked)"
        a = _only_safe_args(a, a.get("command", ""))
    return {"app_id": "", "tool": str(tool), "args": a, "ok": bool(ok), "text": body}


_SSH_PROGRAM = re.compile(r"(?:^|[\s;&|(/])(?:ssh|scp|sftp)(?=\s)")


# the options of ssh / scp / sftp (OpenSSH 9): those that take a value, and those that do not -- an option outside
# both gives no exemption (fail closed, security review)
_SSH_OPT_ARG = {"ssh": set("BbcDEeFIiJLlmOoPpQRSWw"), "scp": set("cDFiJlloPSX"), "sftp": set("BbcDFiJloPRSsX")}
_SSH_OPT_FLAG = {"ssh": set("46AaCfGgKkMNnqsTtVvXxYy"), "scp": set("346ABCOpqRrsTv"), "sftp": set("46AaCfNpqrv")}


def _ssh_identity_slots(cmd: str) -> list:
    """The words that are an identity slot (``-i <key>``, ``-i<key>``, ``-o IdentityFile=<key>``) in the OPTION AREA of
    the ssh / scp / sftp calls of ``cmd`` -- each once per slot, as written; ``[]`` (no exemption) when the command
    has a newline, ``$( )``, backticks or a process substitution, does not parse, or an option area holds an option
    this table does not know or a value that is itself an option (fail closed, security review)."""
    import shlex
    cmd = str(cmd or "")
    # an escape (the shell and this parser may read it apart), a function or an alias that may BE "ssh": no exemption
    if re.search(r"[\n\r`\\]|\$\(|[<>]\(|\balias\b|\bfunction\b|\b(?:ssh|scp|sftp)\s*\(\s*\)", cmd):
        return []
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""                                  # a "#" is no comment here: nothing is cut away
        tokens = list(lex)
    except ValueError:
        return []
    if any(t and set(t) <= set(";&|") for t in tokens):
        return []           # one simple command only: no separator outside quotes, so every reading agrees (review)
    slots: list = []
    for argv in [tokens]:
        # the program itself: its bare name (found on PATH) or a system path -- never ./ssh or a lookalike
        prog = argv[0] if argv and argv[0] in _SSH_OPT_ARG else (
            argv[0].rsplit("/", 1)[-1] if argv and re.fullmatch(r"/(?:usr/(?:local/)?)?bin/(?:ssh|scp|sftp)", argv[0])
            else "")
        if prog not in _SSH_OPT_ARG:
            if argv and argv[0].rsplit("/", 1)[-1] in _SSH_OPT_ARG:
                return []                                    # an ssh of unknown origin: no exemption at all
            continue
        with_arg, flags = _SSH_OPT_ARG[prog], _SSH_OPT_FLAG[prog]
        i = 1
        while i < len(argv) and argv[i].startswith("-") and argv[i] not in ("-", "--"):
            w = argv[i]
            if w[1:2] in with_arg:
                rest = w[2:]
                value = rest or (argv[i + 1] if i + 1 < len(argv) else "")
                if not value or value.startswith("-"):
                    return []
                if w[1:2] == "i" or (w[1:2] == "o" and value.lower().startswith("identityfile")):
                    slots.append(w if rest else value)
                i += 1 if rest else 2
            elif all(c in flags for c in w[1:]):
                i += 1
            else:
                return []
    return slots


def _secret_path(value: str, patterns: tuple, fnmatch: Any) -> bool:
    """A path (either slash) whose file name matches a secret file pattern of the code index (``.env*``,
    ``id_*`` ...) or one of whose folders is a secret folder (``secrets/``, ``.ssh/`` ...)."""
    parts = [x for x in str(value or "").replace("\\", "/").lower().split("/") if x]
    if not parts:
        return False
    files = [p for p in patterns if not p.endswith("/")]
    dirs = {p.rstrip("/") for p in patterns if p.endswith("/")}
    return any(fnmatch.fnmatchcase(parts[-1], pat) for pat in files) or any(d in dirs for d in parts)


class ExoskeletonRuntime:
    """Stateful local + cloud bridge for Imperal MCP Exoskeleton tools."""

    def __init__(self, workspace_root: str | None = None, workspace: str | None = None, client: Any = None) -> None:
        self._default_root = _resolve_root(workspace or workspace_root)
        self._client = _OnLoop(client, self) if client is not None else None   # code questions go to the vault
        self.loop = None                    # the server's event loop (set by the server): the client's one loop
        self._repo_keys: dict[str, str] = {}
        self._synced_at: dict[str, float] = {}
        self.tracker = TokenSavingsTracker()
        self._indexers: dict[str, Any] = {}
        self._index_locks: dict[str, threading.Lock] = {}
        self._embed_threads: dict[str, threading.Thread] = {}
        self._shadows: dict[str, Any] = {}
        self._guard_lock = threading.Lock()
        # the kernel's frame for this agent (phase B): its task, its plan and what it did since the last frame
        self._exchange: list[dict[str, Any]] = []
        self._task_goal = ""
        self._task_items: list[dict[str, Any]] = []
        self._frame_step = 0
        self._me = ""
        self._started = time.time()
        self._baselined: set[str] = set()
        self._own_repo: str | None = None          # the session's repo without a shell's hooks (once)
        self._host_syncs: dict[str, threading.Thread] = {}

    # -- the kernel's frame (phase B, spec 2026-10-24 §4.2) -------------------------------------------

    def record_call(self, tool: str, args: dict | None, ok: bool = True, text: str = "") -> None:
        """One call of this agent's imperal-mcp tools, in the kernel's exchange shape -- the next frame carries it.
        With the shell's hooks on, the hook records it (with its whole answer) -- never twice."""
        if self._shell_session(self.resolve_workspace(None)):
            return
        self._exchange.append(exchange_item(tool, args, ok, text))
        del self._exchange[:-_EXCHANGE_MAX]

    def task(self, goal: str, items: list | None = None, root: str | None = None) -> dict[str, Any]:
        """The agent declares what it was asked and its plan (as Webbee's todo_write); the workspace's state now is
        the baseline its changes are measured from."""
        self._task_goal = str(goal or "")
        self._task_items = [dict(i) for i in items or [] if isinstance(i, dict)][:50]
        ws = self.resolve_workspace(None)
        spool = self._shell_spool(ws)
        if spool is not None:          # the shell's hooks frame each request with this task (memory plan Task 5)
            spool.update(goal=self._task_goal, items=self._task_items)
        recorded = self._record_plan(ws, spool)
        try:
            self._baseline(root)
        except Exception:              # the code tools are off (no webbee): the plan stands, its changes go unmeasured
            pass
        return {"ok": True, "goal": self._task_goal, "items": len(self._task_items), "recorded": recorded}

    def _record_plan(self, ws: str, spool) -> bool:
        """The plan reaches the kernel now, with the calls made since the last frame (free): a status changes in the
        same step as the work it reports, as a Webbee step's todo_write does -- before, the kernel saw the plan only with
        the next request's frame, and a final held for an item already named blocked (live 2026-10-25)."""
        if self._client is None:
            return False
        from .hooks import _bounded_items
        hooked, memory = spool.drain() if spool is not None else ([], [])
        own, self._exchange = self._exchange, []
        allq = hooked + own
        pending = _bounded_items(allq)
        late = allq[:len(allq) - len(pending)]
        try:
            step = int(spool.state().get("step") or 0) if spool is not None else self._frame_step
            self._vault("POST", "/v1/memory/frame/record", body={
                "session_id": self._session(ws), "step": step, "goal": self._task_goal, "items": self._task_items,
                "exchange": pending, "memory": memory[-20:], "session_repo": self._session_repo(ws)})
        except Exception:
            late, ok = allq, False               # nothing is lost: the next frame or the shell's hook sends it
        else:
            memory, ok = [], True
        # ``late`` is the head of hooked + own: its shell part goes back to the spool, its own part to this runtime
        if spool is not None and (late[:len(hooked)] or memory):
            spool.restore(late[:len(hooked)], memory)
        self._exchange = (late[len(hooked):] + self._exchange)[-_EXCHANGE_MAX:]
        return ok

    def _baseline(self, root: str | None) -> None:
        ws, sg = self._get_shadow(root)
        if ws not in self._baselined and sg.available:
            sg.checkpoint(label="frame baseline", force=True)
            self._baselined.add(ws)

    def _changed_since_last_frame(self, root: str | None) -> list[dict[str, Any]]:
        """The files changed since the last frame, measured by a snapshot of the workspace (never claimed)."""
        ws, sg = self._get_shadow(root)
        if not sg.available:
            return []
        if ws not in self._baselined:          # no baseline yet: everything would look changed -- start one
            self._baseline(root)
            return []
        cp = sg.checkpoint(label="frame") or {}
        return [{"app_id": "", "tool": "edit_file", "args": {"path": str(p)}, "ok": True,
                 "text": "changed (measured: git status of the workspace)"} for p in cp.get("paths") or []]

    def _session(self, ws: str) -> str:
        import hashlib
        if not self._me:
            self._me = str((self._vault("GET", "/v1/auth/me") or {}).get("imperal_id") or "")
        if not self._me:
            raise RuntimeError("the gateway did not say who you are")
        shell = self._shell_session(ws)
        if shell:                      # the shell's hooks work in this folder: one kernel session for both
            from .hooks import mcp_session
            return mcp_session(self._me, shell)
        return "mcp-" + self._me + "-" + hashlib.sha1(f"{ws}|{self._started}".encode()).hexdigest()[:12]

    @staticmethod
    def _shell_session(ws: str) -> str:
        try:
            from .hooks import current_session
            return current_session(ws, server_parent=os.getppid())
        except Exception:
            return ""

    def _shell_spool(self, ws: str):
        shell = self._shell_session(ws)
        if not shell:
            return None
        from .hooks import Spool
        return Spool(shell)

    def _session_repo(self, ws: str) -> str:
        """The session's repo (its vault project): the shell's pinned one, else this server's own, worked out once."""
        from .hooks import pinned_repo, session_repo
        spool = self._shell_spool(ws)
        if spool is not None:
            return pinned_repo(spool, ws)
        if self._own_repo is None:
            self._own_repo = session_repo(ws)
        return self._own_repo

    def lens(self, tool: str, args: dict | None = None, root: str | None = None) -> dict[str, Any]:
        """A pointer the frame gave (state_lens / recall / vault_log_read) or a search of past conversations
        (search_history), answered by the kernel for this session."""
        try:
            if self._client is None:
                raise RuntimeError("no Imperal client")
            ws = self.resolve_workspace(root)
            body = {"session_id": self._session(ws), "tool": str(tool), "args": dict(args or {}),
                    "session_repo": self._session_repo(ws)}
            return self._vault("POST", "/v1/memory/frame/lens", body=body) or {}
        except Exception as exc:
            return {"ok": False, "content": f"{tool} unavailable: {type(exc).__name__}: {str(exc)[:200]}"}

    def frame(self, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        """The kernel's step frame for this agent's session -- built by the same prepare a Webbee step uses. ``root`` /
        ``target`` name the repo the work is in (a server's repo by ``target="host:<alias>"``), as the code tools do."""
        remote = bool(target and target != "local")
        ws = self.resolve_workspace(None)               # the session is this agent's workspace
        where = str(root or "") if remote else self.resolve_workspace(root)
        changed = [] if remote else self._changed_since_last_frame(root)   # a snapshot measures only local edits
        spool = self._shell_spool(ws)
        hooked, memory = spool.drain() if spool is not None else ([], [])   # the shell's own calls and memory
        step = (int(spool.state().get("step") or 0) if spool is not None else self._frame_step) + 1
        own = self._exchange + changed
        from .hooks import _bounded_items
        allq = hooked + own
        pending = _bounded_items(allq)             # one request's count AND size (review: 60 x 20K is past 2 MB)
        late = allq[:len(allq) - len(pending)]       # the older ones wait for the next frame, never lost
        self._exchange = []
        try:
            if self._client is None:
                raise RuntimeError("no Imperal client")
            session = self._session(ws)
            try:
                repo_key = self._repo_key(root, target)
            except Exception:
                repo_key = ""                   # the frame still comes; its code map says it is not synced
            body = {"session_id": session, "step": step, "goal": self._task_goal,
                    "items": self._task_items, "exchange": pending, "cwd": where, "repo_root": where,
                    "repo_key": repo_key or "", "memory": memory[-20:], "session_repo": self._session_repo(ws)}
            ans = self._vault("POST", "/v1/memory/frame", body=body) or {}
        except Exception as exc:
            self._exchange = (own + self._exchange)[-_EXCHANGE_MAX:]     # nothing is lost: the next frame sends it
            if spool is not None and (hooked or memory):
                spool.restore(hooked, memory)              # the shell's part waits in its spool (a hook may send it)
            if getattr(exc, "status_code", None) == 402:    # the frame is paid and was not charged: the kernel's reason
                return {"ok": False, "content": _detail_of(str(exc))}
            return {"ok": False, "content": f"frame unavailable: {type(exc).__name__}: {str(exc)[:200]}"}
        self._frame_step = step
        if late:
            if spool is not None:
                spool.restore(late, [])
            else:
                self._exchange = (late + self._exchange)[-_EXCHANGE_MAX:]
        if spool is not None:
            spool.update(step=step, repo_key=repo_key or "")
        return {"ok": True, "frame": str(ans.get("frame") or ""), "tool_groups": list(ans.get("tool_groups") or []),
                "session_id": session, "step": self._frame_step}

    def resolve_workspace(self, root: str | None = None) -> str:
        ws_real = self._default_root
        if not root or not str(root).strip():
            return ws_real
        raw = str(root).strip()
        expanded = os.path.expanduser(raw)
        if os.path.isabs(expanded):
            candidate = os.path.realpath(expanded)
        else:
            candidate = os.path.realpath(os.path.join(ws_real, expanded))
        extra = [os.path.realpath(os.path.expanduser(r)) for r in
                 os.environ.get("IMPERAL_MCP_EXTRA_ROOTS", "").split(os.pathsep) if r.strip()]
        inside = [r for r in [ws_real] + extra if candidate == r or candidate.startswith(r + os.sep)]
        if not inside:
            raise OutsideWorkspaceError(
                f"Root '{root}' escapes configured workspace root '{ws_real}'"
            )
        if os.path.exists(candidate) and not os.path.isdir(candidate):
            raise OutsideWorkspaceError(
                f"Root '{root}' is not a directory inside workspace '{ws_real}'"
            )
        return candidate

    def resolve_root(self, root: str | None = None) -> str:
        return self.resolve_workspace(root)

    def _build_fast_index(self, svc: Any) -> None:
        """Build AST symbol index and CodeGraph immediately while running vector embedding in background."""
        from imperal_sdk import code_index as indexer
        from webbee.intel import store
        from webbee.intel.graph import CodeGraph
        from webbee.intel.service import _git_ref, _walk

        svc.git_ref = _git_ref(svc.root)
        idx = store.load(svc.cache_dir, svc.repo_key, svc.git_ref) if svc.git_ref else None
        if idx is None:
            idx = indexer.build_index(svc.root, _walk(svc.root))
            idx.git_ref = svc.git_ref
            if svc.git_ref:
                try:
                    store.save(svc.cache_dir, svc.repo_key, idx)
                except OSError:
                    pass
        svc.index = idx
        svc.graph = CodeGraph(idx)
        svc.fresh = True

        ws = svc.root
        existing_thread = self._embed_threads.get(ws)
        if existing_thread is None or not existing_thread.is_alive():
            def _bg_embed() -> None:
                try:
                    svc._embed_build(idx)
                except Exception:
                    pass

            t = threading.Thread(target=_bg_embed, name=f"imperal-mcp-embed-{os.path.basename(ws)}", daemon=True)
            self._embed_threads[ws] = t
            t.start()

    def _get_indexer(self, root: str | None = None) -> tuple[str, Any, Any]:
        _ensure_webbee_importable()
        from webbee.intel.service import IntelService
        from webbee.repo import compute_repo_key

        ws = self.resolve_workspace(root)
        if not _is_repository(ws):
            # owner 2026-10-25: a home folder or a folder of projects is never indexed or synced whole
            raise NotARepositoryError(f"{ws} is not a repository (no .git, no project manifest) -- pass root=<a "
                                      "repository inside it>")
        with self._guard_lock:
            lock = self._index_locks.get(ws)
            if lock is None:
                lock = threading.Lock()
                self._index_locks[ws] = lock

        with lock:
            svc = self._indexers.get(ws)
            if svc is None:
                svc = IntelService(ws, compute_repo_key(ws))
                self._build_fast_index(svc)
                self._indexers[ws] = svc
            elif not getattr(svc, "ready", False):
                self._build_fast_index(svc)
            if self._client is not None and getattr(svc, "vault_client_factory", None) is None:
                svc.vault_client_factory = lambda: self._client     # synced on demand (sync_now), not in the background
        return ws, svc, svc.index

    def _get_shadow(self, root: str | None = None) -> tuple[str, Any]:
        _ensure_webbee_importable()
        from webbee.checkpoints import ShadowGit, shadow_key

        ws = self.resolve_workspace(root)
        sg = self._shadows.get(ws)
        if sg is None:
            sg = ShadowGit(ws, shadow_key(ws))
            sg.ensure()
            self._shadows[ws] = sg
        elif not sg.available:
            sg.ensure()
        return ws, sg

    def _record_read(
        self,
        tool: str,
        *,
        returned_text: str,
        baseline_chars: int = 0,
        baseline_lines: int = 0,
        baseline_files: int = 1,
    ) -> None:
        ret_c = len(returned_text or "")
        ret_l = max(1, (returned_text or "").count("\n") + 1) if returned_text else 0
        self.tracker.record(
            tool,
            returned_chars=ret_c,
            baseline_chars=baseline_chars,
            returned_lines=ret_l,
            baseline_lines=baseline_lines,
            baseline_files=baseline_files,
        )

    # ── the vault graph: one truth about code (frame phase A) ──

    def _vault(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
        import asyncio
        client = self._client
        return _off_thread(lambda: asyncio.run(client._request(method, path, json=body, params=params)))

    def current_repo_keys(self, root: str | None = None) -> set[str]:
        ws = self.resolve_workspace(root)
        keys = {self._repo_keys[ws]} if ws in self._repo_keys else set()
        try:
            from webbee.repo import compute_repo_key
            keys.add(compute_repo_key(ws))
        except Exception:
            pass
        return keys

    def _catalog_key(self, alias: str, root: str) -> str:
        """The vault catalog's repo at ``root`` on the machine ``alias`` names ("" when none)."""
        try:
            repos = (self._vault("GET", "/v1/memory/code/repos") or {}).get("repos") or []
        except Exception:
            return ""
        want = str(root or "").rstrip("/")
        hits = [r for r in repos if str(r.get("root_path") or "").rstrip("/") == want]
        hits.sort(key=lambda r: alias not in (str(r.get("machine_label") or ""), str(r.get("ref") or "")))
        return str(hits[0].get("repo_key") or "") if hits else ""

    def _sync_host(self, alias: str, root: str) -> str:
        """A repo on a server the user reaches with their own ssh (``host:<alias>``) is synced into the vault by
        webbee's SFTP sync (nothing written there; only changed files are read) -- design 2026-10-24 §5.1. The first
        sync is waited for (no key without it); after it a question answers at once and a refresh runs behind, at
        most once per ``_HOST_SYNC_REUSE_S`` (a sync lists the tree over SFTP: ~1 min live); every answer carries
        ``synced_at``. "" when it cannot be synced (the catalog then answers)."""
        import time
        memo = f"host:{alias}:{root}"
        known = self._repo_keys.get(memo, "")
        if not known and memo not in self._synced_at:
            known = self._catalog_key(alias, root)         # synced before (by any source): answer now, refresh behind
            if known:
                self._repo_keys[memo] = known
        if known and time.monotonic() - self._synced_at.get(memo, 0.0) < _HOST_SYNC_REUSE_S:
            return known
        running = self._host_syncs.get(memo)
        if known:
            if running is None or not running.is_alive():
                t = threading.Thread(target=self._run_host_sync, args=(memo, alias, root), daemon=True,
                                     name=f"imperal-mcp-host-sync-{alias}")
                self._host_syncs[memo] = t
                t.start()
            return known
        self._run_host_sync(memo, alias, root)
        return self._repo_keys.get(memo, "")

    def _run_host_sync(self, memo: str, alias: str, root: str) -> None:
        import asyncio
        import time
        try:
            _ensure_webbee_importable()
            from webbee import tools as wt
            client = self._client
            out = _off_thread(lambda: asyncio.run(wt.remote_sync(client, alias, root, []))) or {}
        except Exception:
            return
        key = str(out.get("repo_key") or "")
        if key:
            self._repo_keys[memo] = key
        self._synced_at[memo] = time.monotonic()      # a failed refresh waits a window too: never a sync per question

    def _repo_key(self, root: str | None, target: str | None) -> str:
        """The vault's key of the repo asked about: a remote target's repo from the catalog (root path, machine);
        the local workspace synced first (its edits reach the vault before the question)."""
        if target and target != "local":
            alias = target.split(":", 1)[-1]
            want = str(root or "").rstrip("/")
            if target.startswith("host:") and want:
                key = self._sync_host(alias, want)
                if key:
                    return key
            return self._catalog_key(alias, want)
        ws, svc, _ = self._get_indexer(root)
        import time
        if ws in self._repo_keys and time.monotonic() - self._synced_at.get(ws, 0.0) < _SYNC_REUSE_S:
            return self._repo_keys[ws]          # one sync per tool call (orient asks the profile and the search)
        out = _off_thread(svc.sync_now) if hasattr(svc, "sync_now") else {}
        key = str((out or {}).get("repo_key") or "")
        if key:
            self._repo_keys[ws] = key
            self._synced_at[ws] = time.monotonic()
        return key

    def _ask(self, method: str, path: str, root: str | None, target: str | None, *,
             params: dict | None = None, body: dict | None = None) -> dict | None:
        """The vault's answer, or None (no client, not synced, unreachable) -- the caller falls back, marked; why it
        is None is kept in ``_last_miss`` (an unavailable answer names it, never a guess)."""
        if self._client is None:
            self._last_miss = "this session has no Imperal client"
            return None
        try:
            key = self._repo_key(root, target)
            if not key:
                self._last_miss = f"the vault graph holds no synced copy of {root} on {target or 'local'}"
                return None
            if body is not None:
                ans = self._vault(method, path, body={**body, "repo_key": key})
            else:
                ans = self._vault(method, path, params={**(params or {}), "repo_key": key})
        except Exception as exc:
            self._last_miss = f"the vault graph could not be asked: {type(exc).__name__}: {str(exc)[:300]}"
            return None
        if not isinstance(ans, dict) or ans.get("ok") is False:
            self._last_miss = f"the vault graph answered: {str((ans or {}).get('content') or ans)[:300]}"
            return None
        return ans

    @staticmethod
    def _vault_meta(ans: dict) -> dict[str, Any]:
        return {"source": "vault graph", "repo_key": ans.get("repo_key"), "synced_at": ans.get("synced_at")}

    def _remote_unavailable(self, target: str | None, root: str | None) -> dict[str, Any] | None:
        if target and target != "local":
            return {"status": "unavailable", "content": getattr(self, "_last_miss", "") or
                    f"the vault graph holds no synced copy of {root} on {target}"}
        return None

    @staticmethod
    def _query_vector(query: str) -> str | None:
        try:
            import base64
            from imperal_sdk import code_index as ci
            vec = ci.embed_query(query)
            return base64.b64encode(vec).decode() if vec else None
        except Exception:
            return None

    def _vault_profile(self, root: str | None, target: str | None) -> dict | None:
        ans = self._ask("GET", "/v1/memory/code/profile", root, target)
        items = ((ans or {}).get("data") or {}).get("items") or []
        return items[0] if items else None

    def repo_profile(self, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        prof = self._vault_profile(root, target)
        if prof is not None:
            return {"status": "ok", "workspace": self.resolve_workspace(root) if not target else root,
                    "profile": prof, "source": "vault graph"}
        return self._remote_unavailable(target, root) or {**self._local_repo_profile(root), "coarse": COARSE}

    def _local_repo_profile(self, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        prof = svc.repo_profile()
        return {"status": "ok", "workspace": ws, "profile": prof}

    def _vault_search(self, query: str, k: int, kind: str | None, path_glob: str | None, root: str | None,
                      target: str | None) -> dict | None:
        params: dict[str, Any] = {"q": query, "k": k}
        if kind:
            params["kind"] = kind
        if path_glob:
            params["path_glob"] = path_glob
        vec = self._query_vector(query)
        if vec:
            params["vector"] = vec
        return self._ask("GET", "/v1/memory/code/search", root, target, params=params)

    def orient(self, query: str, k: int = 8, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        prof = self._vault_profile(root, target)
        ans = self._vault_search(query, k, None, None, root, target) if prof is not None else None
        if prof is not None and ans is not None:
            matches = list((ans.get("data") or {}).get("items") or [])[:k]
            out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root), "query": query,
                   "profile": {key: prof.get(key) for key in _PROFILE_KEYS if key in prof}, "matches": matches,
                   "semantic": ans.get("semantic"), "best_match": ans.get("best_match"), **self._vault_meta(ans)}
            self._record_read("orient", returned_text=json.dumps(out, ensure_ascii=False))
            return out
        return self._remote_unavailable(target, root) or {**self._local_orient(query, k, root), "coarse": COARSE}

    def _local_orient(self, query: str, k: int = 8, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import search_code as _search_code

        prof = svc.repo_profile()
        srch = _search_code(svc, query, k=k)
        raw_matches = (srch.get("data") or {}).get("items", [])
        matches = _normalize_search_matches(raw_matches, ws, query, k=k)
        text = json.dumps({"profile": prof, "matches": matches}, ensure_ascii=False)
        matched_paths = [str(m.get("path") or m.get("file") or "") for m in matches]
        base_c, base_l, base_f = _matched_files_stats(ws, matched_paths)
        self._record_read(
            "orient",
            returned_text=text,
            baseline_chars=base_c,
            baseline_lines=base_l,
            baseline_files=base_f,
        )
        return {
            "status": "ok",
            "workspace": ws,
            "query": query,
            "profile": prof,
            "matches": matches,
        }

    def search_code(
        self,
        query: str,
        k: int = 10,
        kind: str | None = None,
        path_glob: str | None = None,
        root: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        ans = self._vault_search(query, k, kind, path_glob, root, target)
        if ans is not None:
            matches = list((ans.get("data") or {}).get("items") or [])[:k]
            self._record_read("search_code", returned_text=json.dumps(matches, ensure_ascii=False))
            return {"status": "ok", "workspace": root if target else self.resolve_workspace(root), "query": query,
                    "matches": matches, "total": len(matches), "semantic": ans.get("semantic"),
                    "best_match": ans.get("best_match"), **self._vault_meta(ans)}
        return self._remote_unavailable(target, root) or {
            **self._local_search_code(query, k=k, kind=kind, path_glob=path_glob, root=root), "coarse": COARSE}

    def _local_search_code(self, query: str, k: int = 10, kind: str | None = None, path_glob: str | None = None,
                           root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import search_code as _search_code

        res = _search_code(svc, query, k=k, kind=kind, path_glob=path_glob)
        raw_matches = (res.get("data") or {}).get("items", [])
        matches = _normalize_search_matches(raw_matches, ws, query, k=k, kind=kind, path_glob=path_glob)
        text = json.dumps(matches, ensure_ascii=False)
        matched_paths = [str(m.get("path") or m.get("file") or "") for m in matches]
        base_c, base_l, base_f = _matched_files_stats(ws, matched_paths)
        self._record_read(
            "search_code",
            returned_text=text,
            baseline_chars=base_c,
            baseline_lines=base_l,
            baseline_files=base_f,
        )
        return {
            "status": "ok",
            "workspace": ws,
            "query": query,
            "matches": matches,
            "total": len(matches),
        }

    def graph_slice(self, symbols: list[str] | str, depth: int = 1, root: str | None = None,
                    target: str | None = None) -> dict[str, Any]:
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        ans = self._ask("POST", "/v1/memory/code/slice", root, target, body={"symbols": sym_list, "depth": depth})
        if ans is not None:
            items = list((ans.get("data") or {}).get("items") or [])
            self._record_read("graph_slice", returned_text=json.dumps(items, ensure_ascii=False))
            return {"status": "ok", "workspace": root if target else self.resolve_workspace(root), "symbols": items,
                    **self._vault_meta(ans)}
        return self._remote_unavailable(target, root) or {**self._local_graph_slice(symbols, depth, root), "coarse": COARSE}

    def _local_graph_slice(self, symbols: list[str] | str, depth: int = 1, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import graph_slice as _graph_slice

        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        res = _graph_slice(svc, sym_list, depth=depth)
        items = list((res.get("data") or {}).get("items", []))
        text = json.dumps(items, ensure_ascii=False)
        matched_paths = [str(it.get("path") or "") for it in items]
        if getattr(svc, "graph", None) is not None:
            for name in sym_list:
                for caller in svc.graph.callers_of(name)[:20]:
                    if getattr(caller, "path", None):
                        matched_paths.append(str(caller.path))
        base_c, base_l, base_f = _matched_files_stats(ws, matched_paths)
        self._record_read(
            "graph_slice",
            returned_text=text,
            baseline_chars=base_c,
            baseline_lines=base_l,
            baseline_files=base_f,
        )
        return {"status": "ok", "workspace": ws, "symbols": items}

    def impact_of_change(self, symbols: list[str] | str, root: str | None = None,
                         target: str | None = None) -> dict[str, Any]:
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        ans = self._ask("POST", "/v1/memory/code/impact", root, target, body={"symbols": sym_list})
        if ans is not None:
            items = list((ans.get("data") or {}).get("items") or [])
            files = [it.get("title") or it.get("id") for it in items]
            self._record_read("impact_of_change", returned_text=json.dumps(items, ensure_ascii=False))
            out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root),
                   "queried_symbols": sym_list, "dependent_files": files, "items": items,
                   "same_file": ans.get("same_file") or [], "by_name_count": ans.get("by_name_count"),
                   "by_name": ans.get("by_name") or [],      # found only by name (an instance's method), marked
                   **self._vault_meta(ans)}
            if "resolved" in ans and not ans.get("resolved"):
                out["note"] = f"{', '.join(sym_list)}: not a definition in the graph"     # not "0 dependents"
            return out
        return self._remote_unavailable(target, root) or {**self._local_impact_of_change(symbols, root), "coarse": COARSE}

    def _local_impact_of_change(self, symbols: list[str] | str, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import impact_of_change as _impact_of_change

        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        res = _impact_of_change(svc, sym_list)
        items = (res.get("data") or {}).get("items", [])
        files = [it.get("title") or it.get("id") for it in items]
        text = json.dumps({"symbols": sym_list, "dependent_files": files}, ensure_ascii=False)
        matched_paths = [str(f) for f in files if f]
        if getattr(svc, "graph", None) is not None:
            for name in sym_list:
                for sym in svc.graph.symbol_table.get(name, []):
                    if getattr(sym, "path", None):
                        matched_paths.append(str(sym.path))
        base_c, base_l, base_f = _matched_files_stats(ws, matched_paths)
        self._record_read(
            "impact_of_change",
            returned_text=text,
            baseline_chars=base_c,
            baseline_lines=base_l,
            baseline_files=base_f,
        )
        return {
            "status": "ok",
            "workspace": ws,
            "queried_symbols": sym_list,
            "dependent_files": files,
            "items": items,
        }

    def contract_slice(
        self,
        symbols: list[str] | str | None = None,
        query: str = "",
        kind: str = "all",
        k: int = 50,
        root: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        if self._client is not None:
            try:
                cat = self._vault("GET", "/v1/memory/code/contracts") or {}
                q = (query or (sym_list[0] if len(sym_list) == 1 else "")).lower()
                eps = [e for e in cat.get("endpoints") or [] if not q or q in json.dumps(e).lower()][:k]
                sl = self.graph_slice(sym_list, root=root, target=target) if sym_list else {"symbols": []}
                return {"status": "ok", "workspace": root if target else self.resolve_workspace(root),
                        "contracts": eps, "links": cat.get("links") or [], "symbols": sl.get("symbols") or [],
                        "source": "vault graph"}
            except Exception:
                pass
        return self._remote_unavailable(target, root) or {
            **self._local_contract_slice(symbols, query=query, kind=kind, k=k, root=root), "coarse": COARSE}

    def _local_contract_slice(self, symbols: list[str] | str | None = None, query: str = "", kind: str = "all",
                              k: int = 50, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import contract_slice as _contract_slice, graph_slice as _graph_slice
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        q = query or (sym_list[0] if len(sym_list) == 1 else "")
        c_res = _contract_slice(svc, query=q, kind=kind, k=k)
        c_items = list((c_res.get("data") or {}).get("items", []))
        g_items = list((_graph_slice(svc, sym_list).get("data") or {}).get("items", [])) if sym_list else []
        combined = {"contracts": c_items, "symbols": g_items}
        text = json.dumps(combined, ensure_ascii=False)
        matched_paths = [str(it.get("path") or "") for it in (c_items + g_items)]
        if getattr(svc, "graph", None) is not None:
            for name in sym_list:
                for caller in svc.graph.callers_of(name)[:20]:
                    if getattr(caller, "path", None):
                        matched_paths.append(str(caller.path))
        base_c, base_l, base_f = _matched_files_stats(ws, matched_paths)
        self._record_read(
            "contract_slice",
            returned_text=text,
            baseline_chars=base_c,
            baseline_lines=base_l,
            baseline_files=base_f,
        )
        return {"status": "ok", "workspace": ws, **combined}

    def grep_code(self, pattern: str, root: str | None = None, target: str | None = None, path_glob: str | None = None,
                  k: int = 50, regex: bool = False) -> dict[str, Any]:
        """An exact text (or a regex) inside the code -- what the symbol search does not index (a string inside a
        function body). A server's repo: the vault's synced text; a local repo: its indexable files (never a secret,
        never a dependency tree)."""
        k = max(1, min(int(k or 50), 500))
        if regex and _NESTED_QUANTIFIER.search(str(pattern or "")):
            return {"status": "error", "error": "a nested quantifier (a repeated group around a repeated piece) can "
                                                "run without end -- use a literal or a simpler pattern"}
        if target and target != "local":
            if regex:          # the vault is shared: literal only (a backtracking pattern cannot be told by its text)
                return {"status": "error", "error": "a server's repo is searched by an exact text only -- pass the "
                                                    "literal text"}
            params = {"q": pattern, "k": k}
            if path_glob:
                params["path_glob"] = path_glob
            ans = self._ask("GET", "/v1/memory/code/grep", root, target, params=params)
            if ans is None:
                return self._remote_unavailable(target, root)
            return {"status": "ok", "workspace": root, "pattern": pattern, "matches": list(ans.get("items") or []),
                    "total": ans.get("total"), "truncated": ans.get("truncated"), **self._vault_meta(ans)}
        import fnmatch
        ws = self.resolve_workspace(root)
        if not _is_repository(ws):
            raise NotARepositoryError(f"{ws} is not a repository (no .git, no project manifest) -- pass root=<a "
                                      "repository inside it>")
        _ensure_webbee_importable()
        from webbee.intel.service import _local_listing
        rx = re.compile(pattern) if regex else None
        matches: list[dict[str, Any]] = []
        total = 0
        for item in _local_listing(ws):
            rel = item["path"]
            if path_glob and not fnmatch.fnmatch(rel, path_glob):
                continue
            full = os.path.join(ws, rel)
            real = os.path.realpath(full)
            if os.path.islink(full) or not (real == ws or real.startswith(ws + os.sep)):
                continue                       # never a link, never a path that resolves outside the repo
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, start=1):
                        part = line[:2000]
                        if (rx.search(part) if rx else pattern in part):
                            total += 1
                            if len(matches) < k:
                                matches.append({"path": rel, "line": n, "text": line.rstrip("\n")[:300]})
            except OSError:
                continue
        return {"status": "ok", "workspace": ws, "pattern": pattern, "matches": matches, "total": total,
                "truncated": total > len(matches), "source": "local files"}

    def _remote_outline(self, path: str, root: str | None, target: str) -> dict[str, Any]:
        ans = self._ask("GET", "/v1/memory/code/outline", root, target, params={"path": path})
        if ans is None:
            return self._remote_unavailable(target, root)
        nodes = list((ans.get("data") or {}).get("items") or ans.get("nodes") or [])
        rendered = f"OUTLINE of {path} (from the code graph):\n" + "\n".join(
            f"{n.get('start')}-{n.get('end')} {n.get('kind')} {n.get('name')}" for n in nodes if isinstance(n, dict))
        return {"status": "ok", "workspace": root, "path": path, "symbol_count": len(nodes), "symbols": nodes,
                "rendered": rendered, **self._vault_meta(ans)}

    def _remote_read_symbol(self, path: str, name: str, root: str | None, target: str) -> dict[str, Any]:
        m = re.fullmatch(r"L?(\d+)-(\d+)", str(name or ""))
        if m:                                 # a line range: from the synced file's text (phase C)
            lo, hi = int(m.group(1)), int(m.group(2))
            ans = self._ask("GET", "/v1/memory/code/file", root, target, params={"path": path, "max_chars": 2_000_000})
            if ans is None:
                return self._remote_unavailable(target, root)
            lines = str(ans.get("text") or "").splitlines()
            hi = min(hi, len(lines))
            body = "\n".join(lines[lo - 1:hi])
            return {"status": "ok", "workspace": root, "path": ans.get("path") or path, "symbol": name,
                    "start_line": lo, "end_line": hi,
                    "rendered": f"[{ans.get('path') or path} lines {lo}-{hi} of {ans.get('total_lines')}, from the synced "
                                f"file]\n{body}", **self._vault_meta(ans)}
        ans = self._ask("POST", "/v1/memory/code/slice", root, target, body={"symbols": [f"{path}::{name}"], "depth": 1})
        items = [i for i in ((ans or {}).get("data") or {}).get("items") or [] if isinstance(i, dict) and i.get("text")]
        if not items:
            return self._remote_unavailable(target, root) if ans is None else {
                "status": "error", "path": path, "symbol": name, "error": f"{name} is not in the code graph of {path}"}
        it = items[0]
        rendered = (f"[{it.get('path')} lines {it.get('start_line')}-{it.get('end_line')}, from the code graph]\n"
                    f"{it.get('text')}")
        return {"status": "ok", "workspace": root, "path": it.get("path"), "symbol": it.get("qualname") or name,
                "start_line": it.get("start_line"), "end_line": it.get("end_line"), "rendered": rendered,
                **self._vault_meta(ans)}

    def outline(self, path: str, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        if target and target != "local":
            return self._remote_outline(path, root, target)
        _ensure_webbee_importable()
        from webbee.intel.outline import outline as _outline, render_outline

        ws = self.resolve_workspace(root)
        full, rel = _resolve_in_workspace(ws, path)
        if not os.path.isfile(full):
            return {"status": "error", "workspace": ws, "path": rel, "error": f"File not found: {rel}"}
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as exc:
            return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}

        total_lines = max(1, source.count("\n") + 1)
        nodes = _outline(rel, source) or []
        rendered = render_outline(rel, nodes, total_lines)
        self.tracker.record(
            "outline",
            returned_chars=len(rendered),
            baseline_chars=len(source),
            returned_lines=max(1, rendered.count("\n") + 1),
            baseline_lines=total_lines,
            baseline_files=1,
        )
        return {
            "status": "ok",
            "workspace": ws,
            "path": rel,
            "total_lines": total_lines,
            "symbol_count": len(nodes),
            "symbols": nodes,
            "rendered": rendered,
        }

    def read_symbol(self, path: str, name: str, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        if target and target != "local":
            return self._remote_read_symbol(path, name, root, target)
        _ensure_webbee_importable()
        from webbee.intel.outline import (
            outline as _outline,
            read_card,
            read_symbol as _read_symbol,
            render_outline,
        )

        ws = self.resolve_workspace(root)
        full, rel = _resolve_in_workspace(ws, path)
        if not os.path.isfile(full):
            return {"status": "error", "workspace": ws, "path": rel, "error": f"File not found: {rel}"}
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as exc:
            return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}

        total_lines = max(1, source.count("\n") + 1)
        hit = _read_symbol(rel, source, name)
        if hit is None:
            nodes = _outline(rel, source) or []
            return {
                "status": "error",
                "workspace": ws,
                "path": rel,
                "symbol": name,
                "error": f"Symbol or span '{name}' not found in {rel}",
                "available_outline": render_outline(rel, nodes, total_lines),
            }

        sym_label = hit["name"]
        if hit.get("kind") == "lines":
            sym_label = f"L{hit['start']}-{hit['end']}"
        rendered = read_card(rel, total_lines, hit["start"], hit["end"], hit["body"])
        self.tracker.record(
            "read_symbol",
            returned_chars=len(rendered),
            baseline_chars=len(source),
            returned_lines=max(1, rendered.count("\n") + 1),
            baseline_lines=total_lines,
            baseline_files=1,
        )
        return {
            "status": "ok",
            "workspace": ws,
            "path": rel,
            "symbol": sym_label,
            "kind": hit.get("kind", "symbol"),
            "start_line": hit["start"],
            "end_line": hit["end"],
            "rendered": rendered,
        }

    def check_syntax(self, path: str, root: str | None = None) -> dict[str, Any]:
        ws = self.resolve_workspace(root)
        full, rel = _resolve_in_workspace(ws, path)
        if not os.path.isfile(full):
            return {"status": "error", "workspace": ws, "path": rel, "error": f"File not found: {rel}"}
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as exc:
            return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}

        errs: list[tuple[int, int, str]] | None = None
        try:
            _ensure_webbee_importable()
            from webbee.intel.outline import syntax_errors

            errs = syntax_errors(rel, source, limit=20)
        except MissingCodeDependencyError:
            errs = None

        if errs is None:
            ext = os.path.splitext(rel)[1].lower()
            if ext in (".py", ".pyi", ".pyw"):
                try:
                    ast.parse(source, filename=rel)
                    errs = []
                except SyntaxError as exc:
                    errs = [(int(exc.lineno or 1), int(exc.offset or 1), str(exc.msg or "syntax error"))]
            elif ext == ".json":
                try:
                    json.loads(source)
                    errs = []
                except json.JSONDecodeError as exc:
                    errs = [(int(exc.lineno or 1), int(exc.colno or 1), str(exc.msg or "invalid JSON"))]

        if errs is None:
            return {
                "status": "ok",
                "workspace": ws,
                "path": rel,
                "clean": None,
                "supported": False,
                "error_count": 0,
                "errors": [],
            }
        formatted = [{"line": ln, "column": col, "message": msg} for ln, col, msg in errs]
        return {
            "status": "ok",
            "workspace": ws,
            "path": rel,
            "clean": len(formatted) == 0,
            "supported": True,
            "error_count": len(formatted),
            "errors": formatted,
        }

    def coding_context(self, root: str | None = None) -> dict[str, Any]:
        _ensure_webbee_importable()
        from webbee.coding_context import build_coding_context, detect_verify_cmd

        ws, svc, _ = self._get_indexer(root)
        ctx = build_coding_context(ws, intel=svc)
        verify_cmd = detect_verify_cmd(ws)
        return {"status": "ok", "workspace": ws, **ctx, "verify_cmd": verify_cmd}

    def checkpoint(
        self,
        label: str = "checkpoint",
        touched_paths: list[str] | None = None,
        root: str | None = None,
    ) -> dict[str, Any]:
        ws, sg = self._get_shadow(root)
        if not sg.available:
            return {"status": "error", "workspace": ws, "error": "ShadowGit unavailable in this workspace"}
        cp = sg.checkpoint(label=label, force=True)
        if not cp:
            return {"status": "error", "workspace": ws, "error": "Failed to create ShadowGit checkpoint"}
        return {
            "status": "ok",
            "workspace": ws,
            "step": cp["n"],
            "id": cp["id"],
            "label": cp["label"],
            "changed": cp["changed"],
            "touched_paths": list(touched_paths or []),
            "checkpoints": sg.list_checkpoints(limit=10),
        }

    def checkpoint_diff(
        self,
        target: str | int | None = None,
        paths: list[str] | None = None,
        root: str | None = None,
    ) -> dict[str, Any]:
        ws, sg = self._get_shadow(root)
        if not sg.available:
            return {"status": "error", "workspace": ws, "error": "ShadowGit unavailable in this workspace"}
        since = str(target) if target is not None else ""
        diff_text = sg.diff(since=since)
        return {
            "status": "ok",
            "workspace": ws,
            "target": target,
            "paths": list(paths or []),
            "diff": diff_text,
        }

    def checkpoint_rollback(self, target: str | int | None = None, root: str | None = None) -> dict[str, Any]:
        ws, sg = self._get_shadow(root)
        if not sg.available:
            return {"status": "error", "workspace": ws, "error": "ShadowGit unavailable in this workspace"}
        if target is None:
            rows = sg.list_checkpoints(limit=1)
            to_ref = str(rows[0]["n"]) if rows else "1"
        else:
            to_ref = str(target)
        res = sg.rollback(to_ref)
        ok = bool(res.get("ok"))
        return {
            "status": "ok" if ok else "error",
            "workspace": ws,
            "target": to_ref,
            "restored": ok,
            "message": res.get("content", ""),
        }

    def token_savings(self, root: str | None = None) -> dict[str, Any]:
        return {
            "status": "ok",
            "workspace": self.resolve_workspace(root),
            **self.tracker.summary(),
        }



