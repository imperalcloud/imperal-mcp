from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import ImperalClient
from .config import Config
from .gate import is_read_only, is_synthetic
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


async def deploy_ir_logic(client: ImperalClient, app_ir: dict, app_id: str) -> dict:
    """Deploy app_ir; retry once after 1 s on a transient first-deploy failure."""
    result = await client.deploy_ir(app_id, app_ir)
    if result.get("status") != "success":
        await asyncio.sleep(1.0)
        result = await client.deploy_ir(app_id, app_ir)
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
