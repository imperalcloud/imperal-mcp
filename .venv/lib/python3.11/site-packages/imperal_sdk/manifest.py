# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Auto-generate and validate extension manifests (`imperal.json`)."""
from __future__ import annotations
import json
import os
import inspect
from imperal_sdk.extension import Extension
from imperal_sdk.manifest_schema import (
    MANIFEST_SCHEMA,
    Manifest,
    Schedule,
    Signal,
    Tool,
    ToolParam,
    get_schema,
    validate_manifest_dict,
)

__all__ = [
    "generate_manifest",
    "save_manifest",
    "validate_manifest_dict",
    "get_schema",
    "MANIFEST_SCHEMA",
    "Manifest",
    "Tool",
    "ToolParam",
    "Signal",
    "Schedule",
]


def generate_manifest(ext: Extension) -> dict:
    """Auto-generate federal manifest v3 from Extension object.

    Federal v4.0.0 changes:
      - Top-level ``name`` (display_name), ``description``, ``icon`` emitted.
      - ``actions_explicit`` declares the extension follows the typed-dispatch
        contract — kernel uses ``chain_callable`` per tool.
      - Every ``@chat.function`` is emitted as a typed tool with
        ``action_type``, ``chain_callable``, ``params_schema``,
        ``return_schema``. The kernel chain planner reads these directly and
        issues ``app/func(args)`` calls without delegating to the
        ChatExtension LLM router. ``effects`` and the per-tool
        ``background`` / ``long_running`` hints are also emitted, but are
        advisory metadata — the kernel does not currently consume these
        decorator fields.
      - ``lifecycle_hooks`` records signatures so the kernel can pass kwargs
        the hook actually accepts (closes the ``on_refresh(message=)``
        TypeError class).
    """
    tools: list[dict] = []

    for name, tool_def in ext.tools.items():
        if name.startswith("__"):
            # Synthetic entries (__webhook__*, __panel__*, __widget__*, __tray__*)
            # belong to their own declarative sections — keep them out of the
            # user-facing tools list. The kernel reads them from
            # webhooks / tray / exposed / panel sections directly.
            continue
        sig = inspect.signature(tool_def.func)
        params = {}
        for pname, param in sig.parameters.items():
            if pname == "ctx":
                continue
            ptype = "string"
            if param.annotation != inspect.Parameter.empty:
                ptype = _python_type_to_str(param.annotation)
            params[pname] = {
                "type": ptype,
                "required": param.default == inspect.Parameter.empty,
            }
        tools.append({
            "name": name,
            "description": tool_def.description,
            "scopes": tool_def.scopes,
            "parameters": params,
        })

    # Federal v4.0.0 — emit every @chat.function as a typed tool. This is what
    # closes the chain_planner gap: kernel sees the typed surface and dispatches
    # directly via ``app/func(args)`` instead of delegating to the BYOLLM router.
    for chat_tool_name, chat_ext in (getattr(ext, "_chat_extensions", {}) or {}).items():
        for fn_name, fn_def in chat_ext.functions.items():
            params_schema: dict = {}
            if getattr(fn_def, "_pydantic_model", None) is not None:
                try:
                    params_schema = fn_def._pydantic_model.model_json_schema()
                except Exception:
                    params_schema = {}
            return_schema: dict = {}
            if getattr(fn_def, "_return_model", None) is not None:
                try:
                    return_schema = fn_def._return_model.model_json_schema()
                except Exception:
                    return_schema = {}
            tools.append({
                "name": fn_name,
                "description": fn_def.description,
                "action_type": fn_def.action_type,
                "chain_callable": fn_def.chain_callable,
                "effects": list(fn_def.effects or []),
                "id_projection": fn_def.id_projection or "",
                "params_schema": params_schema,
                "return_schema": return_schema,
                "event": fn_def.event or "",
                "background": bool(getattr(fn_def, "background", False)),
                "long_running": bool(getattr(fn_def, "long_running", False)),
                "scopes": [],
                "owner_chat_tool": chat_tool_name,
            })

    signals = [{"name": name} for name in ext.signals]
    schedules = [
        {"name": name, "cron": sched.cron}
        for name, sched in ext.schedules.items()
    ]

    # Federal v4.1.5 — emit sdk_version so the v1.6.0+ feature gate
    # validator (SDK-VERSION-1) finds it without engineers hand-editing
    # imperal.json after every `imperal build`.
    from imperal_sdk import __version__ as _sdk_version

    manifest = {
        "manifest_schema_version": 3,
        "sdk_version": _sdk_version,
        "app_id": ext.app_id,
        "version": ext.version,
        "name": ext.display_name or ext.app_id,
        "description": ext.description or "",
        "icon": ext.icon or "",
        "actions_explicit": ext.actions_explicit,
        "system": bool(getattr(ext, "system", False)),
        "capabilities": ext.capabilities,
        "tools": tools,
        "signals": signals,
        "schedules": schedules,
        "required_scopes": _collect_scopes(ext),
    }

    if ext.icon:
        # Resolve icon_size_bytes if file resolvable from CWD or extension dir
        for candidate in (ext.icon, os.path.join(os.getcwd(), ext.icon)):
            if os.path.exists(candidate):
                try:
                    manifest["icon_size_bytes"] = os.path.getsize(candidate)
                except OSError:
                    pass
                break

    if ext.webhooks:
        manifest["webhooks"] = [wh.to_manifest() for wh in ext.webhooks.values()]

    if ext.event_handlers or ext.declared_emits:
        manifest["events"] = {
            "subscribes": [eh.to_manifest() for eh in ext.event_handlers],
            "emits":      [e.to_manifest() for e in ext.declared_emits],
        }

    if ext.exposed:
        manifest["exposed"] = [e.to_manifest() for e in ext.exposed.values()]

    if ext.lifecycle or ext._health_check:
        manifest["lifecycle"] = ext._build_lifecycle_section()

    # Federal V22 — record lifecycle hook signatures so kernel knows what
    # kwargs to pass (closes the ``on_refresh(message=)`` TypeError class).
    if ext.lifecycle:
        manifest["lifecycle_hooks"] = {
            hook_name: {"signature": str(inspect.signature(hook.func))}
            for hook_name, hook in ext.lifecycle.items()
        }

    if ext.tray_items:
        manifest["tray"] = [t.to_manifest() for t in ext.tray_items.values()]

    if ext.migrations_dir:
        manifest["migrations_dir"] = ext.migrations_dir

    if ext.config_defaults:
        manifest["config_defaults"] = ext.config_defaults

    # EXT-SECRETS-V1 (v4.2.2) — emit declared secrets[]. Optional field;
    # backwards-compatible (extensions without @ext.secret omit it).
    if getattr(ext, "_secrets", None):
        manifest["secrets"] = [
            s.to_manifest_dict() for s in ext._secrets.values()
        ]

    # Ф2 — emit the ui.* surface into the contract (additive). Always present
    # (possibly empty []) so the key shape is stable. ``tree`` is serialized
    # only for panels declaring a STATIC ui tree via @ext.panel(..., tree=...);
    # runtime-rendered panels emit {} (the kernel's maybe_publish_panels reads
    # the live runtime node, not this metadata).
    panels_block: list[dict] = []
    for panel_id, meta in (ext.panels or {}).items():
        tree = meta.get("tree")
        if tree is not None and hasattr(tree, "to_dict"):
            tree_dict = tree.to_dict()
        elif isinstance(tree, dict):
            tree_dict = tree
        else:
            tree_dict = {}
        panels_block.append({
            "panel_id": panel_id,
            "slot": meta.get("slot", "center"),
            "title": meta.get("title", ""),
            "tree": tree_dict,
        })
    manifest["panels"] = panels_block

    return manifest


def _merge_disk_manifest(manifest: dict, path: str) -> dict:
    """Merge marketplace-only fields from on-disk imperal.json if it exists."""
    disk_path = os.path.join(path, "imperal.json")
    if not os.path.exists(disk_path):
        return manifest
    with open(disk_path) as f:
        disk = json.load(f)
    for field in ("name", "description", "author", "license", "homepage",
                  "icon", "category", "tags", "marketplace", "pricing"):
        if field in disk:
            manifest[field] = disk[field]
    return manifest


def save_manifest(ext: Extension, path: str = "manifest.json") -> str:
    """Generate and save manifest to file.

    If path is a directory, merges marketplace fields from existing imperal.json
    and writes to imperal.json in that directory.
    """
    manifest = generate_manifest(ext)
    if os.path.isdir(path):
        manifest = _merge_disk_manifest(manifest, path)
        path = os.path.join(path, "imperal.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return path


def _python_type_to_str(t) -> str:
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
    return mapping.get(t, "string")


def _collect_scopes(ext: Extension) -> list[str]:
    scopes = set()
    for name, tool_def in ext.tools.items():
        if name.startswith("__"):
            continue
        scopes.update(tool_def.scopes)
    return sorted(scopes)
