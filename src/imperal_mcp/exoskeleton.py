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
    "Code intelligence tools require the optional 'webbee' dependency (the [code] extra), which this install lacks. "
    "Install it with: pipx install --force 'imperal-mcp[code]' (or: uv tool install --force 'imperal-mcp[code]'); "
    "a server started by uvx needs --with 'imperal-mcp[code]' in its command. Then restart the MCP server."
)

# what a code tool imports from the [code] extra: a missing one is that extra, never a bug of the tool
CODE_EXTRA_MODULES = ("webbee", "tree_sitter")


def missing_code_extra(exc: BaseException) -> bool:
    """The error is the [code] extra not being installed (and not some other import failing)."""
    if isinstance(exc, MissingCodeDependencyError):
        return True
    name = getattr(exc, "name", None) or ""
    return isinstance(exc, ImportError) and name.split(".")[0] in CODE_EXTRA_MODULES


def _ensure_webbee_importable() -> None:
    """Ensure `webbee` is importable, or raise MissingCodeDependencyError."""
    try:
        import webbee  # noqa: F401
    except ImportError as exc:
        raise MissingCodeDependencyError(MISSING_CODE_DEPENDENCY_MESSAGE) from exc


class TokenSavingsTracker:
    """What the code tools saved this session, measured on the real files (owner 2026-11-13: as close to the real
    saving as it can be, without over-engineering). Without the tools the agent opens the files an answer points to,
    each once: ``would_read`` is the size of every distinct file the answers pointed to, counted the first time;
    ``returned`` is what the tools gave back. An answer with no local file behind it (a remote server's, a list of
    contracts) is counted apart as unmeasured, never as a saving. Tokens are estimated at 4 characters each."""

    CHARS_PER_TOKEN = 4

    def __init__(self) -> None:
        self.calls: int = 0
        self.lines_returned: int = 0
        self.chars_returned: int = 0
        self.measured_returned: int = 0
        self.unmeasured_calls: int = 0
        self.files: dict[str, int] = {}
        self.by_tool: dict[str, dict[str, int]] = {}

    def record(self, tool: str, *, returned_chars: int, returned_lines: int = 0, files: dict | None = None,
               **_old: Any) -> dict[str, Any]:
        ret_c, ret_l = max(0, int(returned_chars)), max(0, int(returned_lines))
        self.calls += 1
        self.chars_returned += ret_c
        self.lines_returned += ret_l
        slot = self.by_tool.setdefault(tool, {"calls": 0, "returned_chars": 0, "returned_lines": 0,
                                               "would_read_chars": 0, "unmeasured_calls": 0})
        slot["calls"] += 1
        slot["returned_chars"] += ret_c
        slot["returned_lines"] += ret_l
        new = {str(k): max(0, int(v)) for k, v in (files or {}).items() if str(k) not in self.files}
        if files:
            self.measured_returned += ret_c
            self.files.update(new)
            slot["would_read_chars"] += sum(new.values())
        else:
            self.unmeasured_calls += 1
            slot["unmeasured_calls"] += 1
        return {"tool": tool, "returned_chars": ret_c, "returned_lines": ret_l,
                "would_read_chars": sum(new.values()) if files else None}

    def summary(self) -> dict[str, Any]:
        would = sum(self.files.values())
        saved = max(0, would - self.measured_returned)
        t = self.CHARS_PER_TOKEN
        return {"calls": self.calls, "returned_chars": self.chars_returned, "returned_lines": self.lines_returned,
                "files_behind_answers": len(self.files), "would_read_chars": would,
                "saved_chars": saved, "saved_pct": round(100.0 * saved / would, 1) if would else 0.0,
                "tokens_est": {"would_read": would // t, "returned": self.measured_returned // t, "saved": saved // t},
                "unmeasured_calls": self.unmeasured_calls,
                "how": ("would_read = every distinct local file the answers pointed to, whole, once; saved = would_read "
                        "minus what those answers returned; ~4 characters per token"),
                "by_tool": {k: dict(v) for k, v in self.by_tool.items()}}


COARSE = "vault graph unavailable: links by name"
_SYNC_REUSE_S = 3.0      # one tool call's questions share one sync of the workspace
_FOLDER_ASK_THREADS = 8  # a folder's repositories asked at once (each: its sync check + its question)
_LOCAL_REFRESH_S = 5.0   # the local index checks the files (stat only) at most this often before it answers
# a collection (a folder without git: Documents, Downloads) is checked by a walk -- at most once a minute; a repository
# answers through git (no walk) every _LOCAL_REFRESH_S
_UNIT_REFRESH_S = 60.0
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

    # words of any script (live 2026-11-13: [A-Za-z0-9_] dropped every Cyrillic word, so a Russian quote of a comment
    # found nothing); one- and two-letter words ("в", "и", "of") match everywhere and prove nothing
    words = re.findall(r"\w+", query or "")
    tokens = [t.lower() for t in words if len(t) >= 3] or [t.lower() for t in words if len(t) >= 2]

    def _mentions(item: dict) -> bool:
        blob = " ".join(str(item.get(f) or "") for f in ("name", "qualname", "title", "snippet", "text", "signature",
                                                           "doc", "path")).lower()
        return any(t in blob for t in tokens)

    if any(m.get("path") for m in normalized) and (not tokens or any(_mentions(m) for m in normalized
                                                                     if m.get("path"))):
        return normalized[:k]
    # the index answered only by meaning, and no hit holds a word of the query (an English-only embedding scores any
    # Russian text alike -- live: unrelated tests came back "strong"): read the files for the words, and keep the
    # meaning-only hits after them, marked weak
    ranked_by_meaning = []
    for m in normalized:
        m = dict(m)
        if m.get("path") and tokens:
            m["match"] = "weak"
            m["why"] = "found by meaning only; no word of the query is in it"
        ranked_by_meaning.append(m)
    normalized = []
    if not tokens:
        return ranked_by_meaning[:k]

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
    return (normalized + ranked_by_meaning)[:k]


_IMPACT_KEPT = ("summary", "by_name", "by_name_count", "same_file", "resolved", "note")

_FILE_KINDS = frozenset({"code", "config", "document", "data", "mail", "image"})


def _view_for(ws: str, rel: str) -> dict | None:
    """``{text, nodes, skipped}`` for a file the code outline does not read: a document, sheet, message, HTML page
    or image through its view (universal index), code in a language webbee's outline does not parse through the
    SDK's symbols. None: the code outline reads it as before."""
    try:
        from imperal_sdk.universal.kinds import kind_of
        from imperal_sdk.universal.view import _READERS
    except ImportError:                       # an SDK before 6.4: code only, as before
        return None
    try:
        from webbee.intel.outline import lang_of
    except ImportError:
        def lang_of(_p):
            return ""
    kind = kind_of(rel)
    ext = os.path.splitext(rel)[1].lower()
    if kind is None or kind == "config" or (kind == "code" and lang_of(rel)):
        return None                           # resolution configs and webbee's own languages: the outline as before
    if kind == "code" and ext not in _READERS:
        from imperal_sdk.code_index import parse_file
        try:
            if os.path.getsize(os.path.join(ws, rel)) > _PARSE_CAP:
                return {"text": "", "nodes": [], "skipped": f"over {_PARSE_CAP // 1048576} MB -- read it by lines: "
                                                            "read_symbol(path, \"L<a>-<b>\")"}
            with open(os.path.join(ws, rel), "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as exc:
            return {"text": "", "nodes": [], "skipped": str(exc)}
        fi = parse_file(rel, text)
        nodes = [{"name": s.name, "kind": s.kind, "start": s.start_line, "end": s.end_line, "depth": 0}
                 for s in (fi.symbols if fi else [])]
        return {"text": text, "nodes": sorted(nodes, key=lambda n: (n["start"], -n["end"])), "skipped": ""}
    from imperal_sdk.universal.index import read_view
    view = read_view(ws, rel)
    if view is None:
        return {"text": "", "nodes": [], "skipped": "this file is never read (a secret or outside the folder)"}
    nodes = [{"name": s.title, "kind": s.kind, "start": s.start_line, "end": s.end_line,
              "depth": max(0, min(int(s.level), 4) - 1)} for s in view.sections]
    return {"text": view.text, "nodes": nodes, "skipped": view.skipped}


_PARSE_CAP = 1024 * 1024       # outline/read_symbol parse a file whole up to this (imperal_sdk RAW_CAP for code)


_GREP_FILE_MAX = 2 * 1048576     # a text file bigger than this is data, not something to grep through
_GREP_EXTRA_MAX = 20000          # text files beyond the code index searched in one call
_LOCK_FILES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "cargo.lock",
                         "composer.lock", "gemfile.lock", "go.sum", "pipfile.lock"})


def _grep_files(ws: str):
    """The files grep_code reads, code first: the code index's own files, then every other text file git tracks or
    would track (configs, docs, CI) -- under the rule read_symbol keeps (never a secret by name or place), never a
    dependency or build folder, a lock file, a binary or a file over 2 MB.
    Live 2026-11-13: grep_code read only the index's code files, so a version string in server.json was "not found"."""
    import subprocess
    from webbee.intel.service import _local_listing
    from imperal_sdk.code_index import SKIP_DIRS
    seen = set()
    for item in _local_listing(ws):
        seen.add(item["path"])
        yield item["path"]
    if not os.path.isdir(os.path.join(ws, ".git")):
        return
    try:
        r = subprocess.run(["git", "-C", ws, "ls-files", "-co", "--exclude-standard", "-z"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return
    if r.returncode != 0:
        return
    extra = 0
    for rel in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if not rel or rel in seen:
            continue
        parts = rel.split("/")
        if any(d == ".git" or d in SKIP_DIRS for d in parts[:-1]) or parts[-1].lower() in _LOCK_FILES:
            continue
        full = os.path.join(ws, rel)
        if _refused(ws, rel, full):
            continue
        try:
            if os.path.getsize(full) > _GREP_FILE_MAX:
                continue
            with open(full, "rb") as f:
                if b"\0" in f.read(4096):
                    continue
        except OSError:
            continue
        extra += 1
        if extra > _GREP_EXTRA_MAX:
            return
        yield rel


def _diff_for_paths(diff_text: str, paths: list[str] | None) -> str:
    """Only the files of a unified git diff that lie at or under one of ``paths`` (all of it when none are given).
    Live 2026-11-13: checkpoint_diff took ``paths`` and echoed them back, yet always answered the whole diff."""
    wanted = [p.strip().strip("/") for p in (paths or []) if p and p.strip().strip("/")]
    if not wanted or not diff_text:
        return diff_text
    keep: list[str] = []
    take = False
    for block in re.split(r"(?m)^(?=diff --git )", diff_text):
        if block.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)", block.split("\n", 1)[0])
            names = {m.group(1), m.group(2)} if m else set()
            take = any(n == w or n.startswith(w + "/") for n in names for w in wanted)
        if take:
            keep.append(block)
    return "".join(keep)


def _refused(ws: str, rel: str, full: str) -> str:
    """Why outline / read_symbol never open this file, or "": a secret by its name, by its real path (the workspace
    itself a secret store, a link into one), anything but a regular file (final review 2026-11-04: the tools read
    ``.env`` and ``~/.aws/credentials`` the index never reads)."""
    from imperal_sdk.universal.kinds import never_read_at
    if never_read_at(ws, rel):
        return f"{rel}: this file is never read (a secret by its name or where it lies)"
    try:
        st = os.stat(full)
    except OSError as exc:
        return f"{rel}: {exc}"
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode):
        return f"{rel}: not a regular file"
    try:
        from imperal_sdk.universal.index import is_placeholder
        if is_placeholder(rel, st):
            return f"{rel}: a cloud placeholder (reading it would download it)"
    except ImportError:
        pass
    return ""


def _lines_of(full: str, a: int, b: int) -> tuple[str, int]:
    """Lines ``a..b`` of a big file read as a stream, and the file's line count -- never the whole file in memory."""
    out: list = []
    n = 0
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            if a <= n <= b:
                out.append(line.rstrip("\n"))
    return "\n".join(out), max(1, n)


def _view_hit(text: str, nodes: list, name: str) -> dict | None:
    """One section of a view by its title (exact, then case-insensitive) or a line span ``L<a>-<b>``."""
    lines = text.split("\n")
    want = str(name or "").strip()
    span = re.fullmatch(r"L(\d+)-(\d+)", want)                    # the tool's own span syntax (mechanical)
    if span:
        a, b = max(1, int(span.group(1))), min(len(lines), int(span.group(2)))
        if a <= b:
            return {"name": want, "kind": "lines", "start": a, "end": b, "body": "\n".join(lines[a - 1:b])}
        return None
    for same in (lambda n: n["name"] == want, lambda n: n["name"].casefold() == want.casefold()):
        for n in nodes:
            if same(n):
                return {"name": n["name"], "kind": n["kind"], "start": n["start"], "end": n["end"],
                        "body": "\n".join(lines[n["start"] - 1:n["end"]])}
    return None


def _coarse(out: dict) -> dict:
    """A local answer marked as the coarse fallback. A units answer too (2026-11-06 report: from a folder the same
    name-only links came without the mark and read as exact) -- it keeps its own ``source`` beside the mark."""
    return {**out, "coarse": COARSE}


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


# ---- any folder is a workspace (universal index phase 2, owner 2026-11-03; replaces the 2026-10-25 refusal) ----
_UNIT_SKIP_TOP = frozenset({"Library", "Applications", "System", "Volumes", "private", "cores", "dev"})
_ICLOUD_DRIVE = "Library/Mobile Documents/com~apple~CloudDocs"
_REPO_DEPTH = 4               # repositories are looked for this deep (~/Projects/<org>/<repo>)


def _repo_above(path: str) -> bool:
    up = os.path.dirname(path)
    while up and up != os.path.dirname(up):
        if _is_repository(up):
            return True
        up = os.path.dirname(up)
    return False


def _find_repos(ws: str, depth: int = _REPO_DEPTH) -> list[str]:
    """The repositories (a folder holding ``.git``) inside ``ws``, as ws-relative paths -- Webbee's one rule
    (``webbee.intel.service.find_repositories``): never under a skipped, hidden or linked folder, never inside
    another repository."""
    try:
        from webbee.intel.service import find_repositories
    except ImportError:                       # webbee < 0.7.3: the same rule, here
        from webbee.intel.service import skipped_dir
        out: list[str] = []
        frontier = [""]
        for _ in range(depth):
            nxt: list[str] = []
            for rel in frontier:
                here = os.path.join(ws, rel) if rel else ws
                try:
                    names = sorted(os.listdir(here))
                except OSError:
                    continue
                for name in names:
                    full = os.path.join(here, name)
                    if (not rel and name in _UNIT_SKIP_TOP) or os.path.islink(full) or not os.path.isdir(full) \
                            or skipped_dir(here, name):
                        continue
                    child = f"{rel}/{name}" if rel else name
                    (out if os.path.exists(os.path.join(full, ".git")) else nxt).append(child)
            frontier = nxt
        return out
    return list(find_repositories(ws, depth))


def _plan_units(ws: str) -> list[dict]:
    """A folder that is no repository as index units: each repository in it; each other top-level folder a
    collection (without the repositories inside it); the loose files at the top; iCloud Drive."""
    from webbee.intel.service import skipped_dir
    repos = _find_repos(ws)
    units = [{"root": r, "kind": "repo", "exclude": ()} for r in repos]
    try:
        names = sorted(os.listdir(ws))
    except OSError:
        names = []
    tops = [n for n in names if os.path.isdir(os.path.join(ws, n)) and not os.path.islink(os.path.join(ws, n))]
    for top in tops:
        if top in repos or top in _UNIT_SKIP_TOP or skipped_dir(ws, top):
            continue
        units.append({"root": top, "kind": "collection",
                      "exclude": tuple(r[len(top) + 1:] for r in repos if r.startswith(top + "/"))})
    if any(os.path.isfile(os.path.join(ws, n)) for n in names):
        units.append({"root": ".", "kind": "collection", "exclude": tuple(tops)})
    parts = _ICLOUD_DRIVE.split("/")
    if os.path.isdir(os.path.join(ws, _ICLOUD_DRIVE)) and \
            not any(os.path.islink(os.path.join(ws, *parts[:i])) for i in range(1, len(parts) + 1)):
        units.append({"root": _ICLOUD_DRIVE, "kind": "collection", "exclude": ()})   # never through a link
    return units


def _in_folder(item, unit: str):
    """One vault answer item with its paths named from the folder (``<repo>/<path>``) -- the same rule as the
    kernel's ``meta_tools._in_unit`` (2026-11-06)."""
    import re as _re
    if not isinstance(item, dict) or unit in ("", "."):
        return item
    it = dict(item)

    def pre(v):
        v = str(v)
        return v if (not v or v.startswith("/") or v.startswith(unit + "/")) else f"{unit}/{v}"
    for key in ("path", "file", "uses"):
        if isinstance(it.get(key), str) and it[key]:
            it[key] = pre(it[key])
    for key in ("id", "subtitle"):
        v = it.get(key)
        if isinstance(v, str) and v:
            sep = "::" if "::" in v else (":" if _re.match(r"^[^:\s]+:\d", v) else "")
            if sep:
                head, tail = v.split(sep, 1)
                it[key] = pre(head) + sep + tail
            elif "/" in v or "." in v.rsplit("/", 1)[-1]:
                it[key] = pre(v)
    if it.get("kind") == "file" and isinstance(it.get("title"), str):
        it["title"] = pre(it["title"])
    if isinstance(it.get("targets"), list):
        it["targets"] = [pre(t.split("::", 1)[0]) + ("::" + t.split("::", 1)[1] if "::" in t else "")
                         if isinstance(t, str) else t for t in it["targets"]]
    it["repo"] = unit
    return it


def _cross_in_folder(item, unit: str, units_by_key: dict):
    """A user found in ANOTHER repository through this one's package (the vault's ``origin: package``): its path
    named from the folder by the repository it lies in; one outside this folder keeps the repository's name."""
    it = _in_folder(item, unit)               # targets: the answering repository's definitions
    home = units_by_key.get(str(item.get("repo") or ""))
    path = str(item.get("path") or "")
    name = f"{home}/{path}" if home not in (None, "", ".") else (path if home is not None else
                                                                 f"{item.get('repo_name') or item.get('repo')}/{path}")
    it.update(id=name, title=name, path=name, repo=home if home is not None else str(item.get("repo_name") or ""))
    if home is None:
        it["outside_folder"] = True
    return it


def _one_path_each(items: list) -> list:
    """A file found again through an overlapping repository key (``outside_folder``, its path named from a parent
    folder) is the same file as its in-folder copy -- kept once (Ignat 06.11 §4.4: 5 callers counted twice)."""
    inside = [str(x.get("path") or "") for x in items if isinstance(x, dict) and not x.get("outside_folder")]
    out = []
    for x in items:
        p = str(x.get("path") or "") if isinstance(x, dict) else ""
        if isinstance(x, dict) and x.get("outside_folder") and any(p.endswith("/" + q) or q.endswith("/" + p)
                                                                   for q in inside if q):
            continue
        out.append(x)
    return out


def _merge_folder_answers(answers: list, query: str = "", k: int = 0, units_by_key: dict | None = None) -> dict | None:
    """The vault's answers for each repository of a folder as one answer, or None when none answered.
    A search (``query``) puts exact-name hits first, then takes each repo's ranked list in turn."""
    ok = [(u, a) for u, a in answers if isinstance(a, dict) and a.get("ok", True) is not False]
    if not ok:
        return None
    keys = units_by_key or {}
    lists = []
    for u, a in ok:
        lst, seen = [], set()
        for x in ((a.get("data") or {}).get("items") or []):
            y = _cross_in_folder(x, u, keys) if isinstance(x, dict) and x.get("origin") == "package" \
                else _in_folder(x, u)
            ident = (y.get("id"), y.get("title")) if isinstance(y, dict) else id(y)
            if ident in seen:
                continue
            seen.add(ident)
            lst.append(y)
        lists.append(lst)
    if query:
        exact = [x for lst in lists for x in lst if isinstance(x, dict) and str(x.get("title") or "") == query]
        rest = [[x for x in lst if x not in exact] for lst in lists]
        items = list(exact)
        for i in range(max((len(r) for r in rest), default=0)):
            items += [r[i] for r in rest if i < len(r)]
        # one order over the repositories: an exact name, then the vault's own ``score`` (the fused rank its order
        # follows, comparable between repos) -- the repos taken in turn put one repo's 5th above another's 1st (field
        # report 06.11 #3); an answer without scores (an older vault) keeps the turns
        if any(isinstance(x, dict) and isinstance(x.get("score"), (int, float)) for x in items):
            items = sorted(items, key=lambda x: (not (isinstance(x, dict) and (x in exact or x.get("match") == "exact")),
                                                 -(float(x.get("score") or 0) if isinstance(x, dict) else 0)))
        if k:
            items = items[:max(k, len(exact))]
    else:
        items = _one_path_each(code_first([x for lst in lists for x in lst]))
    out = {"ok": True, "data": {"items": items, "total": len(items),
                                "has_more": any((a.get("data") or {}).get("has_more") for _u, a in ok)},
           "repo_key": ",".join(str(a.get("repo_key") or "") for _u, a in ok),
           # the folder's newest sync: a repository the client did not change is not resynced (its time stays) --
           # the oldest one read as a frozen map (Ignat 06.11 §5.2)
           "synced_at": max((a.get("synced_at") for _u, a in ok if a.get("synced_at")), default=None),
           "repos": {u: ("answered" if isinstance(a, dict) and a.get("ok", True) is not False else "no answer")
                     for u, a in answers}}
    for key in ("same_file", "by_name"):
        vals = [_in_folder(x, u) for u, a in ok for x in (a.get(key) or [])]
        if vals or any(key in a for _u, a in ok):
            out[key] = vals
    if any("by_name_count" in a for _u, a in ok):
        out["by_name_count"] = sum(int(a.get("by_name_count") or 0) for _u, a in ok)
    # files that only changed together, kept apart and named from the folder (06.11 #3: lost in the merge, the summary
    # counted 7 and the list read [])
    together = [{**c, "path": f"{u}/{c['path']}" if u not in ("", ".") and c.get("path") else c.get("path")}
                for u, a in ok for c in (a.get("changed_together") or []) if isinstance(c, dict)]
    if together:
        out["changed_together"] = sorted(together, key=lambda c: -float(c.get("confidence") or 0))[:30]
        out["changed_together_count"] = sum(int(a.get("changed_together_count") or 0) for _u, a in ok) or len(together)
    if any("resolved" in a for _u, a in ok):
        out["resolved"] = [f"{u}/{r}" if u not in ("", ".") else r for u, a in ok
                           for r in (a.get("resolved") if isinstance(a.get("resolved"), list) else [])] \
            or any(a.get("resolved") for _u, a in ok)
    # what each repository's answer says about itself, kept (report 06.11 #2: from the folder root the semantic
    # arm read null although each repository's search used it)
    sem = [a.get("semantic") for _u, a in ok if a.get("semantic") is not None]
    if sem:
        out["semantic"] = next((x for x in sem if x), sem[0])
    if query:
        best = next((x for x in out["data"]["items"] if isinstance(x, dict)), None)
        if best is not None:
            out["best_match"] = best.get("title") or best.get("id")
    sums = [f"{u}: {a['summary']}" for u, a in ok if a.get("summary") and (
        (a.get("data") or {}).get("items") or a.get("by_name_count") or a.get("resolved"))]
    if sums:
        out["summary"] = " | ".join(sums)[:1200]
    return out


_REPO_ID_KEYS = ("repo_key", "repo", "repository", "provider_repo", "user_repo", "src_repo", "dst_repo", "source_id",
                 "subject_id", "id")


def _one_per_contract(entries: list) -> list:
    """The account's contract catalog names a repository once per key that synced it (the folder synced whole, each
    repository on its own, an older sync): one entry per contract, the keys that hold it listed (report 06.11 #2:
    the same pair of endpoints four times, under four keys)."""
    out, at = [], {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        if e.get("route") or e.get("key"):
            # a contract is its method, route and handler -- never the path or line one copy indexed it at (live
            # 2026-11-13: a folder sync prefixed the path and an older sync kept older lines, so 4 copies stayed 4)
            ident = json.dumps([str(e.get("kind") or ""), str(e.get("method") or "").upper(),
                                str(e.get("route") or e.get("key") or ""), str(e.get("handler") or "")])
        else:
            ident = json.dumps({k: v for k, v in e.items() if k not in _REPO_ID_KEYS and not str(k).endswith("_repo")
                                and not str(k).endswith("repo_key")}, sort_keys=True, default=str)
        keys = [str(e.get(k)) for k in ("repo_key", "repo", "provider_repo", "user_repo") if e.get(k)]
        if ident in at:
            held = out[at[ident]].setdefault("held_by", [])
            held += [x for x in keys if x not in held]
            continue
        at[ident] = len(out)
        out.append({**e, **({"held_by": keys} if keys else {})})
    return out


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


def _file_sizes(ws: str, rel_paths) -> dict[str, int]:
    """``{repo-relative path: characters}`` of the real files ``rel_paths`` name inside ``ws`` (a ``path::symbol``,
    ``path#chunk`` or ``path:line`` spelling is its file; a path outside the workspace or not on disk is skipped)."""
    out: dict[str, int] = {}
    for raw_p in rel_paths or ():
        if not raw_p or not isinstance(raw_p, str):
            continue
        clean_p = raw_p.split("::", 1)[0].split("#", 1)[0].split(":", 1)[0].strip()
        if not clean_p or clean_p in out:
            continue
        try:
            full, rel = _resolve_in_workspace(ws, clean_p)
        except (ValueError, OutsideWorkspaceError):
            continue
        if rel in out or not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                out[rel] = len(f.read())
        except OSError:
            continue
    return out


def _answer_paths(text: str) -> list[str]:
    """The file paths an answer (its JSON) points to: every ``path`` / ``file`` / ``def_path`` value, and an ``id``
    spelled ``path::symbol``."""
    try:
        obj = json.loads(text or "null")
    except (TypeError, ValueError):
        return []
    found: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("path", "file", "def_path", "rel_path") and isinstance(v, str):
                    found.append(v)
                elif k == "id" and isinstance(v, str) and "::" in v:
                    found.append(v)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return found


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
IMPERAL - memory across sessions, a live code map, undo for every change and a fact check, in any shell.
Prefer these tools over your shell's own grep/read/search when the work is about code or the user's past work: they
answer from the exact code graph and the user's memory, so you read less, miss fewer callers and make up no names.

1. `frame` first - at the start and after each change: your task, what is proven and what is only claimed, the code
   around your focus, the world. If a hook already put this turn's frame in your context, act on its DECISION and call
   `frame` again only after a change (not until you change something). It needs an account: `login` gives a link and
   a code to show the user, once.
2. `task(goal, items)` - your plan; an item closes only by a proof the kernel saw (a diff, a check that exits 0, a
   finding with its sources). One you cannot finish: status blocked or cancelled, the reason in blocked_on.
3. Code, no account needed: `orient(query)` -> `outline(path)` -> `read_symbol(path, name | "L120-180")`;
   `search_code`, `grep_code` for an exact text, `graph_slice`, `contract_slice`, `repo_profile`, `coding_context`;
   `impact_of_change(symbols)` before editing a shared symbol, `check_syntax` after. root is the repository (default:
   the workspace); a server's repo: the same tools with target="host:<alias>" (or ssh:<connection_id>) and root=<path>.
4. Undo: `checkpoint` before a risky multi-file edit, then `checkpoint_diff` or `checkpoint_rollback`;
   `token_savings` measures what the code tools saved against reading the files whole.
5. Memory: `recall_context(query)`, `recall`, `search_history`, `live_sessions`, `message_session` (as an agent, never
   the user's words), `state_lens`, `vault_log_read`; keep what lasts with `remember_fact` and `save_repo_note`.
6. Never state a code name, file or size you did not read: the kernel checks every step and the final answer.
7. After a result your thought starts with `learned: <one fact>`, then `expect: <exit 0 | "text" | reach: files>` and,
   when you lack something, `need: <it, in plain words>`. Never secrets or raw file contents in them.

Apps: `list_apps`, `get_app`, `run_read_tool`, `run_write_tool` (money tools need panel approval), `upload_file`;
build one with `validate_ir` -> `smoke_ir` -> `deploy_ir`.
Pricing: a `frame` costs credits; every other tool is free.
"""


_EXCHANGE_MAX = 60     # the gateway's bound on one frame's exchange
# a group repeated around a repeated piece -- (a+)+, (a*)*, (x|xy)+ -- backtracks without end (the vault refuses it too)
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*[+*{]|\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*[+*{]")
_TOGETHER_SHOWN = 8         # files that changed together with a symbol, named under impact_of_change (not its users)
_HOST_SYNC_REUSE_S = 60.0   # a remote repo is listed over SFTP at most once a minute (only changed files are read)
_HOST_HEAD_REUSE_S = 15.0   # the server's HEAD (a few small SFTP reads) is asked again after this many seconds
_HOST_HEAD_WAIT_S = 25.0    # ... and waited for at most this long (an unreachable host answers by then)
_HOST_SYNC_WAIT_S = 70.0    # a sync the answer waits for (the copy is behind the server's HEAD) ends by then -- with
                            # the HEAD read (25 s) inside the MCP client's 120 s (live 2026-10-25: 150 s hung the call)
_UNKNOWN_HOST = re.compile(r"(?i)not known|nodename|could not resolve|no address associated|unknown host|"
                           r"name or service")


ANSWER_CHARS = 20000   # what one tool answer may put in the model's context by default (live: 65K / 354K answers)


def app_summary(app: Any) -> Any:
    """An app as an agent uses it: its identity and its CALLABLE tools (name, action_type, a line of what each does)
    -- the kernel's own ``skeleton_*`` entries are no tools to call (MCP audit 2026-10-25: get_app cut the manifest
    JSON mid-string at 20 000 chars, and run_read_tool refused a skeleton entry it listed)."""
    if not isinstance(app, dict):
        return app
    try:
        manifest = json.loads(app.get("manifest_json") or "{}") if isinstance(app.get("manifest_json"), str) \
            else (app.get("manifest_json") or {})
    except ValueError:
        manifest = {}
    tools = []
    for t in (manifest.get("tools") if isinstance(manifest, dict) else None) or []:
        name = str(t.get("name") or "")
        if not name or name.startswith("skeleton_"):
            continue
        desc = " ".join(str(t.get("description") or "").split())
        tools.append({"name": name, "action_type": t.get("action_type") or "", "about": desc[:240]
                      + ("…" if len(desc) > 240 else "")})
    keep = ("app_id", "display_name", "description", "category", "status", "pricing_model", "pricing_config")
    return {**{k: app.get(k) for k in keep if k in app}, "version": (manifest or {}).get("version"),
            "tools": tools, "note": "full=true gives the raw record with the whole manifest"}


# lists a cut must never touch: the query's own echo (Ignat 06.11 §4.1: "queried_symbols_shown: 1 / 2")
_KEEP_WHOLE = frozenset({"queried_symbols"})
_MORE = re.compile(r"^\+(\d+) more$")


def _real_total(v: list) -> int:
    """A display list's real length: one that ends with "+N more" stands for N more than it shows."""
    m = _MORE.match(str(v[-1])) if v else None
    return (len(v) - 1 + int(m.group(1))) if m else len(v)


def code_first(items: list) -> list:
    """The code of every repository first, then the tests (stable) -- what the impact tool promises; a cut then
    drops tests, never another repository's code (Ignat 06.11 §4.1)."""
    return sorted(items or [], key=lambda it: str((it or {}).get("group") or "") == "tests")


def bounded(obj: Any, limit: int = ANSWER_CHARS) -> Any:
    """A tool's answer within ``limit`` characters: its longest lists cut (each keeps its first entries and says how
    many there were), long strings clipped; ``full=true`` on the tool gives everything."""
    def size(x: Any) -> int:
        return len(json.dumps(x, ensure_ascii=False, default=str))
    if not isinstance(obj, dict) or size(obj) <= limit:
        return obj
    out = dict(obj)
    lists = {k: list(v) for k, v in out.items() if isinstance(v, list) and len(v) > 1 and k not in _KEEP_WHOLE}
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
            out[f"{k}_shown"], out[f"{k}_total"] = shown[k], _real_total(v)
    if size(out) > limit:          # still too big: the long strings give way
        out = {k: (v[:2000] + "…" if isinstance(v, str) and len(v) > 2000 else v) for k, v in out.items()}
    for _ in range(12):            # ... then what sits INSIDE the remaining entries (live 2026-11-13: one graph_slice
        if size(out) <= limit:     # symbol carried its whole body and 40 callers twice: 38 KB past this bound)
            break
        if not _shrink_inside(out):
            break
    out["truncated"] = f"bounded to {limit} chars -- pass full=true for everything"
    return out


def _shrink_inside(x: Any, depth: int = 0) -> bool:
    """One halving step for the lists and long strings nested inside ``x``; False when nothing is left to cut."""
    if depth > 6:
        return False
    changed = False
    items = x.items() if isinstance(x, dict) else enumerate(x) if isinstance(x, list) else ()
    for k, v in list(items):
        if isinstance(v, str) and len(v) > 400:
            x[k] = v[: max(400, len(v) // 2)] + "…"
            changed = True
        elif isinstance(v, list) and len(v) > 3 and depth > 0:
            x[k] = v[: max(3, len(v) // 2)]
            if isinstance(x, dict) and f"{k}_total" not in x:
                x[f"{k}_total"] = len(v)
            changed = True
        elif isinstance(v, (dict, list)):
            changed = _shrink_inside(v, depth + 1) or changed
    return changed


_SLICE_TEXT_LINES, _SLICE_TEXT_CHARS, _SLICE_LINKS = 80, 4000, 15


def lean_slice_item(item: Any) -> Any:
    """One graph_slice symbol as an agent reads it: the definition's text clipped (read_symbol gives it whole), callers
    and callees once (the *_detail lists repeat the plain ones) and at most 15 of each, with their totals."""
    if not isinstance(item, dict):
        return item
    out = dict(item)
    text = out.get("text")
    if isinstance(text, str):
        lines = text.split("\n")
        if len(lines) > _SLICE_TEXT_LINES or len(text) > _SLICE_TEXT_CHARS:
            out["text"] = "\n".join(lines[:_SLICE_TEXT_LINES])[:_SLICE_TEXT_CHARS] + "\n…"
            out["text_lines_total"] = len(lines)
    for side in ("callers", "callees"):
        detail = out.get(f"{side}_detail")
        if isinstance(detail, list):
            out.pop(side, None)
            if len(detail) > _SLICE_LINKS:
                out[f"{side}_detail"] = detail[:_SLICE_LINKS]
                out[f"{side}_total"] = len(detail)
        elif isinstance(out.get(side), list) and len(out[side]) > _SLICE_LINKS:
            out[f"{side}_total"] = len(out[side])
            out[side] = out[side][:_SLICE_LINKS]
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


_WORD_EDGE = "\"'`.,;:!?()[]{}<>«»“”"
_WORD_NUM = re.compile(r"\d+(?:\.\d+)?")
WITHHELD_SEEN_MAX = 400          # the gateway's bound on the words a final may report


def withheld_words(text: str) -> list:
    """The words of a text as the kernel's claim check reads them: each whitespace word trimmed of its punctuation, its
    parts (``65–72`` -> 65, 72; ``a=b``), its numbers (``28s`` -> 28) -- the same cut for an output and an answer."""
    out: list = []
    for w in str(text or "").split():
        w = w.strip(_WORD_EDGE)
        if not w:
            continue
        out.append(w)
        out += [p for p in re.split(r"[^\w.\-]+", w) if p.strip(".-")]
        out += _WORD_NUM.findall(w)
    return list(dict.fromkeys(x[:120] for x in out if x.strip(".-")))


def word_marks(words) -> list:
    """Keyed fingerprints of words, one per word in order (this machine's own key): what a withheld output held,
    never what it said."""
    import hashlib
    import hmac
    key = _withhold_key()
    return [hmac.new(key, str(w).encode(), hashlib.sha256).hexdigest()[:16] for w in words]


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

    @property
    def _fresh(self) -> dict[str, Any]:
        return getattr(self._per_call, "fresh", {})

    @_fresh.setter
    def _fresh(self, value: dict[str, Any]) -> None:
        self._per_call.fresh = value

    @property
    def _last_miss(self) -> str:
        return getattr(self._per_call, "miss", "")

    @_last_miss.setter
    def _last_miss(self, value: str) -> None:
        self._per_call.miss = value

    def __init__(self, workspace_root: str | None = None, workspace: str | None = None, client: Any = None) -> None:
        self._default_root = _resolve_root(workspace or workspace_root)
        self._client = _OnLoop(client, self) if client is not None else None   # code questions go to the vault
        self.loop = None                    # the server's event loop (set by the server): the client's one loop
        self._repo_keys: dict[str, str] = {}
        self._synced_at: dict[str, float] = {}
        self.tracker = TokenSavingsTracker()
        self._indexers: dict[str, Any] = {}
        self._units: dict[str, list] = {}     # a non-repository workspace -> [(unit, IntelService)]
        self._refreshed_at: dict[str, float] = {}
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
        self._host_heads: dict[str, tuple[float, dict]] = {}     # memo -> (when asked, remote_head's answer)
        self._sync_errors: dict[str, str] = {}                    # memo -> why its last sync failed
        # per call (each tool runs on its own worker thread, parallel calls at once): how fresh the copy of the
        # repo asked about is, and why an answer is missing -- never another call's (MCP audit 2026-10-25: a local
        # impact_of_change carried whm-jump's freshness)
        self._per_call = threading.local()

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

    # the lens tools whose answer the kernel checks against what this session saw (the truth door)
    _CHECKED_LENS = frozenset({"message_session"})

    def _flush_calls(self, ws: str) -> None:
        """This turn's calls so far -- the shell's spooled ones and this server's own -- written to the kernel now, as
        the stop hook writes them before a final (2026-10-28: a message naming two files read a step before was held
        "this task never read it": the reads still sat in the spool). Nothing is lost: a failed write puts them back."""
        from .hooks import _bounded_items
        spool = self._shell_spool(ws)
        hooked, memory = spool.drain() if spool is not None else ([], [])
        own, self._exchange = self._exchange, []
        allq = hooked + own
        pending = _bounded_items(allq)
        late = allq[:len(allq) - len(pending)]
        if not (pending or memory):
            return
        st = spool.state() if spool is not None else {}
        body = {"session_id": self._session(ws), "step": int(st.get("step") or self._frame_step), "exchange": pending,
                "memory": memory[-20:], "repo_key": str(st.get("repo_key") or ""),
                "session_repo": self._session_repo(ws)}
        try:
            self._vault("POST", "/v1/memory/frame/record", body=body)
        except Exception:
            if spool is not None:
                spool.restore(hooked, memory)
            self._exchange = (own + self._exchange)[-_EXCHANGE_MAX:]
            return
        if late:
            if spool is not None:
                spool.restore(late, [])
            else:
                self._exchange = (late + self._exchange)[-_EXCHANGE_MAX:]

    def lens(self, tool: str, args: dict | None = None, root: str | None = None) -> dict[str, Any]:
        """A pointer the frame gave (state_lens / recall / vault_log_read) or a search of past conversations
        (search_history), answered by the kernel for this session. A checked one (``message_session``) first writes
        this turn's calls, so the check sees what was read."""
        try:
            if self._client is None:
                raise RuntimeError("no Imperal client")
            ws = self.resolve_workspace(root)
            if str(tool) in self._CHECKED_LENS:
                try:
                    self._flush_calls(ws)
                except Exception:      # the message still goes: the kernel checks what it holds
                    pass
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

        if hasattr(svc, "load_or_build"):
            # webbee >= 0.7: the cache checked against the disk by its checksum tree (new, changed and deleted files
            # caught, a folder without git cached too), else the build -- every file kind, the focus first
            _touched, rebuilt = svc.load_or_build()
            if rebuilt:
                svc._save_cache()
            self._start_embed(svc)
            return
        svc.git_ref = _git_ref(svc.root)
        idx = store.load(svc.cache_dir, svc.repo_key, svc.git_ref) if svc.git_ref else None
        if idx is None:
            if hasattr(svc, "_build_progressive"):
                # every file kind, the focus first, published in steps (universal index phase 2)
                from webbee.intel.service import _index_walk
                walked, skipped = _index_walk(svc.root, getattr(svc, "focus", None),
                                              exclude=getattr(svc, "exclude", ()))
                svc._progress = {"indexed": 0, "total": len(walked), "focus_done": False,
                                 "skipped": {**skipped, "unread": 0}}
                idx = svc._build_progressive(walked)
                svc._progress.update(indexed=len(walked), focus_done=True)
            else:
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
        self._start_embed(svc)

    def _start_embed(self, svc: Any) -> None:
        """Vectors for the index in the background (one thread per folder)."""
        idx = svc.index
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
            else:
                self._refresh_if_due(ws, svc)
            if self._client is not None and getattr(svc, "vault_client_factory", None) is None:
                svc.vault_client_factory = lambda: self._client     # synced on demand (sync_now), not in the background
        return ws, svc, svc.index

    def _refresh_if_due(self, ws: str, svc: Any, every: float = _LOCAL_REFRESH_S) -> None:
        """The local index catches up with the files before it answers (live 2026-11-03: a server running for hours
        answered search_code from its first snapshot -- files written since were missing and config files ranked
        first). A stat listing, no read, at most once per ``_LOCAL_REFRESH_S``; only changed files are parsed (the
        index's own ``apply_changes``, which also sends them to the vault)."""
        now = time.monotonic()
        if now - self._refreshed_at.get(ws, 0.0) < every:
            return
        self._refreshed_at[ws] = now
        if hasattr(svc, "refresh"):
            # webbee >= 0.7: one listing for build and refresh (every file kind, .gitignore honoured), a git
            # repository unchanged answers with no walk, a folder by its checksum tree
            try:
                svc.refresh()
            except Exception as exc:      # a refresh that fails leaves the index as it was -- and says why once
                self._last_miss = f"the local index could not check its files: {type(exc).__name__}: {str(exc)[:200]}"
            return
        try:
            from webbee.intel import service as intel_service
            files, _capped = intel_service._code_files(ws)
            rels = [f.replace(os.sep, "/") for f in files]
            now_stats = intel_service._stats_of(ws, rels)
            known = dict(getattr(svc, "_stats", None) or {})
            changed = [rel for rel, st in now_stats.items() if known.get(rel) != st]
            gone = [rel for rel in known if rel not in now_stats]
            deleted = [rel for rel in gone if not os.path.lexists(os.path.join(ws, rel))]
            # a file that left the listing but is still on disk (now .gitignore'd, now named like a secret) is never
            # read again: it leaves the index here unread -- apply_changes would read it and send it to the vault
            unlisted = [rel for rel in gone if rel not in set(deleted)]
            if unlisted:
                self._evict_unread(svc, unlisted)
            if changed or deleted:
                svc.apply_changes(changed + deleted)
        except Exception as exc:          # a refresh that fails leaves the index as it was -- and says why once
            self._last_miss = f"the local index could not check its files: {type(exc).__name__}: {str(exc)[:200]}"

    @staticmethod
    def _evict_unread(svc: Any, rels: list) -> None:
        """Files out of the index without a read (the index's own lock and graph rebuild, as apply_changes does)."""
        from webbee.intel.graph import CodeGraph
        with svc._lock:
            for rel in rels:
                svc.index.files.pop(rel, None)
                svc._stats.pop(rel, None)
            svc.graph = CodeGraph(svc.index)

    # ---- units: a workspace that is no repository (a home folder) ----

    def _is_units_workspace(self, ws: str) -> bool:
        return not _is_repository(ws) and not _repo_above(ws)

    def _unit_services(self, ws: str) -> list:
        """The workspace's units with their indexes; the first call plans them and starts one background builder
        that indexes them one after another (the answers never wait for it)."""
        with self._guard_lock:
            got = self._units.get(ws)
        if got is not None:
            for u, svc in got:                # built units catch up with the disk (new, changed, deleted files)
                if getattr(svc, "_unit_done", False) and getattr(svc, "index", None) is not None:
                    self._refresh_if_due(svc.root, svc,
                                         _LOCAL_REFRESH_S if u["kind"] == "repo" else _UNIT_REFRESH_S)
            return got
        with self._guard_lock:
            got = self._units.get(ws)
            if got is not None:
                return got
            _ensure_webbee_importable()
            from webbee.intel.service import IntelService
            from webbee.repo import compute_repo_key
            got = []
            ws_real = os.path.realpath(ws)
            for u in _plan_units(ws):
                abs_root = os.path.realpath(os.path.join(ws, u["root"]))
                if abs_root != ws_real and not abs_root.startswith(ws_real + os.sep):
                    continue                  # a unit that resolves outside the workspace is never indexed
                svc = IntelService(abs_root, compute_repo_key(abs_root), exclude=u["exclude"])
                svc._unit_done = False
                got.append((u, svc))
            self._units[ws] = got
        threading.Thread(target=self._build_units, args=(got,), daemon=True, name="imperal-mcp-units").start()
        return got

    def _build_units(self, units: list) -> None:
        for _u, svc in units:
            try:
                self._build_fast_index(svc)
            except Exception as exc:          # one unit's failure is said in its progress, never the others' end
                svc.stale_reason = f"index failed: {type(exc).__name__}: {str(exc)[:200]}"
            svc._unit_done = True

    def units_progress(self, root: str | None = None) -> list[dict]:
        """How far each unit of a non-repository workspace is: ``[{root, kind, indexed, total, done}]``."""
        ws = self.resolve_workspace(root)
        out = []
        for u, svc in self._units.get(ws, []):
            prog = svc.progress() if hasattr(svc, "progress") else {}
            out.append({"root": u["root"], "kind": u["kind"], "indexed": int(prog.get("indexed") or 0),
                        "total": prog.get("total") if getattr(svc, "index", None) is not None or prog.get("total")
                        else None, "done": bool(getattr(svc, "_unit_done", False)),
                        **({"note": svc.stale_reason} if getattr(svc, "stale_reason", "") else {})})
        return out

    @staticmethod
    def _in_unit(u: dict, rel: str) -> str:
        return rel if u["root"] == "." else f"{u['root']}/{rel}"

    def _units_search(self, ws: str, query: str, k: int, kind: str | None, path_glob: str | None) -> dict:
        import fnmatch
        from webbee.intel.query import search_code as _search_code
        merged: list = []
        waiting = []
        for u, svc in self._unit_services(ws):
            if getattr(svc, "index", None) is None:
                waiting.append(u["root"])
                continue
            res = _search_code(svc, query, k=k, kind=kind)
            for m in _normalize_search_matches((res.get("data") or {}).get("items", []), svc.root, query, k=k,
                                               kind=kind):
                # every path field named from the folder (06.11 report: each hit came twice -- once with the repo's
                # path, once with the folder's -- because only ``path`` was prefixed)
                m = _in_folder(dict(m), u["root"])
                if path_glob and not fnmatch.fnmatch(str(m.get("path") or ""), path_glob):
                    continue
                merged.append(m)
        seen_ids: set = set()
        uniq = []
        for m in merged:
            key = str(m.get("id") or m.get("path") or "")
            if key in seen_ids:
                continue
            seen_ids.add(key)
            uniq.append(m)
        # an exact name first, whatever its score (06.11 report: exact hits carry no score and sank below fuzzy ones)
        uniq.sort(key=lambda m: (str(m.get("title") or "") != query, -float(m.get("score") or 0)))
        matches = uniq[:k]
        self._record_read("search_code", returned_text=json.dumps(matches, ensure_ascii=False), root=ws)
        return {**self._units_status(waiting), "workspace": ws, "query": query, "matches": matches,
                "total": len(matches), "units": self.units_progress(ws), "source": "local index (units)"}

    def _units_profile(self, ws: str) -> dict:
        files = 0
        other: dict = {}
        for _u, svc in self._unit_services(ws):
            if getattr(svc, "index", None) is None:
                continue
            prof = svc.repo_profile()
            files += int(prof.get("file_count") or 0)
            for k2, v in (prof.get("other_kinds") or {}).items():
                other[k2] = other.get(k2, 0) + int(v)
        return {"status": "ok", "workspace": ws, "profile": {"code_files": files, "other_kinds": other},
                "units": self.units_progress(ws), "source": "local index (units)"}

    def _units_impact(self, ws: str, sym_list: list) -> dict:
        from webbee.intel.query import impact_of_change as _impact_of_change
        items: list = []
        by_name: list = []
        waiting = []
        for u, svc in self._unit_services(ws):
            if getattr(svc, "index", None) is None:
                waiting.append(u["root"])
                continue
            res = _impact_of_change(svc, sym_list)
            items += [_in_folder(dict(it), u["root"]) for it in (res.get("data") or {}).get("items", [])]
            by_name += [_in_folder(dict(b), u["root"]) for b in res.get("by_name") or []]
        files = [it.get("title") or it.get("id") for it in items]
        return {**self._units_status(waiting), "workspace": ws, "queried_symbols": sym_list,
                "dependent_files": files, "items": items, "by_name": by_name, "by_name_count": len(by_name),
                "summary": (f"{len(files)} file(s) use {', '.join(sym_list)} by resolved links"
                            + (f"; {len(by_name)} more only mention the name (by_name)" if by_name else "")),
                "units": self.units_progress(ws), "source": "local index (units)"}

    @staticmethod
    def _units_status(waiting: list) -> dict:
        """``status: ok``, or ``partial`` naming the units whose index is not built yet -- never an empty "ok" that
        reads as "nothing found / nobody affected" (06.11 report: mid-rebuild, impact said ok + [])."""
        if not waiting:
            return {"status": "ok"}
        return {"status": "partial", "not_ready": waiting,
                "note": f"{len(waiting)} unit(s) still indexing ({', '.join(waiting[:5])}) -- their answer is missing, "
                        "ask again shortly"}

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

    def _record_read(self, tool: str, *, returned_text: str, paths: Any = None, root: str | None = None,
                     **_old: Any) -> None:
        """One answer in token_savings: what it returned against the local files it points to (``paths``, else the
        ones its JSON names), each file counted once per session."""
        ret_c = len(returned_text or "")
        ret_l = max(1, (returned_text or "").count("\n") + 1) if returned_text else 0
        try:
            files = _file_sizes(self.resolve_workspace(root), paths if paths is not None
                                else _answer_paths(returned_text))
        except Exception:
            files = {}
        self.tracker.record(tool, returned_chars=ret_c, returned_lines=ret_l, files=files)

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

    def _catalog_row(self, alias: str, root: str, *, strict: bool = False) -> dict:
        """The vault catalog's repo at ``root`` on the machine ``alias`` names ({} when none). ``strict``: that machine
        only -- a ``host:`` alias never borrows another machine's copy of the same path (live 2026-10-25: host:no-such-host
        answered from whm-jump's /home/ipw-repo)."""
        try:
            repos = (self._vault("GET", "/v1/memory/code/repos") or {}).get("repos") or []
        except Exception:
            return {}
        want = str(root or "").rstrip("/")
        hits = [r for r in repos if str(r.get("root_path") or "").rstrip("/") == want]
        mine = [r for r in hits if alias in (str(r.get("machine_label") or ""), str(r.get("ref") or ""))]
        hits = mine if strict else mine + [r for r in hits if r not in mine]
        return dict(hits[0]) if hits else {}

    def _only_copy(self, root: str) -> bool:
        """The catalog holds exactly one copy of ``root`` (on any machine)."""
        try:
            repos = (self._vault("GET", "/v1/memory/code/repos") or {}).get("repos") or []
        except Exception:
            return False
        want = str(root or "").rstrip("/")
        return sum(1 for r in repos if str(r.get("root_path") or "").rstrip("/") == want) == 1

    def _catalog_key(self, alias: str, root: str) -> str:
        """The vault catalog's repo at ``root`` on the machine ``alias`` names ("" when none)."""
        return str(self._catalog_row(alias, root).get("repo_key") or "")

    def _host_head(self, memo: str, alias: str, root: str) -> dict:
        """The server's HEAD of the repo (webbee's ``remote_head``: a few small SFTP reads), asked at most every
        ``_HOST_HEAD_REUSE_S`` and waited for at most ``_HOST_HEAD_WAIT_S``. ``{"commit": "", "why": ""}`` when it
        cannot tell (an older webbee): the copy is then trusted as before."""
        import asyncio
        import time
        at, got = self._host_heads.get(memo, (0.0, {}))
        if got and time.monotonic() - at < _HOST_HEAD_REUSE_S:
            return got
        try:
            _ensure_webbee_importable()
            from webbee import tools as wt
        except Exception:
            return {"commit": "", "why": ""}
        if not hasattr(wt, "remote_head"):
            return {"commit": "", "why": ""}
        box: dict = {}

        def run():
            try:
                box["v"] = asyncio.run(wt.remote_head(alias, root)) or {}
            except Exception as exc:
                box["v"] = {"commit": "", "why": f"{type(exc).__name__}: {exc}"}
        t = threading.Thread(target=run, daemon=True, name=f"imperal-mcp-host-head-{alias}")
        t.start()
        t.join(_HOST_HEAD_WAIT_S)
        got = box.get("v") or {"commit": "", "why": f"{alias}: no answer in {int(_HOST_HEAD_WAIT_S)} s"}
        self._host_heads[memo] = (time.monotonic(), got)
        return got

    def _sync_host_now(self, memo: str, alias: str, root: str) -> None:
        """A sync the answer waits for, bounded by ``_HOST_SYNC_WAIT_S`` -- never a hang (live 2026-10-25: 30 min)."""
        running = self._host_syncs.get(memo)
        if running is None or not running.is_alive():
            running = threading.Thread(target=self._run_host_sync, args=(memo, alias, root), daemon=True,
                                       name=f"imperal-mcp-host-sync-{alias}")
            self._host_syncs[memo] = running
            running.start()
        running.join(_HOST_SYNC_WAIT_S)
        if running.is_alive():
            self._sync_errors[memo] = f"the sync of {root} on {alias} did not finish in {int(_HOST_SYNC_WAIT_S)} s"

    def _sync_host(self, alias: str, root: str) -> str:
        """A repo on a server the user reaches with their own ssh (``host:<alias>``) is synced into the vault by
        webbee's SFTP sync (nothing written there; only changed files are read) -- design 2026-10-24 §5.1. The first
        sync is waited for (no key without it); after it a question answers at once and a refresh runs behind, at
        most once per ``_HOST_SYNC_REUSE_S`` (a sync lists the tree over SFTP: ~1 min live); every answer carries
        ``synced_at``. "" when it cannot be synced (the catalog then answers)."""
        import time
        memo = f"host:{alias}:{root}"
        row = self._catalog_row(alias, root, strict=True)
        if not row:
            # the catalog names a machine by the label its sync gave it (live 2026-10-25: /opt/imperal-auth-gateway
            # is "imperal-gateway", asked as host:10.88.0.1): ONE copy of this path, on a host that does exist, is it
            only = [r for r in [self._catalog_row(alias, root)] if r]
            if only and self._only_copy(root):
                head = self._host_head(memo, alias, root)
                if not _UNKNOWN_HOST.search(str(head.get("why") or "")):
                    row = only[0]
        known = self._repo_keys.get(memo, "") or str(row.get("repo_key") or "")
        if known:
            self._repo_keys[memo] = known
        # the server's HEAD against the copy's commit: a copy behind it is synced BEFORE the answer (live 2026-10-25:
        # the copy stayed on 711e5630 after fd751713 was deployed -- "0 matches" for the new code, no warning)
        head = self._host_head(memo, alias, root)
        live, mapped = str(head.get("commit") or ""), str(row.get("git_ref") or "")
        self._fresh = {"server": f"host:{alias}", "server_head": live[:12], "copy_commit": mapped[:12],
                       **({"copy_of_machine": str(row.get("machine_label"))}
                          if row.get("machine_label") and row.get("machine_label") != alias else {})}
        if head.get("why") and not known:
            self._last_miss = str(head["why"])            # an unknown host, a missing folder: said, never a guess
            return ""
        behind = bool(live) and (not mapped or not (live.startswith(mapped) or mapped.startswith(live)))
        if not known or behind:
            self._sync_host_now(memo, alias, root)
            row = self._catalog_row(alias, root, strict=True)
            known = self._repo_keys.get(memo, "") or str(row.get("repo_key") or "")
            mapped = str(row.get("git_ref") or mapped)
            self._fresh["copy_commit"] = mapped[:12]
            if not known:
                self._last_miss = self._sync_errors.get(memo) or f"{root} on {alias} could not be synced"
                return ""
            if live and mapped and not (live.startswith(mapped) or mapped.startswith(live)):
                self._fresh["stale"] = (f"the copy is at {mapped[:12]}, the server at {live[:12]}: "
                                        + (self._sync_errors.get(memo) or "the sync did not reach it"))
            return known
        if head.get("why"):
            self._fresh["stale"] = f"the server could not be asked for its HEAD ({head['why']}): the copy may be old"
        if time.monotonic() - self._synced_at.get(memo, 0.0) >= _HOST_SYNC_REUSE_S:
            # same commit: an uncommitted edit is caught by a listing -- behind the answer, at most once a window
            running = self._host_syncs.get(memo)
            if running is None or not running.is_alive():
                t = threading.Thread(target=self._run_host_sync, args=(memo, alias, root), daemon=True,
                                     name=f"imperal-mcp-host-sync-{alias}")
                self._host_syncs[memo] = t
                t.start()
        return known

    def _run_host_sync(self, memo: str, alias: str, root: str) -> None:
        import asyncio
        import time
        try:
            _ensure_webbee_importable()
            from webbee import tools as wt
            client = self._client
            out = _off_thread(lambda: asyncio.run(wt.remote_sync(client, alias, root, []))) or {}
        except Exception as exc:
            # kept, never swallowed: the next answer names it (live 2026-10-25: a refresh failed for an hour unseen)
            self._sync_errors[memo] = f"the sync failed: {type(exc).__name__}: {str(exc)[:200]}"
            self._synced_at[memo] = time.monotonic()
            return
        key = str(out.get("repo_key") or "")
        if key:
            self._repo_keys[memo] = key
            self._sync_errors.pop(memo, None)
        else:
            self._sync_errors[memo] = str(out.get("partial_reason") or out.get("content") or "the sync gave no repo")
        self._synced_at[memo] = time.monotonic()      # a failed refresh waits a window too: never a sync per question

    def _repo_key(self, root: str | None, target: str | None) -> str:
        """The vault's key of the repo asked about: a remote target's repo from the catalog (root path, machine);
        the local workspace synced first (its edits reach the vault before the question)."""
        if target and target != "local":
            alias = target.split(":", 1)[-1]
            want = str(root or "").rstrip("/")
            if target.startswith("host:") and want:
                return self._sync_host(alias, want)      # its own machine's copy or none (and why): never another's
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
        if (not target or target == "local") and self._is_units_workspace(self.resolve_workspace(root)):
            return self._ask_folder(method, path, root, params=params, body=body)
        self._fresh, self._last_miss = {}, ""
        try:
            key = self._repo_key(root, target)
            if not key:
                # the reason found on the way (an unknown host, a missing folder, a failed sync) stays -- never this
                # generic line over it (MCP audit 2026-10-25)
                self._last_miss = (self._last_miss
                                   or f"the vault graph holds no synced copy of {root} on {target or 'local'}")
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

    def _ask_folder(self, method: str, path: str, root: str | None, *, params: dict | None = None,
                    body: dict | None = None) -> dict | None:
        """A folder that is no repository (2026-11-06 report: from such a folder every graph question fell to the
        name-only local index): the vault is asked for each repository in it, the answers merged -- paths named from
        the folder, exact names first in a search. None when no repository of it answered (the reasons kept)."""
        ws = self.resolve_workspace(root)
        repos = [u["root"] for u in _plan_units(ws) if u["kind"] == "repo"]
        if not repos:
            self._last_miss = f"{ws} holds no repository the vault graph could answer for"
            return None
        answers, misses, units_by_key = [], [], {}

        def one(rel: str):
            # each repository on its own thread: its sync check and its question (live 2026-11-06: 21 repositories
            # one after another took 78 s); the per-call state (_last_miss) is thread-local
            ans = self._ask(method, path, os.path.join(ws, rel), "local", params=params, body=body)
            return rel, ans, (self._last_miss if ans is None else "")
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(_FOLDER_ASK_THREADS, len(repos))) as pool:
            got = list(pool.map(one, repos))
        for rel, ans, miss in got:
            key = str(ans.get("repo_key") or "") if isinstance(ans, dict) else ""
            if key and key in units_by_key:
                continue        # another checkout of the same repository (a worktree, a copy): answered once
            answers.append((rel, ans))
            if key:
                units_by_key[key] = rel
            if ans is None:
                misses.append(f"{rel}: {miss}")
        for rel in repos:                 # the keys of repositories that did not answer this question too
            try:
                key = self._repo_keys.get(os.path.join(ws, rel)) if isinstance(self._repo_keys, dict) else None
            except Exception:
                key = None
            if key:
                units_by_key.setdefault(str(key), rel)
        q = str((params or {}).get("q") or "")
        merged = _merge_folder_answers(answers, query=q, k=int((params or {}).get("k") or 0),
                                       units_by_key=units_by_key)
        self._fresh = {}
        self._last_miss = "; ".join(misses)[:600] if merged is None else ""
        if merged is not None and misses:
            merged["partial"] = misses[:20]
        return merged

    def _vault_meta(self, ans: dict) -> dict[str, Any]:
        """Where an answer comes from -- and, for a server's repo, how fresh its copy is: the server's HEAD and the
        copy's commit, and why it is old when it is (never a silent "0 matches" from an old copy)."""
        meta = {"source": "vault graph", "repo_key": ans.get("repo_key"), "synced_at": ans.get("synced_at")}
        if ans.get("partial"):
            # a folder: the repositories that did not answer, and why -- an answer from the others is never complete
            # (live 2026-11-06: the SDK's 502 vanished and the answer said "not a definition in the graph")
            meta["partial"] = list(ans["partial"])
        fresh = getattr(self, "_fresh", None) or {}
        if fresh and fresh.get("server") and str(ans.get("repo_key") or "") in ("", *self._repo_keys.values()):
            meta["freshness"] = dict(fresh)
        return meta

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
        if (not target or target == "local") and self._is_units_workspace(self.resolve_workspace(root)):
            # a folder of repositories: each one's profile (report 06.11 #2: only the first -- the gateway -- showed)
            ans = self._ask("GET", "/v1/memory/code/profile", root, target)
            profs = list(((ans or {}).get("data") or {}).get("items") or [])
            if profs:
                return {"status": "ok", "workspace": self.resolve_workspace(root), "source": "vault graph",
                        "repositories": [{"repo": p.get("repo"), **{k: p.get(k) for k in _PROFILE_KEYS if k in p}}
                                         for p in profs],
                        **({"partial": ans["partial"]} if ans.get("partial") else {})}
        prof = self._vault_profile(root, target)
        if prof is not None:
            return {"status": "ok", "workspace": self.resolve_workspace(root) if not target else root,
                    "profile": prof, "source": "vault graph"}
        return self._remote_unavailable(target, root) or _coarse(self._local_repo_profile(root))

    def _local_repo_profile(self, root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            return self._units_profile(self.resolve_workspace(root))
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
            # the repo's map once per commit in this session; after that a line (MCP audit 2026-10-25: every orient
            # repeated the whole profile and its top symbols)
            seen = f"{prof.get('repo_key') or ans.get('repo_key')}@{prof.get('git_ref') or ''}"
            shown = getattr(self, "_profiles_shown", set())
            profile = ({key: prof.get(key) for key in _PROFILE_KEYS if key in prof} if seen not in shown else
                       f"as in this session's first orient of this repo at {prof.get('git_ref') or '?'} -- repo_profile "
                       "gives it again")
            shown.add(seen)
            self._profiles_shown = shown
            out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root), "query": query,
                   "profile": profile, "matches": matches,
                   "semantic": ans.get("semantic"), "best_match": ans.get("best_match"), **self._vault_meta(ans)}
            self._record_read("orient", returned_text=json.dumps(out, ensure_ascii=False), root=root,
                              paths=[] if target and target != "local" else None)
            return out
        return self._remote_unavailable(target, root) or _coarse(self._local_orient(query, k, root))

    def _local_orient(self, query: str, k: int = 8, root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            ws = self.resolve_workspace(root)
            return {**self._units_search(ws, query, k, None, None), "profile": self._units_profile(ws)["profile"]}
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import search_code as _search_code

        prof = svc.repo_profile()
        srch = _search_code(svc, query, k=k)
        raw_matches = (srch.get("data") or {}).get("items", [])
        matches = _normalize_search_matches(raw_matches, ws, query, k=k)
        text = json.dumps({"profile": prof, "matches": matches}, ensure_ascii=False)
        matched_paths = [str(m.get("path") or m.get("file") or "") for m in matches]
        self._record_read("orient", returned_text=text, paths=matched_paths, root=ws)
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
        """``kind``: a file kind (document | code | data | mail | image | config) filters by what the file is;
        any other value is a symbol kind, as before."""
        if kind not in _FILE_KINDS:
            return self._search_code_any(query, k, kind, path_glob, root, target)
        from imperal_sdk.universal.kinds import kind_of
        if kind not in ("code", "config") and not (target and target != "local"):
            # documents, sheets, mail and images live only in the local index (the vault's code map never holds
            # them): asking the vault first answered an empty list (final review 2026-11-04)
            out = self._local_search_code(query, k=k * 4, kind=None, path_glob=path_glob, root=root)
        else:
            out = self._search_code_any(query, k * 4, None, path_glob, root, target)
        out["matches"] = [m for m in out.get("matches") or []
                          if kind_of(str(m.get("path") or m.get("file") or "")) == kind][:k]
        out["total"] = len(out["matches"])
        return out

    def _search_code_any(self, query: str, k: int, kind: str | None, path_glob: str | None, root: str | None,
                         target: str | None) -> dict[str, Any]:
        ans = self._vault_search(query, k, kind, path_glob, root, target)
        if ans is not None:
            matches = list((ans.get("data") or {}).get("items") or [])[:k]
            self._record_read("search_code", returned_text=json.dumps(matches, ensure_ascii=False), root=root,
                              paths=[] if target and target != "local" else None)
            return {"status": "ok", "workspace": root if target else self.resolve_workspace(root), "query": query,
                    "matches": matches, "total": len(matches), "semantic": ans.get("semantic"),
                    "best_match": ans.get("best_match"), **self._vault_meta(ans)}
        return self._remote_unavailable(target, root) or _coarse(
            self._local_search_code(query, k=k, kind=kind, path_glob=path_glob, root=root))

    def _local_search_code(self, query: str, k: int = 10, kind: str | None = None, path_glob: str | None = None,
                           root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            return self._units_search(self.resolve_workspace(root), query, k, kind, path_glob)
        ws, svc, _ = self._get_indexer(root)
        from webbee.intel.query import search_code as _search_code

        res = _search_code(svc, query, k=k, kind=kind, path_glob=path_glob)
        raw_matches = (res.get("data") or {}).get("items", [])
        matches = _normalize_search_matches(raw_matches, ws, query, k=k, kind=kind, path_glob=path_glob)
        text = json.dumps(matches, ensure_ascii=False)
        matched_paths = [str(m.get("path") or m.get("file") or "") for m in matches]
        self._record_read("search_code", returned_text=text, paths=matched_paths, root=ws)
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
            self._record_read("graph_slice", returned_text=json.dumps(items, ensure_ascii=False), root=root,
                              paths=[] if target and target != "local" else None)
            out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root),
                   "symbols": [lean_slice_item(i) for i in items], **self._vault_meta(ans)}
            found = {str(i.get("qualname") or i.get("title") or "").rsplit(".", 1)[-1] for i in items} | {
                str(i.get("qualname") or "") for i in items}
            missing = [s for s in sym_list if s.split("::")[-1] not in found and s.split("::")[-1].rsplit(".", 1)[-1]
                       not in found]
            if missing:      # an empty slice is "not in the graph", never a silent ok (MCP audit 2026-10-25)
                out["not_found"] = missing
                out["note"] = (f"{', '.join(missing)}: not a definition in the repositories that answered -- "
                               f"{len(ans['partial'])} did not answer (see partial)" if ans.get("partial") else
                               f"{', '.join(missing)}: not a definition in the code graph of this repo")
            return out
        return self._remote_unavailable(target, root) or {**self._local_graph_slice(symbols, depth, root), "coarse": COARSE}

    def _units_graph_slice(self, ws: str, sym_list: list, depth: int = 1) -> dict:
        """graph_slice over each repository of a folder (field report 06.11 #3: at a folder root it raised "is not a
        repository ... pass root=" while impact and search answered)."""
        from webbee.intel.query import graph_slice as _graph_slice
        items: list = []
        waiting = []
        for u, svc in self._unit_services(ws):
            if getattr(svc, "index", None) is None:
                waiting.append(u["root"])
                continue
            res = _graph_slice(svc, sym_list, depth)
            items += [_in_folder(dict(it), u["root"]) for it in (res.get("data") or {}).get("items", [])]
        out = {**self._units_status(waiting), "workspace": ws, "symbols": items, "units": self.units_progress(ws),
               "source": "local index (units)"}
        found = {str(i.get("qualname") or i.get("title") or "").rsplit(".", 1)[-1] for i in items}
        missing = [s for s in sym_list if s.split("::")[-1].rsplit(".", 1)[-1] not in found]
        if missing and not waiting:
            out["not_found"], out["note"] = missing, f"{', '.join(missing)}: not a definition in any repository here"
        return out

    def _units_contract_slice(self, ws: str, symbols, query: str = "", kind: str = "all", k: int = 50) -> dict:
        """contract_slice over each repository of a folder: their endpoints, the symbols' slices, and the endpoints the
        symbols reach through their callers."""
        from imperal_sdk.code_links import contracts_reached
        from webbee.intel.query import contract_slice as _contract_slice
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        sl = self._units_graph_slice(ws, sym_list) if sym_list else {"symbols": []}
        endpoints, matched, waiting = [], [], []
        q = str(query or "").lower()               # a symbol reaches its endpoints by its callers, never by substring
        for u, svc in self._unit_services(ws):
            if getattr(svc, "index", None) is None:
                waiting.append(u["root"])
                continue
            all_eps = [_in_folder(dict(it), u["root"]) for it in
                       ((_contract_slice(svc, query="", kind=kind, k=500).get("data") or {}).get("items") or [])]
            endpoints += [e for e in all_eps if e.get("kind") == "endpoint"]
            matched += [e for e in all_eps if q and q in json.dumps(e).lower()]

        def callers_of(names):
            got = sl if list(names) == sym_list else self._units_graph_slice(ws, list(names))
            out: dict = {}
            for it in got.get("symbols") or []:
                name = str(it.get("qualname") or it.get("title") or "").rsplit(".", 1)[-1]
                out.setdefault(name, []).extend(
                    (c.get("user") if isinstance(c, dict) else str(c)) for c in it.get("callers") or []
                    if c and (not isinstance(c, dict) or c.get("user") not in ("", None, "(module)")))
            return out
        reached = contracts_reached(sym_list, endpoints, callers_of) if sym_list else []
        ids = {e.get("id") for e in reached}
        return {**self._units_status(waiting), "workspace": ws,
                "contracts": (reached + [e for e in matched if e.get("id") not in ids])[:k],
                "symbols": sl.get("symbols") or [], "source": "local index (units)"}

    def _local_graph_slice(self, symbols: list[str] | str, depth: int = 1, root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            return self._units_graph_slice(self.resolve_workspace(root),
                                           [symbols] if isinstance(symbols, str) else list(symbols or []), depth)
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
        self._record_read("graph_slice", returned_text=text, paths=matched_paths, root=ws)
        return {"status": "ok", "workspace": ws, "symbols": items}

    def impact_of_change(self, symbols: list[str] | str, root: str | None = None,
                         target: str | None = None) -> dict[str, Any]:
        sym_list = [symbols] if isinstance(symbols, str) else list(symbols or [])
        ans = self._ask("POST", "/v1/memory/code/impact", root, target, body={"symbols": sym_list})
        if ans is not None:
            items = list((ans.get("data") or {}).get("items") or [])
            # files that only CHANGED TOGETHER with it in git history are no users of it: named apart, briefly (MCP
            # audit 2026-10-25: 31 "dependents" of a private method, 15-21 KB, none of them calling it)
            together = sorted((it for it in items if it.get("via") == "measured"
                               and str(it.get("origin") or "") == "changed together"),
                              key=lambda it: -float(it.get("confidence") or 0))
            items = [it for it in items if it not in together]
            # a vault since 06.11 #3 names them itself, apart from the items ({path, confidence}), with their count
            together += [{"title": c.get("path"), "confidence": c.get("confidence")}
                         for c in ans.get("changed_together") or [] if isinstance(c, dict)]
            together_count = max(len(together), int(ans.get("changed_together_count") or 0))
            # a user two steps away is one only through a user one step away -- never through a file that merely
            # changed together (MCP audit 2026-10-25: four tests "depended" on a private method via such files)
            near = {str(it.get("id") or "") for it in items if int(it.get("depth") or 1) <= 1}
            items = [it for it in items if int(it.get("depth") or 1) <= 1
                     or str(it.get("uses") or "") in near
                     or any(str(t).split("::", 1)[0] in near for t in it.get("targets") or [])]
            items = code_first(items)
            files = [it.get("title") or it.get("id") for it in items]
            self._record_read("impact_of_change", returned_text=json.dumps(items, ensure_ascii=False), root=root,
                              paths=[] if target and target != "local" else None)
            out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root),
                   "queried_symbols": sym_list, "dependent_files": files, "items": items,
                   "changed_together": [f"{it.get('title') or it.get('id')} ({float(it.get('confidence') or 0):.1f})"
                                        for it in together[:_TOGETHER_SHOWN]]
                   + ([f"+{together_count - min(len(together), _TOGETHER_SHOWN)} more"]
                      if together_count > min(len(together), _TOGETHER_SHOWN) else []),
                   "same_file": ans.get("same_file") or [], "by_name_count": ans.get("by_name_count"),
                   "by_name": ans.get("by_name") or [],      # found only by name (an instance's method), marked
                   **({"summary": ans["summary"]} if ans.get("summary") else {}),
                   **self._vault_meta(ans)}
            if "resolved" in ans and not ans.get("resolved"):
                out["note"] = (f"{', '.join(sym_list)}: not a definition in the repositories that answered -- "
                               f"{len(ans['partial'])} did not answer (see partial): it may be defined there"
                               if ans.get("partial") else
                               f"{', '.join(sym_list)}: not a definition in the graph")     # not "0 dependents"
            return out
        return self._remote_unavailable(target, root) or _coarse(self._local_impact_of_change(symbols, root))

    def _local_impact_of_change(self, symbols: list[str] | str, root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            return self._units_impact(self.resolve_workspace(root),
                                      [symbols] if isinstance(symbols, str) else list(symbols or []))
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
        self._record_read("impact_of_change", returned_text=text, paths=matched_paths, root=ws)
        out = {
            "status": "ok",
            "workspace": ws,
            "queried_symbols": sym_list,
            "dependent_files": files,
            "items": items,
        }
        # the index's own honest parts: files that only name it, uses in its own file, the summary line (live
        # 2026-11-13: "1 more file only mentions the name" was dropped, so an import-only user read as "nobody")
        for key in _IMPACT_KEPT:
            if res.get(key) not in (None, [], ""):
                out[key] = res[key]
        return out

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
                # the text match is the asked query's only: a symbol's own name as a substring matched other handlers
                # (live 2026-11-06: _code -> POST /v1/auth/cli/codes of mint_code); a symbol reaches its endpoints
                # through contracts_reached (its handler, or a caller of it)
                q = str(query or "").lower()
                sl = self.graph_slice(sym_list, root=root, target=target) if sym_list else {"symbols": []}
                # the endpoints the asked symbols reach: a handler that is one, or calls one through its callers
                # (field report 06.11 #3: session_for_sid answered nothing -- the endpoint's handler calls it)
                reached = self._contracts_reached(sym_list, cat.get("endpoints") or [], sl, root, target)
                seen = {(e.get("repo"), e.get("method"), e.get("route"), e.get("handler")) for e in reached}
                eps = _one_per_contract(reached + [e for e in cat.get("endpoints") or []
                                                   if ((q and q in json.dumps(e).lower()) or (not q and not sym_list))
                                                   and (e.get("repo"), e.get("method"), e.get("route"),
                                                        e.get("handler")) not in seen])
                eps = eps[:k]
                names = [s.split("::")[-1].rsplit(".", 1)[-1].lower() for s in sym_list] + ([q] if q else [])
                # only the links that touch what was asked (MCP audit 2026-10-25: an unknown symbol got every link)
                links = _one_per_contract([ln for ln in cat.get("links") or [] if not names
                                           or any(n and n in json.dumps(ln).lower() for n in names)])[:k]
                out = {"status": "ok", "workspace": root if target else self.resolve_workspace(root),
                       "contracts": eps, "links": links, "symbols": sl.get("symbols") or [], "source": "vault graph"}
                if sl.get("not_found"):
                    out["not_found"], out["note"] = sl["not_found"], sl.get("note")
                if names and not (eps or links or out["symbols"]):
                    out["note"] = f"nothing in the code graph or its contracts matches {', '.join(sym_list) or query}"
                return out
            except Exception:
                pass
        return self._remote_unavailable(target, root) or {
            **self._local_contract_slice(symbols, query=query, kind=kind, k=k, root=root), "coarse": COARSE}

    def _contracts_reached(self, sym_list: list, endpoints: list, first_slice: dict, root, target) -> list:
        """``imperal_sdk.code_links.contracts_reached`` over the vault graph: callers asked by graph_slice."""
        if not sym_list or not endpoints:
            return []
        from imperal_sdk.code_links import contracts_reached

        def callers_of(names):
            got = first_slice if list(names) == list(sym_list) else self.graph_slice(list(names), root=root,
                                                                                       target=target)
            out: dict = {}
            for it in got.get("symbols") or []:
                name = str(it.get("qualname") or it.get("title") or "").rsplit(".", 1)[-1]
                users = [c.get("user") for c in it.get("callers_detail") or [] if isinstance(c, dict) and c.get("user")]
                out.setdefault(name, []).extend(users or [c for c in it.get("callers") or [] if isinstance(c, str)])
            return out
        return contracts_reached(sym_list, endpoints, callers_of)

    def _local_contract_slice(self, symbols: list[str] | str | None = None, query: str = "", kind: str = "all",
                              k: int = 50, root: str | None = None) -> dict[str, Any]:
        if self._is_units_workspace(self.resolve_workspace(root)):
            return self._units_contract_slice(self.resolve_workspace(root), symbols, query=query, kind=kind, k=k)
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
        self._record_read("contract_slice", returned_text=text, paths=matched_paths, root=ws)
        return {"status": "ok", "workspace": ws, **combined}

    def grep_code(self, pattern: str, root: str | None = None, target: str | None = None, path_glob: str | None = None,
                  k: int = 50, regex: bool = False) -> dict[str, Any]:
        """An exact text (or a regex) inside the code -- what the symbol search does not index (a string inside a
        function body). A server's repo: searched on the server itself (the vault holds the index, never the code); a
        local repo: its indexable files (never a secret, never a dependency tree)."""
        k = max(1, min(int(k or 50), 500))
        if regex and _NESTED_QUANTIFIER.search(str(pattern or "")):
            return {"status": "error", "error": "a nested quantifier (a repeated group around a repeated piece) can "
                                                "run without end -- use a literal or a simpler pattern"}
        if target and target != "local":
            # the code is searched where it lives: the vault holds its index, never its text (owner 2026-11-04)
            if not target.startswith("host:") or not root:
                return {"status": "error", "error": "an exact text is searched on the machine itself: pass "
                                                    "target=host:<alias> and root=<the repo there> (a panel "
                                                    "connection's files are searched by Webbee's tools there)"}
            _ensure_webbee_importable()
            from webbee import tools as wt
            import asyncio
            got = _off_thread(lambda: asyncio.run(wt.remote_grep(target[5:], str(root), str(pattern or ""), k,
                                                                 path_glob or "", bool(regex)))) or {}
            if got.get("why"):
                return {"status": "error", "workspace": root, "error": str(got["why"])}
            out = {"status": "ok", "workspace": root, "pattern": pattern, "matches": got.get("matches") or [],
                   "total": int(got.get("total") or 0), "truncated": bool(got.get("truncated")),
                   "source": f"{target} (searched there)"}
            return self._grep_out(out, pattern, regex)
        import fnmatch
        ws = self.resolve_workspace(root)
        if not _is_repository(ws) and not self._is_units_workspace(ws):
            # a folder INSIDE a repository is that repository, narrowed to the folder (MCP audit 2026-10-25: root=
            # <repo>/src was refused) -- a folder of no repository is still refused
            up = os.path.dirname(ws)
            while up and up != os.path.dirname(up) and not _is_repository(up):
                up = os.path.dirname(up)
            if not (up and _is_repository(up)):
                raise NotARepositoryError(f"{ws} is not a repository (no .git, no project manifest) -- pass root=<a "
                                          "repository inside it>")
            sub = os.path.relpath(ws, up).replace(os.sep, "/")
            path_glob = f"{sub}/{path_glob}" if path_glob else f"{sub}/*"
            ws = up
        _ensure_webbee_importable()
        rx = re.compile(pattern) if regex else None
        matches: list[dict[str, Any]] = []
        total = 0
        for rel in _grep_files(ws):
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
        return self._grep_out({"status": "ok", "workspace": ws, "pattern": pattern, "matches": matches,
                               "total": total, "truncated": total > len(matches), "source": "local files"},
                              pattern, regex)

    def _grep_out(self, out: dict[str, Any], pattern: str, regex: bool) -> dict[str, Any]:
        """A grep's answer, counted in token_savings (MCP audit 2026-10-25: grep_code was never counted); no match for
        a pattern that looks like a regex, searched as an exact text, is said -- never a silent 0 ("def a|def b"
        found nothing and read as "not in the code")."""
        # a server's grep (source "host:... (searched there)") has no local file to measure against
        remote = "searched there" in str(out.get("source") or "")
        self._record_read("grep_code", returned_text=json.dumps(out.get("matches") or [], ensure_ascii=False),
                          root=None if remote else out.get("workspace"), paths=[] if remote else None)
        if not regex and not out.get("matches") and re.search(r"\||\\[sdwb(]|\.\*|\[[^\]]+\]|\(\?", str(pattern or "")):
            out["note"] = ("searched as an EXACT text -- this pattern looks like a regex: pass regex=true (on a "
                           "server's repo: literal texts joined by |)")
        return out

    def _remote_outline(self, path: str, root: str | None, target: str) -> dict[str, Any]:
        ans = self._ask("GET", "/v1/memory/code/outline", root, target, params={"path": path})
        if ans is None:
            return self._remote_unavailable(target, root)
        nodes = list((ans.get("data") or {}).get("items") or ans.get("nodes") or [])
        rendered = f"OUTLINE of {path} (from the code graph):\n" + "\n".join(
            f"{n.get('start')}-{n.get('end')} {n.get('kind')} {n.get('name')}"
            + (f" -- {n['doc']}" if n.get("doc") else "") for n in nodes if isinstance(n, dict))
        return {"status": "ok", "workspace": root, "path": path, "symbol_count": len(nodes), "symbols": nodes,
                "rendered": rendered, **self._vault_meta(ans)}

    def _remote_read_symbol(self, path: str, name: str, root: str | None, target: str) -> dict[str, Any]:
        """A server file's definition or line range: WHERE from the code map (it holds the index, never the code --
        owner 2026-11-04), the LINES from the machine itself (``host:``, the user's own ssh). A panel connection
        (``ssh:``) only Webbee's tools reach: its answer is where the definition is, its signature and description."""
        m = re.fullmatch(r"L?(\d+)-(\d+)", str(name or ""))
        where: dict = {}
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
        else:
            ans = self._ask("POST", "/v1/memory/code/slice", root, target, body={"symbols": [f"{path}::{name}"],
                                                                                 "depth": 1})
            items = [i for i in ((ans or {}).get("data") or {}).get("items") or [] if isinstance(i, dict)]
            if not items:
                return self._remote_unavailable(target, root) if ans is None else {
                    "status": "error", "path": path, "symbol": name, "error": f"{name} is not in the code graph of {path}"}
            where = items[0]
            path = str(where.get("path") or path)
            lo, hi = int(where.get("start_line") or 1), int(where.get("end_line") or 1)
        head = (f"{where.get('signature') or ''}\n{where.get('doc') or ''}".strip() + "\n") if where else ""
        if not target.startswith("host:") or not root:
            return {"status": "ok", "workspace": root, "path": path, "symbol": where.get("qualname") or name,
                    "start_line": lo, "end_line": hi,
                    "rendered": f"[{path} lines {lo}-{hi}, from the code map: where it is, not its text]\n{head}"
                                f"(read these lines with Webbee's tools on {target})"}
        _ensure_webbee_importable()
        from webbee import tools as wt
        import asyncio
        got = _off_thread(lambda: asyncio.run(wt.remote_read(target[5:], str(root), path))) or {}
        if got.get("why"):
            return {"status": "error", "workspace": root, "path": path, "symbol": name, "error": str(got["why"])}
        lines = str(got.get("text") or "").split("\n")
        hi = min(hi, len(lines))
        if lo > hi:
            return {"status": "error", "workspace": root, "path": path, "symbol": name,
                    "error": f"lines {lo}-{hi}: past the end of {path} ({len(lines)} lines)"}
        rendered = f"[{path} lines {lo}-{hi} of {len(lines)}, read on {target}]\n" + "\n".join(lines[lo - 1:hi])
        self.tracker.record("read_symbol", returned_chars=len(rendered), returned_lines=hi - lo + 2,
                            files={f"{target}:{str(root or '').rstrip('/')}/{path}": len(got.get("text") or "")})
        return {"status": "ok", "workspace": root, "path": path, "symbol": where.get("qualname") or name,
                "start_line": lo, "end_line": hi, "rendered": rendered, "source": f"{target} (read there)"}

    def outline(self, path: str, root: str | None = None, target: str | None = None) -> dict[str, Any]:
        if target and target != "local":
            return self._remote_outline(path, root, target)
        _ensure_webbee_importable()
        from webbee.intel.outline import outline as _outline, render_outline

        ws = self.resolve_workspace(root)
        full, rel = _resolve_in_workspace(ws, path)
        if not os.path.lexists(full):
            return {"status": "error", "workspace": ws, "path": rel, "error": f"File not found: {rel}"}
        refused = _refused(ws, rel, full)
        if refused:
            return {"status": "error", "workspace": ws, "path": rel, "error": refused}
        alt = _view_for(ws, rel)
        if alt is not None and alt["skipped"]:
            return {"status": "error", "workspace": ws, "path": rel, "error": f"{rel}: {alt['skipped']}"}
        if alt is not None:
            source = alt["text"]
        else:
            if os.path.getsize(full) > _PARSE_CAP:
                return {"status": "error", "workspace": ws, "path": rel,
                        "error": f"{rel}: over {_PARSE_CAP // 1048576} MB -- read it by lines: read_symbol(path, "
                                 "\"L<a>-<b>\")"}
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError as exc:
                return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}

        total_lines = max(1, source.count("\n") + 1)
        nodes = alt["nodes"] if alt is not None else (_outline(rel, source) or [])
        rendered = render_outline(rel, nodes, total_lines)
        self.tracker.record("outline", returned_chars=len(rendered), returned_lines=max(1, rendered.count("\n") + 1),
                            files={rel: len(source)})
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
        if not os.path.lexists(full):
            return {"status": "error", "workspace": ws, "path": rel, "error": f"File not found: {rel}"}
        refused = _refused(ws, rel, full)
        if refused:
            return {"status": "error", "workspace": ws, "path": rel, "error": refused}
        span = re.fullmatch(r"L(\d+)-(\d+)", str(name or "").strip())
        alt = _view_for(ws, rel)
        if span and os.path.getsize(full) > _PARSE_CAP and (alt is None or "over" in alt["skipped"]):
            # a big text file (a log, a dump) by lines: streamed, never parsed or held whole
            a, b = max(1, int(span.group(1))), int(span.group(2))
            try:
                body, total = _lines_of(full, a, b)
            except OSError as exc:
                return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}
            b = min(b, total)
            if a > b:
                return {"status": "error", "workspace": ws, "path": rel, "symbol": name,
                        "error": f"Span '{name}' is past the end of {rel} ({total} lines)"}
            rendered = read_card(rel, total, a, b, body)
            self.tracker.record("read_symbol", returned_chars=len(rendered),
                                returned_lines=max(1, rendered.count("\n") + 1), files={rel: os.path.getsize(full)})
            return {"status": "ok", "workspace": ws, "path": rel, "symbol": f"L{a}-{b}", "kind": "lines",
                    "start_line": a, "end_line": b, "rendered": rendered}
        if alt is not None and alt["skipped"]:
            return {"status": "error", "workspace": ws, "path": rel, "error": f"{rel}: {alt['skipped']}"}
        if alt is not None:
            source = alt["text"]
        else:
            if os.path.getsize(full) > _PARSE_CAP:
                return {"status": "error", "workspace": ws, "path": rel,
                        "error": f"{rel}: over {_PARSE_CAP // 1048576} MB -- read it by lines: read_symbol(path, "
                                 "\"L<a>-<b>\")"}
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError as exc:
                return {"status": "error", "workspace": ws, "path": rel, "error": str(exc)}

        total_lines = max(1, source.count("\n") + 1)
        hit = _view_hit(source, alt["nodes"], name) if alt is not None else _read_symbol(rel, source, name)
        if hit is None:
            nodes = alt["nodes"] if alt is not None else (_outline(rel, source) or [])
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
        self.tracker.record("read_symbol", returned_chars=len(rendered),
                            returned_lines=max(1, rendered.count("\n") + 1), files={rel: len(source)})
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
        diff_text = _diff_for_paths(sg.diff(since=since), paths)
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



