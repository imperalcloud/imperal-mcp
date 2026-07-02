from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .client import ImperalClient
from .config import Config
from .gate import is_read_only, is_synthetic, classify_tier
from .irkit import (
    validate_ir as _validate_ir,
    ui_catalog_text,
    ir_spec_text,
    examples_text,
    build_prompt_text,
)
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


def _destructive_prompt(conf: dict) -> str:
    """Typed, human-readable summary of the kernel confirmation card's actions."""
    lines = []
    for a in (conf.get("actions") or []):
        fn = a.get("function_name") or a.get("function") or "?"
        n = a.get("item_count")
        lines.append(f"- {fn}" + (f" ({n} item(s))" if n is not None else ""))
    body = "\n".join(lines) or "(a destructive operation)"
    return ("This is a DESTRUCTIVE operation:\n" + body +
            "\nApprove once, enable autopilot (stop asking this session), or reject?")


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


async def run_write_tool_logic(client, ctx, app_id, function, args, autopilot) -> dict:
    """Run a write/destructive tool via the guarded /operate seam.
    - read  -> refused (use run_read_tool)
    - blocked (synthetic/legacy/unknown) -> refused
    - write -> operate(bypass=False) once, return shaped result
    - destructive -> operate(bypass=False) surfaces the kernel confirmation card;
      consent via ctx.elicit (or session autopilot); on approval operate(bypass=True).
    The kernel owns tier/billing/audit/confirmation (CONTROL != BYPASS) — this only
    drives the local consent UX."""
    action_type = await _resolve_action_type(client, app_id, function)
    tier = classify_tier(function, action_type)
    if tier == "read":
        return {"status": "refused", "reason": "use run_read_tool"}
    if tier == "blocked":
        return {"status": "refused", "reason": "not a runnable write/destructive tool"}
    if tier == "write":
        res = await client.operate(app_id, function, args or {}, confirmation_bypassed=False)
        return _shape(res)
    # tier == "destructive"
    first = await client.operate(app_id, function, args or {}, confirmation_bypassed=False)
    if isinstance(first, dict) and first.get("kind") == "tool_result":
        return _shape(first)  # kernel re-graded as non-destructive / already done
    if not (isinstance(first, dict) and first.get("kind") == "confirmation"):
        return {"status": "error", "detail": "unexpected kernel result for destructive op"}
    consent = "autopilot"
    if not autopilot.enabled:
        result = await ctx.elicit(message=_destructive_prompt(first), schema=_DestructiveConsent)
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


def build_server(client: ImperalClient) -> FastMCP:
    mcp = FastMCP("imperal")

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
        """Run a WRITE or DESTRUCTIVE tool of a deployed app. Write runs directly;
        destructive requires human consent (elicitation) or session autopilot; read
        tools are refused (use run_read_tool). Money tools are not supported here."""
        return await run_write_tool_logic(client, ctx, app_id, function, args or {}, _AUTOPILOT)

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
