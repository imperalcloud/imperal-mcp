# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""generate_ir — map an Extension's manifest onto the IR envelope (impl=code)."""
from __future__ import annotations

from typing import Any

from ..manifest import generate_manifest
from ..sdl._generate_roles_json import _SCHEMA_VERSION as _SDL_VOCAB_VERSION_INT
from .schema import IR_VERSION, CONTRACT_VERSION

_SDL_VOCAB_VERSION = str(_SDL_VOCAB_VERSION_INT)

# Tool name prefixes that belong to ui/skeleton slots — handled in later tasks
# (E2/E5). Exclude them from the IR functions list.
_SKIP_PREFIXES = ("__panel__", "__webhook__", "__widget__", "__tray__", "skeleton_refresh_", "skeleton_alert_")


def generate_ir(ext: Any) -> dict[str, Any]:
    """Map an Extension's manifest onto the IR envelope.

    All handlers are ``impl.kind="code"`` — the pure-declarative impl kind
    (``declarative``) is reserved for future tasks (L0-2 phase B).

    Skips synthetic tool entries:
    - ``__panel__`` / ``__webhook__`` / ``__widget__`` / ``__tray__`` —
      handled by their own manifest sections.
    - ``skeleton_refresh_`` / ``skeleton_alert_`` — handled by the skeleton
      slot (E2/E5).
    """
    m = generate_manifest(ext)
    functions: list[dict[str, Any]] = []

    for tool in m.get("tools", []):
        name: str = tool["name"]
        # Skip any tool whose name starts with a synthetic prefix.
        if any(name.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        functions.append({
            "name": name,
            "description": tool.get("description", ""),
            "params_schema": tool.get("params_schema") or {},
            "return_schema": tool.get("return_schema") or None,
            "action_type": tool.get("action_type") or "read",
            "effects": list(tool.get("effects") or []),
            "event": tool.get("event") or "",
            "impl": {
                "kind": "code",
                "module": "handlers",
                "entry": tool.get("owner_chat_tool") or name,
            },
        })

    panels_ir: list[dict] = []
    for p in m.get("panels", []):
        tree = p.get("tree") or {}
        if tree:
            render: dict = {"kind": "static", "tree": tree}
        else:
            render = {
                "kind": "code",
                "module": "panels",
                "entry": f"__panel__{p['panel_id']}",
            }
        panels_ir.append({
            "panel_id": p["panel_id"],
            "slot": p.get("slot", "center"),
            "title": p.get("title", ""),
            "render": render,
        })

    # Skeleton slot — scan ext._tools for skeleton_refresh_* entries.
    # The _skeleton meta dict (section_name, alert_on_change, ttl) is set by
    # @ext.skeleton(...) on the in-memory ToolDef and does NOT survive into the
    # manifest dict, so we read it from the live ext object here.
    skeleton_ir: list[dict] = []
    live_tools: dict = getattr(ext, "_tools", {})
    for tool_name, tool_def in live_tools.items():
        if not tool_name.startswith("skeleton_refresh_"):
            continue
        section = tool_name[len("skeleton_refresh_"):]
        meta: dict = getattr(tool_def, "_skeleton", None) or {}
        skeleton_ir.append({
            "section": meta.get("section_name") or section,
            "shape": {},
            "producer": {
                "kind": "code",
                "module": "skeleton",
                "entry": tool_name,
            },
            "alert": bool(meta.get("alert_on_change", False)),
            "ttl": int(meta.get("ttl", 300)),
        })

    app: dict = {
        "id": m.get("app_id", ""),
        "version": m.get("version", ""),
        "title": m.get("name", "") or m.get("app_id", ""),
        "description": m.get("description", ""),
        "capabilities": list(m.get("capabilities") or []),
        "functions": functions,
    }
    if panels_ir:
        app["ui"] = {"panels": panels_ir}
    if skeleton_ir:
        app["skeleton"] = skeleton_ir

    return {
        "ir_version": IR_VERSION,
        "sdl_vocab_version": _SDL_VOCAB_VERSION,
        "contract_version": CONTRACT_VERSION,
        "app": app,
    }
