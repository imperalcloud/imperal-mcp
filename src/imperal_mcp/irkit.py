from __future__ import annotations

import json

from imperal_sdk.ir.validator import validate_ir_dict
from imperal_sdk.ir.actions import validate_step
import imperal_sdk.ui as _ui

# Canonical link-saver example — schema-valid (passes validate_ir).
# Uses real declarative step shape: op + args{kind, data}.
LINK_SAVER_EXAMPLE: dict = {
    "ir_version": "1.0",
    "app": {
        "id": "link-saver",
        "version": "1.0.0",
        "title": "Link Saver",
        "capabilities": ["store"],
        "functions": [
            {
                "name": "save_link",
                "action_type": "write",
                "params_schema": {"url": {"type": "string"}},
                "return_schema": {"type": "object"},
                "impl": {
                    "kind": "declarative",
                    "steps": [
                        {
                            "id": "s1",
                            "op": "store.create",
                            "args": {"kind": "link", "data": {"url": "{{args.url}}"}},
                        }
                    ],
                },
            },
            {
                "name": "list_links",
                "action_type": "read",
                "params_schema": {},
                "return_schema": {"type": "array"},
                "impl": {
                    "kind": "declarative",
                    "steps": [
                        {
                            "id": "s1",
                            "op": "store.list",
                            "args": {"kind": "link"},
                        }
                    ],
                },
            },
        ],
    },
}


def _issue(rule: str, level: str, message: str) -> dict:
    return {"rule": rule, "level": level, "message": message}


def validate_ir(app_ir: dict) -> dict:
    """Full local validation: envelope structure (validate_ir_dict) + every
    declarative step (validate_step). No network. valid == no ERROR issues."""
    issues: list[dict] = [
        _issue(i.rule, i.level, i.message) for i in validate_ir_dict(app_ir)
    ]
    # Per-step validation for declarative function impls.
    for fn in (app_ir.get("app", {}) or {}).get("functions", []) or []:
        impl = fn.get("impl") or {}
        for idx, step in enumerate(impl.get("steps", []) or []):
            for msg in validate_step(step):
                issues.append(
                    _issue("STEP", "ERROR", f"{fn.get('name', '?')}[{idx}]: {msg}")
                )
    valid = not any(i["level"] == "ERROR" for i in issues)
    return {"valid": valid, "issues": issues}


def ui_catalog_text() -> str:
    names = sorted(getattr(_ui, "__all__", []))
    lines = ["# Imperal ui.* component catalog", ""]
    lines += [f"- ui.{n}" for n in names]
    lines.append("")
    lines.append("Each component is a UINode {type, props}; compose them in panels/render.")
    return "\n".join(lines)


def ir_spec_text() -> str:
    return (
        "# Imperal IR envelope (app.ir.json)\n\n"
        "An IR app is a declarative envelope:\n"
        "{\n"
        '  "ir_version": "1.0",\n'
        '  "app": {\n'
        '    "id": "<app_id>", "version": "1.0.0", "title": "<display name>",\n'
        '    "capabilities": ["store"],\n'
        '    "functions": [\n'
        '      {"name": "save_link", "action_type": "write",\n'
        '       "params_schema": {"url": {"type": "string"}},\n'
        '       "return_schema": {"type": "object"},\n'
        '       "impl": {"kind": "declarative", "steps": [\n'
        '         {"id": "s1", "op": "store.create",\n'
        '          "args": {"kind": "link", "data": {"url": "{{args.url}}"}}}\n'
        "       ]}}\n"
        "    ]\n"
        "  }\n}\n\n"
        "Declarative step vocabulary:\n"
        "- op: store.create / store.list / store.get / store.update / store.delete\n"
        "- args: {kind, data} for create/update; {kind} for list/get/delete\n"
        "- Use {{args.<param>}} template syntax to reference function parameters.\n\n"
        "- Every function declares action_type: read | write | destructive.\n"
        "- Validate locally with the validate_ir tool BEFORE deploy.\n"
        "- Render with ui.* components (see the ui-catalog resource)."
    )


def examples_text() -> str:
    return (
        "# Example app.ir.json — link-saver\n\n"
        "```json\n"
        + json.dumps(LINK_SAVER_EXAMPLE, indent=2)
        + "\n```\n"
    )


def build_prompt_text() -> str:
    return (
        "You are building an Imperal app as a declarative app.ir.json. Steps:\n"
        "1. Read the imperal://ir-spec and imperal://ui-catalog resources.\n"
        "2. Author the app.ir.json envelope. Declare each function's action_type.\n"
        "3. Call validate_ir(app_ir) and fix every ERROR issue.\n"
        "4. Call smoke_ir(app_ir, function, args) to run it in isolation and confirm it works.\n"
        "5. Call deploy_ir(app_ir, app_id) to deploy. The app is then live and routable.\n"
        "Keep functions small; never invent verbs outside the action vocabulary."
    )
