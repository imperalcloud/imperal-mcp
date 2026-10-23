from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import threading
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
    """Per-session telemetry tracker comparing surgical tool output against the actual matched files on disk."""

    def __init__(self) -> None:
        self.calls: int = 0
        self.files_measured: int = 0
        self.lines_returned: int = 0
        self.lines_baseline: int = 0
        self.chars_returned: int = 0
        self.chars_baseline: int = 0
        self.by_tool: dict[str, dict[str, int]] = {}

    def record(
        self,
        tool: str,
        *,
        returned_chars: int,
        baseline_chars: int,
        returned_lines: int = 0,
        baseline_lines: int = 0,
        baseline_files: int = 1,
    ) -> dict[str, Any]:
        ret_c = max(0, int(returned_chars))
        base_c = max(0, int(baseline_chars))
        ret_l = max(0, int(returned_lines))
        base_l = max(0, int(baseline_lines))
        base_f = max(0, int(baseline_files))
        saved_c = max(0, base_c - ret_c)
        saved_l = max(0, base_l - ret_l)

        self.calls += 1
        self.files_measured += base_f
        self.chars_returned += ret_c
        self.chars_baseline += base_c
        self.lines_returned += ret_l
        self.lines_baseline += base_l

        slot = self.by_tool.setdefault(
            tool,
            {
                "calls": 0,
                "baseline_files": 0,
                "returned_chars": 0,
                "baseline_chars": 0,
                "saved_chars": 0,
                "returned_lines": 0,
                "baseline_lines": 0,
                "saved_lines": 0,
            },
        )
        call_pct = round((saved_c / base_c) * 100.0, 1) if base_c > 0 else 0.0

        slot["calls"] += 1
        slot["baseline_files"] += base_f
        slot["returned_chars"] += ret_c
        slot["baseline_chars"] += base_c
        slot["saved_chars"] += saved_c
        slot["returned_lines"] += ret_l
        slot["baseline_lines"] += base_l
        slot["saved_lines"] += saved_l

        return {
            "tool": tool,
            "baseline_basis": "matched_files_on_disk",
            "baseline_files": base_f,
            "returned_chars": ret_c,
            "baseline_chars": base_c,
            "saved_chars": saved_c,
            "returned_lines": ret_l,
            "baseline_lines": base_l,
            "saved_lines": saved_l,
            "compression_pct": call_pct,
            "session_calls": self.calls,
        }

    def summary(self) -> dict[str, Any]:
        saved_c = max(0, self.chars_baseline - self.chars_returned)
        saved_l = max(0, self.lines_baseline - self.lines_returned)
        pct = round((saved_c / self.chars_baseline) * 100.0, 1) if self.chars_baseline > 0 else 0.0
        return {
            "status": "ok",
            "baseline_basis": "matched_files_on_disk",
            "calls": self.calls,
            "baseline_files": self.files_measured,
            "returned_chars": self.chars_returned,
            "baseline_chars": self.chars_baseline,
            "saved_chars": saved_c,
            "returned_lines": self.lines_returned,
            "baseline_lines": self.lines_baseline,
            "saved_lines": saved_l,
            "compression_pct": pct,
            "by_tool": dict(self.by_tool),
        }


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
You are equipped with the Imperal MCP Exoskeleton for Claude Code.
Follow these operating rules to navigate repositories accurately, minimize unnecessary context reads, and keep changes safe:
1. ORIENT FIRST: Start tasks with `orient(query=...)` or `repo_profile()` instead of blind `grep`/`find`.
2. SURGICAL AST READS: Before reading a large code file, call `outline(path=...)` and then `read_symbol(path=..., name=...)` to read only the exact function/class/span needed.
3. IMPACT & CONTRACTS: Before editing shared functions or classes, call `impact_of_change(symbols=[...])` and `contract_slice(symbols=[...])`.
4. REVERSIBILITY (SHADOWGIT): Before risky multi-file edits, call `checkpoint(label=...)`. Use `checkpoint_diff()` to inspect changes and `checkpoint_rollback()` to restore a checkpoint without touching `.git`.
5. SYNTAX VERIFICATION: After editing a source file, call `check_syntax(path=...)` to verify AST cleanliness.
6. UNIFIED CLOUD MEMORY: Call `recall_context(query=...)` to load user directives/notes across Webbee, Telegram, and Panel, and `remember_fact(...)` / `save_repo_note(...)` to persist durable knowledge.
"""


class ExoskeletonRuntime:
    """Stateful local + cloud bridge for Imperal MCP Exoskeleton tools."""

    def __init__(self, workspace_root: str | None = None, workspace: str | None = None) -> None:
        self._default_root = _resolve_root(workspace or workspace_root)
        self.tracker = TokenSavingsTracker()
        self._indexers: dict[str, Any] = {}
        self._index_locks: dict[str, threading.Lock] = {}
        self._embed_threads: dict[str, threading.Thread] = {}
        self._shadows: dict[str, Any] = {}
        self._guard_lock = threading.Lock()

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
        if candidate != ws_real and not candidate.startswith(ws_real + os.sep):
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
        baseline_chars: int,
        baseline_lines: int,
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

    def repo_profile(self, root: str | None = None) -> dict[str, Any]:
        ws, svc, _ = self._get_indexer(root)
        prof = svc.repo_profile()
        return {"status": "ok", "workspace": ws, "profile": prof}

    def orient(self, query: str, k: int = 8, root: str | None = None) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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

    def graph_slice(self, symbols: list[str] | str, depth: int = 1, root: str | None = None) -> dict[str, Any]:
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

    def impact_of_change(self, symbols: list[str] | str, root: str | None = None) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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

    def outline(self, path: str, root: str | None = None) -> dict[str, Any]:
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

    def read_symbol(self, path: str, name: str, root: str | None = None) -> dict[str, Any]:
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



