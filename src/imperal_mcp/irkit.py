from __future__ import annotations

from imperal_sdk.ir.validator import validate_ir_dict
from imperal_sdk.ir.actions import validate_step
import imperal_sdk.ui as _ui


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
        '  "ir_version": "1",\n'
        '  "app": {\n'
        '    "id": "<app_id>", "version": "1.0.0",\n'
        '    "functions": [ {"name": "save_link", "action_type": "write",\n'
        '        "impl": {"kind": "declarative", "steps": [ ... ]}} ]\n'
        "  }\n}\n\n"
        "- Every function declares action_type: read | write | destructive.\n"
        "- Declarative steps use the small action vocabulary (e.g. store.create/store.list).\n"
        "- Validate locally with the validate_ir tool BEFORE deploy.\n"
        "- Render with ui.* components (see the ui-catalog resource)."
    )


def examples_text() -> str:
    return (
        "# Example app.ir.json — link-saver\n\n"
        "```json\n"
        "{\n"
        '  "ir_version": "1",\n'
        '  "app": {"id": "link-saver", "version": "1.0.0", "functions": [\n'
        '    {"name": "save_link", "action_type": "write",\n'
        '     "impl": {"kind": "declarative", "steps": [\n'
        '       {"verb": "store.create", "collection": "links", "data": {"url": "{{args.url}}"}}\n'
        "     ]}},\n"
        '    {"name": "list_links", "action_type": "read",\n'
        '     "impl": {"kind": "declarative", "steps": [\n'
        '       {"verb": "store.list", "collection": "links"}\n'
        "     ]}}\n"
        "  ]}\n}\n"
        "```\n"
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
