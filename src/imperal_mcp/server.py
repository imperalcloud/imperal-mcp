from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:  # mcp >= 2.0 renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP, Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .client import ImperalClient
from .config import Config
from .gate import is_money, is_read_only, is_synthetic, classify_tier
from .irkit import (
    validate_ir as _validate_ir,
    ui_catalog_text,
    ir_spec_text,
    examples_text,
    build_prompt_text,
)
from .exoskeleton import EXOSKELETON_INSTRUCTIONS, ExoskeletonRuntime, app_summary
from .mask import defensive_scrub


def _tools_of(app: dict) -> list[dict]:
    """Normalize a get_app payload to a list of {name, action_type}.

    Handles all real shapes returned by the gateway:
    1. tools_json is a list → return directly.
    2. manifest_json is a dict → return manifest_json["tools"].
    3. manifest_json is a non-empty JSON string → parse it, return ["tools"].
    4. Anything else → [].
    """
    tj = app.get("tools_json")
    if isinstance(tj, list):
        return tj
    mj = app.get("manifest_json")
    if isinstance(mj, dict):
        return mj.get("tools", []) or []
    if isinstance(mj, str) and mj:
        try:
            parsed = json.loads(mj)
            return parsed.get("tools", []) or []
        except (json.JSONDecodeError, AttributeError):
            return []
    return []


async def _find_tool(client: ImperalClient, app_id: str, function: str) -> tuple[bool, str | None, list[str]]:
    """(the app has a tool of this name, its action_type, the names it has): the app's own record first, then the
    marketplace catalog. Live 2026-11-13: a name the app does not have was told "this MCP runs read-only tools only"
    -- "not found" and "no action_type" were one None."""
    names: list[str] = []
    app = await client.get_app(app_id)
    for t in _tools_of(app):
        names.append(str(t.get("name")))
        if t.get("name") == function:
            return True, t.get("action_type"), names
    try:
        mkt = await client.get_marketplace_app(app_id)
        for t in (mkt.get("tools") or []):
            names.append(str(t.get("name")))
            if t.get("name") == function:
                return True, t.get("action_type"), names
    except Exception:
        pass
    return False, None, [n for n in dict.fromkeys(names) if n and n != "None"]


async def _resolve_action_type(client: ImperalClient, app_id: str, function: str) -> str | None:
    return (await _find_tool(client, app_id, function))[1]


def _no_such_tool(app_id: str, function: str, names: list[str]) -> dict:
    shown = ", ".join(names[:30]) + (f" (+{len(names) - 30} more)" if len(names) > 30 else "")
    return {"refused": True, "status": "refused",
            "reason": f"app '{app_id}' has no tool '{function}'" + (f"; its tools: {shown}" if names else "")}


_TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "unavailable",
    "temporal", "connection", "503", "bad gateway", "try again",
)


def _is_transient(result: dict) -> bool:
    """A deploy failure that looks like a transient infra hiccup (worth one
    retry), vs a deterministic failure (validation/ownership/zero-tool) that a
    retry won't fix and would only add a fleet-wide catalog reload (AZV-3)."""
    err = str(result.get("error") or result.get("message") or "").lower()
    return any(m in err for m in _TRANSIENT_MARKERS)


async def deploy_ir_logic(client: ImperalClient, app_ir: dict, app_id: str) -> dict:
    """Deploy app_ir. Retry ONCE only on a transient-looking failure; a
    deterministic failure is returned as-is (truthful — DEP-3)."""
    result = await client.deploy_ir(app_id, app_ir)
    if result.get("status") != "success" and _is_transient(result):
        await asyncio.sleep(1.0)
        result = await client.deploy_ir(app_id, app_ir)
    if result.get("status") != "success" and not result.get("error"):
        result = {**result, "error": str(result.get("message") or "deploy did not complete")}
    return result


async def run_read_tool_logic(client: ImperalClient, app_id: str, function: str, args: dict) -> Any:
    if is_synthetic(function):
        return {"refused": True, "reason": "synthetic system entry, not a callable tool"}
    found, action_type, names = await _find_tool(client, app_id, function)
    if not found:
        return _no_such_tool(app_id, function, names)
    if not is_read_only(function, action_type):
        return {"refused": True,
                "reason": f"tool '{function}' is action_type={action_type!r}; "
                          "this MCP runs read-only tools only"}
    out = await client.run_tool(app_id, function, args or {})
    return defensive_scrub(out)


class Autopilot:
    """Per-process session holder for destructive-op autopilot. HUMAN-ONLY toggle:
    only a human 'autopilot' elicitation response flips `enabled` on — never the agent,
    never the kernel. CONTROL != BYPASS: the kernel still re-grades/audits every op."""
    def __init__(self) -> None:
        self.enabled = False


_AUTOPILOT = Autopilot()  # per-process session state


class _DestructiveConsent(BaseModel):
    decision: Literal["approve_once", "autopilot", "reject"] = Field(
        description=("approve_once = run this ONE destructive operation; "
                     "autopilot = run this AND stop asking for the rest of this session; "
                     "reject = do not run"))


def _consent_from_elicit(result: Any) -> str:
    """Map an mcp ElicitationResult -> approve_once|autopilot|reject.
    Declined / Cancelled / anything non-accept -> reject (fail-safe)."""
    if getattr(result, "action", None) == "accept":
        dec = getattr(getattr(result, "data", None), "decision", None)
        if dec in ("approve_once", "autopilot", "reject"):
            return dec
    return "reject"


def _destructive_prompt(app_id: str, function: str, args: dict) -> str:
    """Human-readable consent prompt for a destructive op. Built from the
    tool identity + args (NOT a kernel card — the headless operate path does
    not reliably emit one, so consent is obtained here BEFORE any execution)."""
    try:
        argstr = json.dumps(args or {}, ensure_ascii=False)[:400]
    except Exception:
        argstr = str(args)[:400]
    return (f"DESTRUCTIVE operation requested: {app_id}.{function}\n"
            f"args: {argstr}\n"
            "This will execute immediately on approval. Approve once, enable "
            "autopilot (stop asking for the rest of this session), or reject?")


def _shape(res: Any) -> dict:
    """Kernel {kind,...} -> a compact status envelope, PII-masked."""
    if not isinstance(res, dict):
        return {"status": "error", "detail": "non-dict kernel result"}
    if res.get("kind") == "tool_result":
        content = res.get("content")
        if isinstance(content, dict) and "error" in content:
            return {"status": "error", "detail": defensive_scrub(content)}
        return {"status": "ok", "result": defensive_scrub(content)}
    return {"status": "error", "detail": "unexpected kernel kind"}


_MONEY_REFUSED_ERRORS = ("money_release_denied", "money_release_already_consumed_or_expired")


async def run_write_tool_logic(client, ctx, app_id, function, args, autopilot) -> dict:
    """Run a write/destructive tool via the guarded /operate seam.
    - money -> ALWAYS out-of-band panel approval (ctx.elicit_url), checked FIRST,
      before read/write/destructive classification and before autopilot. Money
      NEVER goes through terminal consent or session autopilot.
    - read  -> refused (use run_read_tool)
    - blocked (synthetic/legacy/unknown) -> refused
    - write -> operate(bypass=False) once, return shaped result
    - destructive -> consent FIRST (ctx.elicit, or session autopilot); ONLY on
      approval operate(bypass=True). NEVER call operate before consent.
    The kernel bills/audits every op (CONTROL != BYPASS). The terminal consent
    gate lives HERE: the headless operate path does NOT reliably emit a kernel
    confirmation card (it auto-executes when the principal's confirmation policy
    is absent/off), so relying on a card would silently execute destructive ops.
    The unforgeable money wall is the out-of-band panel (Plan 2): the kernel
    returns panel_approval_required and refuses to execute until a browser-JWT
    panel release; the re-call after release returns the real tool_result."""
    if is_money(app_id, function):
        res = await client.operate(app_id, function, args or {}, confirmation_bypassed=False)
        if isinstance(res, dict) and res.get("kind") == "panel_approval_required":
            try:
                await ctx.elicit_url(
                    message="Approve this charge in your Imperal panel",
                    url=res.get("panel_url", ""),
                    elicitation_id=res.get("confirmation_id", ""),
                )
            except Exception:
                pass  # host lacks url-elicitation -> the panel_url is in the return payload
            return {"status": "pending_panel_approval",
                    "confirmation_id": res.get("confirmation_id"),
                    "panel_url": res.get("panel_url"), "summary": res.get("summary"),
                    "note": "Approve in your panel, then re-run this tool to complete."}
        if isinstance(res, dict) and res.get("kind") == "tool_result":
            content = res.get("content") or {}
            if isinstance(content, dict) and content.get("error") in _MONEY_REFUSED_ERRORS:
                return {"status": "refused", "reason": content.get("status") or content.get("error")}
            return _shape(res)
        return {"status": "error", "detail": "unexpected money result"}
    # ── existing read/blocked/write/destructive tiers (Plan 1) unchanged below ──
    found, action_type, names = await _find_tool(client, app_id, function)
    if not found:
        return _no_such_tool(app_id, function, names)
    tier = classify_tier(function, action_type)
    if tier == "read":
        return {"status": "refused", "reason": "use run_read_tool"}
    if tier == "blocked":
        return {"status": "refused", "reason": "not a runnable write/destructive tool"}
    if tier == "write":
        res = await client.operate(app_id, function, args or {}, confirmation_bypassed=False)
        return _shape(res)
    # tier == "destructive": consent MUST precede execution. Do NOT call operate
    # until approved — the kernel would execute a bypass=False destructive
    # directly when confirmation policy is absent (LIVE 2026-07-02).
    consent = "autopilot"
    if not autopilot.enabled:
        if ctx is None:
            # Fail-safe: no elicitation channel (a non-compliant host that didn't
            # inject Context) -> refuse rather than AttributeError on None.elicit.
            return {"status": "refused", "reason": "no elicitation channel to confirm a destructive operation"}
        result = await ctx.elicit(
            message=_destructive_prompt(app_id, function, args or {}),
            schema=_DestructiveConsent,
        )
        decision = _consent_from_elicit(result)
        if decision == "reject":
            return {"status": "refused", "reason": "human_rejected"}
        if decision == "autopilot":
            autopilot.enabled = True
        consent = "elicited" if decision == "approve_once" else "autopilot"
    res = await client.operate(app_id, function, args or {}, confirmation_bypassed=True)
    out = _shape(res)
    out["consent"] = consent
    return out


LIVE_SESSIONS_CHARS = 6000   # live_sessions' overview bound; the field test's answer was 13 500 characters
_LIST_TOOLS = frozenset({"impact_of_change", "graph_slice", "orient", "search_code", "grep_code", "contract_slice"})

# What a parameter means where its name alone does not say it: (tool, name) first, then the name in any tool.
# root / target / k / full / path carry none: the protocol says once what root and target are, and a hint
# repeated in sixteen tools cost 2 521 characters of every session (measured 2026-11-13).
PARAM_HINTS: dict = {
    "path_glob": "Only paths matching it, e.g. src/**/*.py.",
    "kind": "function, class, method or variable.",
    "symbols": "name, Class.method or path::name each.",
    "conversation": "Another conversation's id (live_sessions, search_history); empty: this one.",
    ("read_symbol", "name"): "A symbol (function, Class.method, a section's name) or a line range such as L120-180.",
    ("grep_code", "pattern"): "The exact text to find; a regular expression when regex=true.",
    ("graph_slice", "depth"): "How many call hops to follow.",
    ("task", "items"): "The plan: [{content, status: pending|in_progress|completed}]; a blocked item: status blocked "
                       "and blocked_on = what it waits for.",
    ("state_lens", "section"): "law, plan, reality, memory, conversation, path or all.",
    ("state_lens", "focus"): "A word to narrow the section to.",
    ("recall", "ref"): "U<n> (a request), A<n> (an answer), last_answers or all.",
    ("recall", "n"): "How many messages from ref on.",
    ("vault_log_read", "ref"): "The vault://logs/... reference the frame or a tool gave.",
    ("vault_log_read", "grep"): "Only the lines holding this text.",
    ("vault_log_read", "limit"): "Characters to read (0: the default page).",
    ("live_sessions", "minutes"): "Sessions active within this many minutes.",
    ("checkpoint", "label"): "A short name for the snapshot.",
    ("checkpoint_diff", "target"): "A checkpoint's number or id; default: the latest.",
    ("checkpoint_diff", "paths"): "Only these files or folders, relative to root.",
    ("checkpoint_rollback", "target"): "A checkpoint's number or id; default: the latest.",
    ("login", "again"): "true: start a new sign-in even though one is saved (an expired session).",
    ("remember_fact", "category"): "directive, preference, infra, convention or identity.",
    ("remember_fact", "scope"): "global, task or surface; empty: decided from the fact itself.",
    ("save_repo_note", "repo"): "The repository's name; default: the workspace's folder name.",
    ("save_repo_note", "citations"): "Where the note comes from: file paths, symbols, links.",
    ("recall_context", "include_resolved"): "true: also the notes marked resolved.",
    ("smoke_ir", "function"): "The function of the app to run.",
    ("run_read_tool", "function"): "The tool's name as get_app lists it.",
    ("run_write_tool", "function"): "The tool's name as get_app lists it.",
    ("run_read_tool", "tool"): "Same as function.",
    ("run_write_tool", "tool"): "Same as function.",
    ("upload_file", "path"): "The file's path on this machine.",
    ("upload_file", "name"): "The name to store it under; default: the file's own name.",
}


def lean_schema(tool: str, schema: dict) -> dict:
    """The input schema an agent reads, without the generator's noise: no per-field title, an optional field is its
    type (not anyOf [type, null] with default null), and each field whose name does not say it carries a hint.
    Arguments are still checked by the function's own signature; this is only what the listing shows.

    Live 2026-11-13: the 35 schemas were 10 801 characters of the 22 214 every session loads."""
    def one(name: str, field: dict) -> dict:
        f = {k: v for k, v in field.items() if k != "title"}
        alts = f.get("anyOf")
        if isinstance(alts, list) and {"type": "null"} in alts and f.get("default", 0) is None:
            rest = [a for a in alts if a != {"type": "null"}]
            f.pop("anyOf")
            f.pop("default")
            f.update(rest[0] if len(rest) == 1 else {"anyOf": rest})
        hint = PARAM_HINTS.get((tool, name)) or PARAM_HINTS.get(name)
        if hint and "description" not in f:
            f["description"] = hint
        return f

    out = {k: v for k, v in schema.items() if k != "title"}
    out["properties"] = {n: one(n, f) for n, f in (schema.get("properties") or {}).items()}
    return out


def build_server(client: ImperalClient, workspace: str | None = None) -> FastMCP:
    mcp = FastMCP("imperal", instructions=EXOSKELETON_INSTRUCTIONS)
    exo = ExoskeletonRuntime(workspace=workspace, client=client)

    mcp._exoskeleton = exo      # the runtime behind the tools (tests read its exchange)

    def _recorded(tool: str, result: Any, **kwargs: Any) -> Any:
        """A code tool's call joins the exchange the agent's next frame carries (phase B)."""
        import json as _json
        ok = not (isinstance(result, dict) and (result.get("ok") is False or result.get("status") == "error"))
        exo.record_call(tool, kwargs, ok=ok, text=_json.dumps(result, ensure_ascii=False, default=str)[:2000])
        return result

    async def _exo_call(fn, **kwargs):
        """A code tool runs on a worker thread; its cloud calls run on this (the server's) loop."""
        import asyncio
        exo.loop = asyncio.get_running_loop()
        full = bool(kwargs.pop("full", False))
        try:
            out = await asyncio.to_thread(fn, **kwargs)
        except ImportError as exc:
            # live 2026-11-13: the registry's `uvx imperal-mcp` lists every code tool; without the [code] extra
            # orient answered a bare "No module named 'webbee'" -- each code tool now says what to install
            from .exoskeleton import MISSING_CODE_DEPENDENCY_MESSAGE, missing_code_extra
            if not missing_code_extra(exc):
                raise
            out = {"ok": False, "status": "error", "error": MISSING_CODE_DEPENDENCY_MESSAGE}
        if fn.__name__ in _LIST_TOOLS and not full:      # a list answer stays within the model's reach (Task 8)
            from .exoskeleton import bounded
            out = bounded(out)
        return _recorded(fn.__name__, out, **kwargs) if fn.__name__ not in ("frame", "task", "lens") else out

    # ── Exoskeleton: Local Code Intelligence & AST Surgery ──────────────────

    @mcp.tool(
        title="Orient on a Task",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def orient(query: str, k: int = 8, root: str | None = None, target: str | None = None) -> dict:
        """Start here on a code task: the repository's profile plus the symbols and snippets that best match your
        query, ranked from the code graph. Then outline or read_symbol what it points at."""
        return await _exo_call(exo.orient, query=query, k=k, root=root, target=target)

    @mcp.tool(
        title="Repository Profile",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def repo_profile(root: str | None = None, target: str | None = None) -> dict:
        """The repository at a glance: languages, file count and its most-used definitions."""
        return await _exo_call(exo.repo_profile, root=root, target=target)

    @mcp.tool(
        title="Search Code",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def search_code(
        query: str,
        k: int = 10,
        kind: str | None = None,
        path_glob: str | None = None,
        root: str | None = None,
        target: str | None = None,
    ) -> dict:
        """Find code by exact name, words or meaning; each hit says how sure it is. Use it instead of grep/find to
        locate a symbol."""
        return await _exo_call(exo.search_code, query=query, k=k, kind=kind, path_glob=path_glob, root=root, target=target)

    @mcp.tool(
        title="Outline a File",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def outline(path: str, root: str | None = None, target: str | None = None, full: bool = False) -> dict:
        """A file's structure without its body: classes, functions, methods and sections with their line ranges. Use it
        before opening a large file; full=true adds the symbols as JSON."""
        # a worker thread like every code tool: its cloud call must never wait for the loop it would block
        out = await _exo_call(exo.outline, path=path, root=root, target=target)
        if not full and isinstance(out, dict) and out.get("rendered"):
            # live 2026-11-13: each symbol came twice, as JSON and in `rendered` (exoskeleton.py: 20 562 -> 6 906 chars)
            out = {k: v for k, v in out.items() if k != "symbols"}
        return out

    @mcp.tool(
        title="Read a Symbol",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def read_symbol(path: str, name: str, root: str | None = None, target: str | None = None) -> dict:
        """Read one symbol (function, class, Class.method, section) or a line range such as "L120-180" from a file,
        instead of the whole file."""
        return await _exo_call(exo.read_symbol, path=path, name=name, root=root, target=target)

    @mcp.tool(
        title="Callers and Callees",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def graph_slice(symbols: list[str], depth: int = 1, root: str | None = None, target: str | None = None) -> dict:
        """For each symbol: where it is defined, its signature, who calls it and what it calls (depth = how many hops)."""
        return await _exo_call(exo.graph_slice, symbols=symbols, depth=depth, root=root, target=target)

    @mcp.tool(
        title="API Contracts",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def contract_slice(symbols: list[str], root: str | None = None, target: str | None = None) -> dict:
        """The endpoints and routes across the user's repositories and who calls them, plus the given symbols with
        their callers. Use it before changing an API either side depends on."""
        return await _exo_call(exo.contract_slice, symbols=symbols, root=root, target=target)

    @mcp.tool(
        title="Impact of a Change",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def impact_of_change(symbols: list[str], root: str | None = None, target: str | None = None,
                               full: bool = False) -> dict:
        """Before you edit shared code: every file and call site that depends on these symbols, code first and tests
        after. Bounded to the first entries with totals unless full=true."""
        return await _exo_call(exo.impact_of_change, symbols=symbols, root=root, target=target, full=full)

    @mcp.tool(
        title="Declare Task and Plan",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def task(goal: str, items: list[dict] | None = None, root: str | None = None) -> dict:
        """Declare what you were asked and your plan as items {content, status: pending|in_progress|completed}. The
        kernel marks an item proven only by what it measured (a diff, a check that exits 0, a sourced finding).
        Needs login."""
        return await _exo_call(exo.task, goal=goal, items=items or [], root=root)

    @mcp.tool(
        title="Frame",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    )
    async def frame(root: str | None = None, target: str | None = None) -> dict:
        """Your step frame from the Imperal kernel: the task and plan with what is proven and what is only claimed, the
        code around your focus, what a change reaches, the machines and repos, your path so far. Call it at the
        start and after each change. Costs credits; needs login."""
        return await _exo_call(exo.frame, root=root, target=target)

    @mcp.tool(title="Grep Text", annotations=ToolAnnotations(readOnlyHint=True))
    async def grep_code(pattern: str, root: str | None = None, target: str | None = None, path_glob: str | None = None,
                        k: int = 50, regex: bool = False) -> dict:
        """Exact text or a regex in the repository's text files (code, configs, docs): a string inside a function body
        or a setting the symbol search does not index. Secret files are never searched."""
        return await _exo_call(exo.grep_code, pattern=pattern, root=root, target=target, path_glob=path_glob, k=k,
                               regex=regex)

    @mcp.tool(title="State Lens", annotations=ToolAnnotations(readOnlyHint=True))
    async def state_lens(section: str = "all", focus: str = "", offset: int = 0, conversation: str = "") -> dict:
        """Open one section of what the kernel holds for this session (law, plan, reality, memory, conversation, path):
        where the frame's counted lines point. conversation=<id> reads another live session of the user."""
        args: dict = {"section": section, "focus": focus, "offset": offset}
        if conversation:
            args["conversation"] = conversation
        return await _exo_call(exo.lens, tool="state_lens", args=args)

    @mcp.tool(title="Recall a Message", annotations=ToolAnnotations(readOnlyHint=True))
    async def recall(ref: str, offset: int = 0, n: int = 1, conversation: str = "") -> dict:
        """A past request or answer in full: ref = U<n>, A<n>, last_answers or all; of this session, or of another
        conversation by the id search_history gives."""
        args: dict = {"ref": ref, "offset": offset, "n": n}
        if conversation:
            args["conversation"] = conversation
        return await _exo_call(exo.lens, tool="recall", args=args)

    @mcp.tool(title="Search Past Conversations", annotations=ToolAnnotations(readOnlyHint=True))
    async def search_history(query: str, limit: int = 10) -> dict:
        """Find the user's past conversations (Webbee, the panel, Telegram, other shells) that contain a text; open a
        hit with recall(ref, conversation=...)."""
        return await _exo_call(exo.lens, tool="search_history", args={"query": query, "limit": limit})

    @mcp.tool(title="Live Sessions", annotations=ToolAnnotations(readOnlyHint=True))
    async def live_sessions(minutes: int = 120, limit: int = 8, full: bool = False) -> dict:
        """The user's other sessions active in the last N minutes (Webbee, other shells, the panel, Telegram): each
        with its last request, steps and answer, shortened (full=true: whole). Read-only; open one with recall or
        state_lens(conversation=...)."""
        out = await _exo_call(exo.lens, tool="live_sessions", args={"minutes": minutes, "limit": limit})
        if full:
            return out
        from .exoskeleton import bounded
        # an overview, not the sessions' transcripts (field test 2026-11-13: 13.5 KB for one call)
        return bounded(out, limit=LIVE_SESSIONS_CHARS)

    @mcp.tool(title="Message a Live Session", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def message_session(conversation: str, text: str) -> dict:
        """Send a note to another live session of the user: a finding to check, a question, what you are doing so you
        do not both do it. It arrives as an agent's words, never the user's, so it approves nothing. The reply shows
        up in your frame."""
        return await _exo_call(exo.lens, tool="message_session", args={"conversation": conversation, "text": text})

    @mcp.tool(title="Read a Stored Output", annotations=ToolAnnotations(readOnlyHint=True))
    async def vault_log_read(ref: str, offset: int = 0, limit: int = 0, grep: str = "") -> dict:
        """Read a long output the kernel stored (ref = vault://logs/...), by pages or with grep; offset and limit count
        characters, not lines."""
        return await _exo_call(exo.lens, tool="vault_log_read", args={"ref": ref, "offset": offset, "limit": limit,
                                                                      "grep": grep})

    @mcp.tool(
        title="Check Syntax",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def check_syntax(path: str, root: str | None = None) -> dict:
        """Parse a file after you edit it and list its syntax errors with lines (local and instant)."""
        return exo.check_syntax(path=path, root=root)

    @mcp.tool(
        title="Workspace Overview",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def coding_context(root: str | None = None) -> dict:
        """The workspace's file tree (respecting .gitignore, without dependency and build folders) and its git status."""
        return exo.coding_context(root=root)

    @mcp.tool(
        title="Checkpoint",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    def checkpoint(label: str = "checkpoint", root: str | None = None) -> dict:
        """Snapshot the workspace before a risky edit, in a hidden shadow git: your own .git history is untouched.
        Returns its id and the recent checkpoints."""
        return exo.checkpoint(label=label, root=root)

    @mcp.tool(
        title="Diff Since a Checkpoint",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def checkpoint_diff(
        target: str | int | None = None,
        paths: list[str] | None = None,
        root: str | None = None,
    ) -> dict:
        """Unified diff of the workspace since a checkpoint (default: the latest); paths narrows it to those files or
        folders."""
        return exo.checkpoint_diff(target=target, paths=paths, root=root)

    @mcp.tool(
        title="Roll Back to a Checkpoint",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
    )
    def checkpoint_rollback(target: str | int | None = None, root: str | None = None) -> dict:
        """Restore the workspace to a checkpoint (default: the latest). A safety snapshot is taken first, so the
        rollback itself can be undone."""
        return exo.checkpoint_rollback(target=target, root=root)

    @mcp.tool(
        title="Token Savings",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def token_savings() -> dict:
        """What the code tools saved this session, measured on the real files: every distinct file the answers pointed to,
        read whole once, against what the tools returned; tokens estimated at 4 characters each. Answers with no local
        file behind them are counted apart, never as a saving."""
        return exo.token_savings()

    from .auth import AgentLogin
    agent_login = AgentLogin()
    mcp._agent_login = agent_login      # tests swap the grant

    @mcp.tool(
        title="Sign In",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def login(again: bool = False) -> dict:
        """Sign in to Imperal for memory and frame; the code tools need no account. Returns a link and a short code:
        show both to the user, who approves in any browser, then call login again to see that it is done. again=true
        replaces an expired session."""
        return await agent_login(again=again)

    @mcp.tool(
        title="Recall Memory",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def recall_context(
        query: str,
        limit: int = 5,
        include_user_facts: bool = True,
        include_repo_memory: bool = True,
        include_resolved: bool = False,
    ) -> dict:
        """The user's standing rules, preferences and repository notes that match a query, from Imperal memory shared
        with Webbee, Telegram and the panel."""
        from .exoskeleton import scope_recall
        want = max(1, int(limit or 5))
        got = scope_recall(
            await client.run_tool(
                "memory-index",
                "recall_context",
                {
                    "query": query,
                    # another repo's notes are dropped below: ask for more so `limit` of this repo's remain (live
                    # 2026-11-13: the store cut to `limit` first, the filter then left none)
                    "limit": want * 3,
                    "include_user_facts": include_user_facts,
                    "include_repo_memory": include_repo_memory,
                    "include_resolved": include_resolved,
                },
            ), exo.current_repo_keys())
        data = got.get("data") if isinstance(got, dict) else None
        if isinstance(data, dict) and isinstance(data.get("snippets"), list):
            got = {**got, "data": {**data, "snippets": data["snippets"][:want]}}
        return defensive_scrub(got)

    @mcp.tool(
        title="Remember a Fact",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def remember_fact(
        fact: str,
        category: str = "preference",
        tags: list[str] | None = None,
        scope: str | None = None,
    ) -> dict:
        """Keep a lasting fact, decision or rule about the user in Imperal memory, for every future session and
        surface."""
        if (scope or "").strip().lower() not in ("", "global", "task", "surface"):
            return {"ok": False, "status": "error",
                    "error": f"scope must be one of: global, task, surface (or empty to decide from the fact); got "
                             f"'{scope}'. A fact about one project or repository: save_repo_note(note, root=<it>) keeps "
                             "it with that repository"}
        payload: dict[str, Any] = {
            "fact": fact,
            "category": category,
            "tags": tags or [],
        }
        if scope:
            payload["scope"] = scope.strip().lower()
        return defensive_scrub(await client.run_tool("memory-index", "add_user_fact", payload))

    @mcp.tool(
        title="Save a Repository Note",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def save_repo_note(
        note: str,
        repo: str | None = None,
        citations: list[str] | None = None,
        root: str | None = None,
    ) -> dict:
        """Keep a lasting note about a repository (a convention, an architecture decision), with citations if you have
        them."""
        import os as _os
        repo_name = repo
        if not repo_name:
            # the repository's own key, never its folder name: the store matched a name as a fragment of any path and
            # took the first (live 2026-11-13: a note of imperal-cloud-main landed on webbee's key, recall then dropped
            # it as another repo's)
            exo.loop = asyncio.get_running_loop()
            try:
                repo_name = await asyncio.to_thread(exo._repo_key, root, None)
            except Exception:
                repo_name = ""
            repo_name = repo_name or exo.resolve_workspace(root)
        return defensive_scrub(
            await client.run_tool(
                "memory-index",
                "add_note",
                {
                    "note": note,
                    "repo": repo_name,
                    "citations": citations or [],
                },
            )
        )

    # ── Imperal apps: build, deploy and run (listed after the code and memory tools: what a new agent sees
    #    first is what it came for -- live 2026-11-13 the list opened with eight IR-app tools) ──────────

    @mcp.tool(
        title="Validate an App",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def validate_ir(app_ir: dict) -> dict:
        """Check an Imperal app definition (app.ir.json) locally: its envelope and every declarative step."""
        return _validate_ir(app_ir)

    @mcp.tool(
        title="Smoke-Test an App",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def smoke_ir(app_ir: dict, function: str, args: dict | None = None) -> dict:
        """Run one function of an app.ir.json in an isolated store; returns {ok, result, trace}."""
        return await client.smoke_ir(app_ir, function, args or {})

    @mcp.tool(
        title="Deploy an App",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def deploy_ir(app_ir: dict, app_id: str) -> dict:
        """Deploy an app.ir.json to the user's Imperal account; a new app id creates the app."""
        display = (app_ir.get("app", {}) or {}).get("id", app_id)
        await client.ensure_app(app_id, display)
        return await deploy_ir_logic(client, app_ir, app_id)

    @mcp.tool(
        title="List Apps",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_apps() -> Any:
        """The user's own Imperal apps (personal data masked)."""
        return defensive_scrub(await client.list_apps())

    @mcp.tool(
        title="Get an App",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_app(app_id: str, full: bool = False) -> Any:
        """One app and its callable tools (name, action type, what it does): the names run_read_tool and run_write_tool
        take. full=true gives the raw record with the whole manifest."""
        got = defensive_scrub(await client.get_app(app_id))
        return got if full else app_summary(got)

    @mcp.tool(
        title="Run a Read Tool",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def run_read_tool(app_id: str, function: str = "", args: dict | None = None, tool: str = "") -> Any:
        """Call a read-only tool of a deployed app by the name get_app lists; write and destructive tools are refused
        here."""
        if not (function or tool):
            return {"ok": False, "error": "name the app's tool: function=<a name get_app lists>"}
        return await run_read_tool_logic(client, app_id, function or tool, args or {})

    @mcp.tool(
        title="Run a Write Tool",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def run_write_tool(app_id: str, function: str = "", args: dict | None = None, ctx: Context = None,
                             tool: str = "") -> Any:
        """Call a write or destructive tool of a deployed app by the name get_app lists. Destructive needs the user's
        consent; money tools need approval in the Imperal panel, then call again."""
        if not (function or tool):
            return {"ok": False, "error": "name the app's tool: function=<a name get_app lists>"}
        return await run_write_tool_logic(client, ctx, app_id, function or tool, args or {}, _AUTOPILOT)

    @mcp.tool(
        title="Upload a File",
        annotations=ToolAnnotations(destructiveHint=False),
    )
    async def upload_file(path: str, name: str | None = None) -> Any:
        """Send a file from this machine to Imperal by its path (never paste its bytes) and get {file_id, document_id,
        filename, size_bytes, status}. To attach it to anything, pass {"document_id": <id>} as that tool's file
        argument in run_write_tool."""
        return defensive_scrub(await client.upload_file(path, name=name))

    @mcp.resource("imperal://exoskeleton-protocol")
    def _r_exo_protocol() -> str:
        return EXOSKELETON_INSTRUCTIONS

    @mcp.resource("imperal://ir-spec")
    def _r_spec() -> str:
        return ir_spec_text()

    @mcp.resource("imperal://ui-catalog")
    def _r_ui() -> str:
        return ui_catalog_text()

    @mcp.resource("imperal://examples")
    def _r_ex() -> str:
        return examples_text()

    @mcp.prompt()
    def build_imperal_app() -> str:
        """Guidance for building an Imperal app from intent."""
        return build_prompt_text()

    for name, tool in (getattr(getattr(mcp, "_tool_manager", None), "_tools", None) or {}).items():
        tool.parameters = lean_schema(name, tool.parameters)
        # a docstring's own indentation reached every agent as runs of spaces after each line break
        tool.description = " ".join((tool.description or "").split())
    return mcp


def main() -> None:
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
