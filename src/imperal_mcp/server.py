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
from .exoskeleton import EXOSKELETON_INSTRUCTIONS, ExoskeletonRuntime
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


async def _resolve_action_type(client: ImperalClient, app_id: str, function: str) -> str | None:
    app = await client.get_app(app_id)
    for t in _tools_of(app):
        if t.get("name") == function:
            return t.get("action_type")
    # Fallback: check the marketplace catalog
    try:
        mkt = await client.get_marketplace_app(app_id)
        for t in (mkt.get("tools") or []):
            if t.get("name") == function:
                return t.get("action_type")
    except Exception:
        pass
    return None


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
    action_type = await _resolve_action_type(client, app_id, function)
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
    action_type = await _resolve_action_type(client, app_id, function)
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
        out = await asyncio.to_thread(fn, **kwargs)
        return _recorded(fn.__name__, out, **kwargs) if fn.__name__ not in ("frame", "task", "lens") else out

    @mcp.tool(
        title="Validate IR",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def validate_ir(app_ir: dict) -> dict:
        """Validate an app.ir.json locally (envelope + every declarative step)."""
        return _validate_ir(app_ir)

    @mcp.tool(
        title="Smoke-test IR",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def smoke_ir(app_ir: dict, function: str, args: dict | None = None) -> dict:
        """Run one function of an app.ir.json in an ISOLATED store and report {ok,result,trace}."""
        return await client.smoke_ir(app_ir, function, args or {})

    @mcp.tool(
        title="Deploy IR",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def deploy_ir(app_ir: dict, app_id: str) -> dict:
        """Deploy an app.ir.json into the caller's account (creates the app record if needed)."""
        display = (app_ir.get("app", {}) or {}).get("id", app_id)
        await client.ensure_app(app_id, display)
        return await deploy_ir_logic(client, app_ir, app_id)

    @mcp.tool(
        title="List Apps",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_apps() -> Any:
        """List the caller's developer apps (PII-masked)."""
        return defensive_scrub(await client.list_apps())

    @mcp.tool(
        title="Get App",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_app(app_id: str) -> Any:
        """Get one app's manifest + tools (with action_type) (PII-masked)."""
        return defensive_scrub(await client.get_app(app_id))

    @mcp.tool(
        title="Run Read Tool",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def run_read_tool(app_id: str, function: str, args: dict | None = None) -> Any:
        """Run a READ-only tool of a deployed app (refuses write/destructive)."""
        return await run_read_tool_logic(client, app_id, function, args or {})

    @mcp.tool(
        title="Run Write Tool",
        annotations=ToolAnnotations(destructiveHint=True),
    )
    async def run_write_tool(app_id: str, function: str, args: dict | None = None, ctx: Context = None) -> Any:
        """Run a WRITE or DESTRUCTIVE tool of a deployed app. Money tools always go
        through out-of-band panel approval (never terminal consent or autopilot):
        re-run this tool after approving in the panel to complete. Write runs
        directly; destructive requires human consent (elicitation) or session
        autopilot; read tools are refused (use run_read_tool)."""
        return await run_write_tool_logic(client, ctx, app_id, function, args or {}, _AUTOPILOT)

    @mcp.tool(
        title="Upload Local File",
        annotations=ToolAnnotations(destructiveHint=False),
    )
    async def upload_file(path: str, name: str | None = None) -> Any:
        """Send a file from THIS machine into Imperal and get its ids back.

        Read the file straight off disk -- never paste its bytes into a tool
        call, that is truncated long before it reaches the gateway.

        Returns {file_id, document_id, filename, size_bytes, status}. To then
        PLACE that file into any extension (a task attachment, an envelope, a
        post), call run_write_tool with the sink's own file argument set to
        {"document_id": <document_id>}: the gateway swaps the reference for the
        real bytes on the way in, so the file never travels through this
        conversation.
        """
        return defensive_scrub(await client.upload_file(path, name=name))

    # ── Exoskeleton: Local Code Intelligence & AST Surgery ──────────────────

    @mcp.tool(
        title="Orient on Task",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def orient(query: str, k: int = 8, root: str | None = None, target: str | None = None) -> dict:
        """One-call orientation for a task: repo profile + top ranked symbols/snippets from the code graph in Imperal's vault. Call FIRST instead of scanning files blind. `target`: local (default), ssh:<connection_id> or host:<alias> with `root` = the repo path there."""
        return await _exo_call(exo.orient, query=query, k=k, root=root, target=target)

    @mcp.tool(
        title="Repository Profile",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def repo_profile(root: str | None = None, target: str | None = None) -> dict:
        """Structured profile of the repository (languages, file count, the most-used definitions) from the code graph."""
        return await _exo_call(exo.repo_profile, root=root, target=target)

    @mcp.tool(
        title="Search Code Graph",
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
        """Search the code graph: exact names, words and meaning (each hit says how sure it is). Prefer over grep/find."""
        return await _exo_call(exo.search_code, query=query, k=k, kind=kind, path_glob=path_glob, root=root, target=target)

    @mcp.tool(
        title="Code File Outline",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def outline(path: str, root: str | None = None, target: str | None = None) -> dict:
        """Tree-sitter structural map of a source file (classes, functions, methods, major blocks with exact line ranges). Call before reading large files."""
        # a worker thread like every code tool: its cloud call must never wait for the loop it would block
        return await _exo_call(exo.outline, path=path, root=root, target=target)

    @mcp.tool(
        title="Read Symbol or Span",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def read_symbol(path: str, name: str, root: str | None = None, target: str | None = None) -> dict:
        """Read ONE symbol (function, class, Class.method, block name) or line range ('L120-180') from a file without loading the whole file."""
        return await _exo_call(exo.read_symbol, path=path, name=name, root=root, target=target)

    @mcp.tool(
        title="Call Graph Slice",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def graph_slice(symbols: list[str], depth: int = 1, root: str | None = None, target: str | None = None) -> dict:
        """Return definition locations, signatures, direct callers, and callees for a batch of symbols from the code graph."""
        return await _exo_call(exo.graph_slice, symbols=symbols, depth=depth, root=root, target=target)

    @mcp.tool(
        title="Contract Slice",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def contract_slice(symbols: list[str], root: str | None = None, target: str | None = None) -> dict:
        """Return the endpoints and route links across the user's repos, plus the given symbols with their callers."""
        return await _exo_call(exo.contract_slice, symbols=symbols, root=root, target=target)

    @mcp.tool(
        title="Impact of Change",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def impact_of_change(symbols: list[str], root: str | None = None, target: str | None = None) -> dict:
        """Given symbols you plan to modify, return the files and call sites that depend on them (code first, tests after, uses inside the same file listed apart)."""
        return await _exo_call(exo.impact_of_change, symbols=symbols, root=root, target=target)

    @mcp.tool(
        title="Task and Plan",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def task(goal: str, items: list[dict] | None = None, root: str | None = None) -> dict:
        """Declare what you were asked and your plan (items: {content, status: pending|in_progress|completed}) -- the
        kernel's frame holds you to it: an item is proven only by what the kernel measured."""
        return await _exo_call(exo.task, goal=goal, items=items or [], root=root)

    @mcp.tool(
        title="Frame",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
    )
    async def frame(root: str | None = None, target: str | None = None) -> dict:
        """The kernel's step frame for your work (the same frame a Webbee step gets): your task and plan with what is
        proven, the code around your focus from the exact graph, what your change reaches, the world, your path.
        Call it at the start and after each change."""
        return await _exo_call(exo.frame, root=root, target=target)

    @mcp.tool(title="Grep Code", annotations=ToolAnnotations(readOnlyHint=True))
    async def grep_code(pattern: str, root: str | None = None, target: str | None = None, path_glob: str | None = None,
                        k: int = 50, regex: bool = False) -> dict:
        """An exact text (or regex) inside the code -- a string in a function body the symbol search does not index.
        `target`: local (default), ssh:<connection_id> or host:<alias> with `root` = the repo path there."""
        return await _exo_call(exo.grep_code, pattern=pattern, root=root, target=target, path_glob=path_glob, k=k,
                               regex=regex)

    @mcp.tool(title="State Lens", annotations=ToolAnnotations(readOnlyHint=True))
    async def state_lens(section: str = "all", focus: str = "", offset: int = 0) -> dict:
        """What the kernel holds for your session, by section (law, plan, reality, memory, conversation, path) -- where
        the frame's counted lines point."""
        return await _exo_call(exo.lens, tool="state_lens", args={"section": section, "focus": focus, "offset": offset})

    @mcp.tool(title="Recall", annotations=ToolAnnotations(readOnlyHint=True))
    async def recall(ref: str, offset: int = 0, n: int = 1) -> dict:
        """A past request or answer of your session whole (ref = A<seq> / U<seq> / last_answers / all)."""
        return await _exo_call(exo.lens, tool="recall", args={"ref": ref, "offset": offset, "n": n})

    @mcp.tool(title="Vault Log Read", annotations=ToolAnnotations(readOnlyHint=True))
    async def vault_log_read(ref: str, offset: int = 0, limit: int = 0, grep: str = "") -> dict:
        """An output the kernel kept in the vault (ref = vault://logs/...), paged or grepped."""
        return await _exo_call(exo.lens, tool="vault_log_read", args={"ref": ref, "offset": offset, "limit": limit,
                                                                      "grep": grep})

    @mcp.tool(
        title="Check Syntax (Tree-sitter)",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def check_syntax(path: str, root: str | None = None) -> dict:
        """Fast local tree-sitter syntax validation of a source file after editing."""
        return exo.check_syntax(path=path, root=root)

    @mcp.tool(
        title="Workspace Coding Context",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def coding_context(root: str | None = None) -> dict:
        """Project file tree and git status snapshot (respecting .gitignore and pruning heavy build/vendor directories)."""
        return exo.coding_context(root=root)

    @mcp.tool(
        title="ShadowGit Checkpoint",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    def checkpoint(label: str = "checkpoint", root: str | None = None) -> dict:
        """Capture an instant, invisible ShadowGit snapshot of the workspace without touching the user's real .git history."""
        return exo.checkpoint(label=label, root=root)

    @mcp.tool(
        title="ShadowGit Checkpoint Diff",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def checkpoint_diff(
        target: str | int | None = None,
        paths: list[str] | None = None,
        root: str | None = None,
    ) -> dict:
        """Show a unified diff between the current workspace state and a ShadowGit checkpoint."""
        return exo.checkpoint_diff(target=target, paths=paths, root=root)

    @mcp.tool(
        title="ShadowGit Checkpoint Rollback",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
    )
    def checkpoint_rollback(target: str | int | None = None, root: str | None = None) -> dict:
        """Restore the workspace to a previous ShadowGit checkpoint (an auto-safety snapshot is taken first)."""
        return exo.checkpoint_rollback(target=target, root=root)

    @mcp.tool(
        title="Context Compression Telemetry",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def token_savings() -> dict:
        """Return measured characters and lines returned vs. full-file baseline in this session."""
        return exo.token_savings()

    @mcp.tool(
        title="Recall Cross-Surface Cloud Memory",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def recall_context(
        query: str,
        limit: int = 5,
        include_user_facts: bool = True,
        include_repo_memory: bool = True,
        include_resolved: bool = False,
    ) -> dict:
        """Retrieve relevant user directives, preferences, and repository notes from Imperal Cloud Memory across Webbee, Telegram, and the Panel."""
        from .exoskeleton import scope_recall
        return defensive_scrub(scope_recall(
            await client.run_tool(
                "memory-index",
                "recall_context",
                {
                    "query": query,
                    "limit": limit,
                    "include_user_facts": include_user_facts,
                    "include_repo_memory": include_repo_memory,
                    "include_resolved": include_resolved,
                },
            ), exo.current_repo_keys()))

    @mcp.tool(
        title="Remember Durable User Fact / Directive",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def remember_fact(
        fact: str,
        category: str = "preference",
        tags: list[str] | None = None,
        scope: str | None = None,
    ) -> dict:
        """Persist a durable user fact, architectural decision, or standing directive to Imperal Cloud Memory (shared across all surfaces)."""
        payload: dict[str, Any] = {
            "fact": fact,
            "category": category,
            "tags": tags or [],
        }
        if scope:
            payload["scope"] = scope
        return defensive_scrub(await client.run_tool("memory-index", "add_user_fact", payload))

    @mcp.tool(
        title="Save Durable Repository Note",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def save_repo_note(
        note: str,
        repo: str | None = None,
        citations: list[str] | None = None,
        root: str | None = None,
    ) -> dict:
        """Save a durable repository convention or architectural note to Imperal Cloud Memory."""
        import os as _os
        repo_name = repo or _os.path.basename(exo.resolve_workspace(root))
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

    return mcp


def main() -> None:
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
