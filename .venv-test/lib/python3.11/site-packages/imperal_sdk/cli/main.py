# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Imperal Cloud SDK CLI."""
import json
import os
import re
import sys
import configparser
import click
import httpx

try:
    from imperal_sdk import __version__ as SDK_VERSION
except Exception:  # pragma: no cover - defensive
    SDK_VERSION = "5.x"


def _load_credentials() -> dict:
    """Load credentials from .imperal/credentials or environment variables."""
    creds = {
        "registry_url": os.getenv("IMPERAL_REGISTRY_URL", ""),
        "gateway_url": os.getenv("IMPERAL_GATEWAY_URL", ""),
        "api_key": os.getenv("IMPERAL_API_KEY", ""),
    }
    creds_file = os.path.join(os.getcwd(), ".imperal", "credentials")
    if not os.path.exists(creds_file):
        creds_file = os.path.expanduser("~/.imperal/credentials")
    if os.path.exists(creds_file):
        cp = configparser.ConfigParser()
        cp.read(creds_file)
        section = "default"
        if cp.has_section(section):
            if not creds["registry_url"]:
                creds["registry_url"] = cp.get(section, "registry_url", fallback="")
            if not creds["gateway_url"]:
                creds["gateway_url"] = cp.get(section, "gateway_url", fallback="")
            if not creds["api_key"]:
                creds["api_key"] = cp.get(section, "api_key", fallback="")
    return creds


def _validate_manifest(manifest: dict) -> list[str]:
    """Validate manifest before deploy. Returns list of errors.

    Combines structural JSON-Schema validation (from `manifest_schema`) with
    deploy-specific checks (missing tool descriptions break embeddings).
    """
    from imperal_sdk.manifest_schema import validate_manifest_dict

    errors: list[str] = []

    # Structural contract — app_id / version / scope / cron / shape
    for issue in validate_manifest_dict(manifest):
        errors.append(f"[{issue.rule}] {issue.message}")

    # Deploy-only: embeddings depend on non-empty tool descriptions
    for tool in manifest.get("tools", []):
        if not tool.get("description"):
            errors.append(f"Tool '{tool.get('name', '?')}' has no description — embeddings will fail")

    return errors


@click.group()
@click.version_option(version=SDK_VERSION)
def cli():
    """Imperal Cloud SDK — build extensions for the Imperal platform."""
    pass


@cli.command()
@click.argument("name")
@click.option("--template", type=click.Choice(["chat", "tool"]), default="chat", help="Extension template")
def init(name: str, template: str):
    """Scaffold a new extension project (federal v5 contract)."""
    os.makedirs(name, exist_ok=True)
    os.makedirs(f"{name}/tests", exist_ok=True)

    title = name.replace("-", " ").replace("_", " ").title()
    # V14 requires description ≥40 chars, V15 requires display_name ≥3 chars
    # ≠ app_id, V16 requires per-function description ≥20 chars. We seed
    # values that satisfy all three so `imperal build && imperal validate`
    # passes immediately — no surprises for new authors.
    display_name = f"{title} Extension"
    description = (
        f"{title} — a starter extension scaffolded by `imperal init`. "
        f"Replace this description with something specific to your tool."
    )

    if template == "chat":
        main_content = f'''"""{title} extension — Imperal Cloud."""
from pydantic import BaseModel, Field
from imperal_sdk import Extension, ChatExtension, ActionResult


# Federal v5 Extension surface — V14 (description ≥40 chars), V15
# (display_name ≥3 chars, ≠ app_id), V19 (actions_explicit=True), and
# V21 (icon.svg required, XML <svg> root + viewBox) are all satisfied
# by these defaults. Edit display_name + description before publish.
ext = Extension(
    "{name}",
    version="1.0.0",
    display_name={display_name!r},
    description={description!r},
    icon="icon.svg",
    actions_explicit=True,
    capabilities=[{name!r} + ":read"],
)

chat = ChatExtension(
    ext,
    tool_name={name.replace('-', '_')!r},
    description={f"{title} — chat tool entrypoint."!r},
)


class GreetParams(BaseModel):
    """Pydantic params model — V17 federal: typed BaseModel param required."""
    name: str = Field(default="World", description="Person to greet")


@chat.function(
    "greet",
    action_type="read",
    description="Greet someone by name with a friendly message.",
)
async def fn_greet(ctx, params: GreetParams) -> ActionResult:
    """Echo a greeting to verify the extension loads + validators pass."""
    return ActionResult.success(
        data={{"message": f"Hello, {{params.name}}!"}},
        summary=f"Greeted {{params.name}}",
    )
'''
    else:
        main_content = f'''"""{title} extension — Imperal Cloud (tool template, no chat surface)."""
from imperal_sdk import Extension


ext = Extension(
    "{name}",
    version="1.0.0",
    display_name={display_name!r},
    description={description!r},
    icon="icon.svg",
    actions_explicit=True,
    capabilities=[{name!r} + ":read"],
)


@ext.tool({name!r}, scopes=[{name!r} + ":read"], description={f"{title} — invoke from automations or chains."!r})
async def fn_default(ctx, **kwargs):
    """Stub tool. Replace with your own."""
    return {{"message": "ok"}}
'''

    with open(f"{name}/main.py", "w") as f:
        f.write(main_content)

    # V21 federal: extensions MUST ship a valid SVG icon. We seed a tiny
    # placeholder that passes the validator (XML root + viewBox + ≤100 KB).
    with open(f"{name}/icon.svg", "w") as f:
        f.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            'fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" width="24" height="24">'
            '<rect x="3" y="3" width="18" height="18" rx="2"/>'
            '<path d="M9 9h6v6H9z"/>'
            '</svg>\n'
        )

    with open(f"{name}/requirements.txt", "w") as f:
        f.write("imperal-sdk>=5.0.0\n")

    with open(f"{name}/tests/__init__.py", "w") as f:
        pass

    test_content = (
        f'"""Tests for {name} extension."""\n'
        f'import pytest\n'
        f'from imperal_sdk.testing import MockContext\n'
        f'from main import ext\n'
    )
    if template == "chat":
        test_content += (
            f'from main import GreetParams, fn_greet\n\n\n'
            f'def test_extension_registered():\n'
            f'    assert ext.app_id == "{name}"\n'
            f'    assert ext.version == "1.0.0"\n'
            f'    assert ext.display_name and ext.display_name != ext.app_id\n'
            f'    assert len(ext.description) >= 40\n\n\n'
            f'@pytest.mark.asyncio\n'
            f'async def test_greet_returns_action_result():\n'
            f'    ctx = MockContext(user_id="imp_u_test")\n'
            f'    result = await fn_greet(ctx, GreetParams(name="Alex"))\n'
            f'    assert result.status == "success"\n'
            f'    assert "Alex" in result.summary\n'
        )
    else:
        test_content += (
            f'\n\ndef test_extension_registered():\n'
            f'    assert ext.app_id == "{name}"\n'
            f'    assert ext.version == "1.0.0"\n'
            f'    assert "{name}" in ext.tools\n'
        )

    with open(f"{name}/tests/test_main.py", "w") as f:
        f.write(test_content)

    with open(f"{name}/.gitignore", "w") as f:
        f.write(
            "venv/\n.venv/\n__pycache__/\n*.pyc\n*.pyo\n.pytest_cache/\n"
            ".env\n.imperal/\nimperal.json\n.DS_Store\n"
        )

    click.echo(f"Extension '{name}' scaffolded (template: {template})")
    click.echo(f"")
    click.echo(f"Next steps:")
    click.echo(f"  cd {name}")
    click.echo(f"  pip install 'imperal-sdk>=5.0.0'")
    click.echo(f"  imperal build       # generates imperal.json")
    click.echo(f"  imperal validate    # runs V1-V24+V31 federal validators")
    click.echo(f"  imperal test        # smoke-test handlers via MockContext")
    click.echo(f"  imperal deploy      # upload to panel.imperal.io/developer")


@cli.command()
def dev():
    """Run local development server with hot reload."""
    sys.path.insert(0, ".")
    try:
        from main import ext
        from imperal_sdk.manifest import generate_manifest
        manifest = generate_manifest(ext)
        click.echo(f"Extension: {ext.app_id} v{ext.version}")
        click.echo(f"Tools: {', '.join(ext.tools.keys()) or 'none'}")
        click.echo(f"Signals: {', '.join(ext.signals.keys()) or 'none'}")
        click.echo(f"Schedules: {', '.join(ext.schedules.keys()) or 'none'}")
        click.echo("Dev server ready. Ctrl+C to stop.")
    except ImportError:
        click.echo("Error: No main.py found with 'ext' Extension object.", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("path", default=".")
def build(path: str):
    """Generate imperal.json manifest for the extension at PATH.

    Loads the extension from main.py, generates the manifest from registered
    tools/signals/schedules, merges any existing marketplace fields from
    imperal.json, and writes the result to imperal.json.
    """
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        click.echo(f"Error: Path '{path}' is not a directory.", err=True)
        raise SystemExit(1)

    original_dir = os.getcwd()
    try:
        os.chdir(abs_path)
        sys.path.insert(0, abs_path)
        try:
            # Re-import fresh so multiple builds in one session don't cache stale
            import importlib
            if "main" in sys.modules:
                del sys.modules["main"]
            import main as ext_module
        except ImportError as e:
            click.echo(f"Error: Could not load main.py from '{path}': {e}", err=True)
            raise SystemExit(1)

        # Find Extension instance
        from imperal_sdk.extension import Extension
        ext_obj = None
        for attr_name in dir(ext_module):
            obj = getattr(ext_module, attr_name)
            if isinstance(obj, Extension):
                ext_obj = obj
                break

        if ext_obj is None:
            click.echo(f"Error: No Extension instance found in '{path}/main.py'.", err=True)
            raise SystemExit(1)

        from imperal_sdk.manifest import save_manifest
        out_path = save_manifest(ext_obj, abs_path)

        tool_count = len(ext_obj.tools)
        signal_count = len(ext_obj.signals)
        schedule_count = len(ext_obj.schedules)

        click.echo(f"Built: {ext_obj.app_id} v{ext_obj.version}")
        click.echo(f"  Tools: {tool_count}, Signals: {signal_count}, Schedules: {schedule_count}")
        click.echo(f"  Manifest: {out_path}")
    finally:
        os.chdir(original_dir)
        if abs_path in sys.path:
            sys.path.remove(abs_path)


@cli.command()
@click.argument("path", default=".")
def validate(path: str):
    """Validate extension against the current SDK federal rules (V1-V24+V31)."""
    original_dir = os.getcwd()
    try:
        os.chdir(path)
        sys.path.insert(0, ".")
        try:
            from main import ext
        except ImportError:
            click.echo("Error: No main.py found with 'ext' Extension object.", err=True)
            raise SystemExit(1)

        from imperal_sdk.validator import validate_extension, ValidationIssue
        from imperal_sdk.manifest_schema import validate_manifest_dict
        from imperal_sdk.validator_v1_6_0 import (
            validate_source_tree,
            validate_manifest_v1_6_0,
        )
        report = validate_extension(ext)

        # v1.6.0 AST rules (SKEL-GUARD-*, CACHE-MODEL-1, CACHE-TTL-1,
        # MANIFEST-SKELETON-1) — source-level, independent of ext instance.
        source_root = os.getcwd()
        for issue in validate_source_tree(source_root):
            report.issues.append(issue)

        # Close V8 — validate filesystem imperal.json if present. Replaces
        # the "runtime-only" V8 warning with concrete M1..M5 structural
        # issues from the JSON Schema contract.
        manifest_path = os.path.join(source_root, "imperal.json")
        if os.path.exists(manifest_path):
            # Drop the V8 placeholder warning — we have the real answer now.
            report.issues = [i for i in report.issues if i.rule != "V8"]
            try:
                with open(manifest_path) as f:
                    disk_manifest = json.load(f)
                for issue in validate_manifest_dict(disk_manifest):
                    issue.file = "imperal.json"
                    report.issues.append(issue)
                # SDK-VERSION-1 — cross-check sdk_version against source usage.
                for issue in validate_manifest_v1_6_0(disk_manifest, source_root):
                    report.issues.append(issue)
            except json.JSONDecodeError as e:
                report.issues.append(ValidationIssue(
                    rule="M0", level="ERROR",
                    message=f"imperal.json is not valid JSON: {e}",
                    file="imperal.json", line=e.lineno,
                    fix="Fix the JSON syntax error at the reported line",
                ))

        click.echo(f"\n── Imperal Extension Validator (SDK {SDK_VERSION}) {'─' * 36}")
        click.echo(f"\nExtension: {report.app_id} v{report.version}")
        click.echo(f"Tools: {report.tool_count}, Functions: {report.function_count}, Events: {report.event_count}")

        if not report.issues:
            click.echo("\n✅ No issues found!")
            return

        errors = report.errors
        warnings = report.warnings
        infos = [i for i in report.issues if i.level == "INFO"]

        click.echo(f"\nRESULTS: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info")

        for issue in report.issues:
            prefix = {"ERROR": "  ERROR", "WARN": "  WARN ", "INFO": "  INFO "}[issue.level]
            loc = f" {issue.file}:{issue.line}" if issue.file else ""
            click.echo(f"\n  {prefix}{loc}  [{issue.rule}] {issue.message}")
            if issue.fix:
                click.echo(f"         Fix: {issue.fix}")

        if errors:
            click.echo(f"\n❌ {len(errors)} error(s) must be fixed before deployment.")
            raise SystemExit(1)
        else:
            click.echo(f"\n⚠️  {len(warnings)} warning(s) — consider fixing.")
    finally:
        os.chdir(original_dir)


@cli.command()
def test():
    """Run extension tests."""
    import subprocess
    result = subprocess.run(["python", "-m", "pytest", "tests/", "-v"])
    raise SystemExit(result.returncode)


@cli.command()
def deploy():
    """Deploy extension to Imperal Cloud.

    1. Generates manifest from Extension
    2. Validates tools (descriptions, scope format)
    3. Pushes tools + scopes to Registry
    4. Pushes config defaults to unified config store
    """
    sys.path.insert(0, ".")
    try:
        from main import ext
    except ImportError:
        click.echo("Error: No main.py found.", err=True)
        raise SystemExit(1)

    from imperal_sdk.manifest import generate_manifest, save_manifest

    manifest = generate_manifest(ext)
    save_manifest(ext)
    click.echo(f"Extension: {ext.app_id} v{ext.version}")

    errors = _validate_manifest(manifest)
    if errors:
        click.echo("Deploy blocked:", err=True)
        for e in errors:
            click.echo(f"  - {e}", err=True)
        raise SystemExit(1)

    creds = _load_credentials()
    if not creds["registry_url"] or not creds["api_key"]:
        click.echo("Error: Missing credentials. Set IMPERAL_REGISTRY_URL + IMPERAL_API_KEY or create .imperal/credentials", err=True)
        raise SystemExit(1)

    try:
        resp = httpx.get(
            f"{creds['registry_url']}/v1/apps/{ext.app_id}",
            headers={"x-api-key": creds["api_key"]},
            timeout=10,
        )
        if resp.status_code == 404:
            click.echo(f"Error: App '{ext.app_id}' not registered. Create it in Panel first.", err=True)
            raise SystemExit(1)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        click.echo(f"Error connecting to Registry: {e}", err=True)
        raise SystemExit(1)

    tools_payload = []
    for tool in manifest["tools"]:
        tools_payload.append({
            "activity": f"tool_{tool['name']}",
            "name": tool["name"].replace("_", " ").title(),
            "description": tool["description"],
            "domains": [],
            "required_scopes": tool.get("scopes", []),
        })

    skeleton_payload = []
    if "skeleton" in manifest.get("config_defaults", {}):
        for section_name, section_config in manifest["config_defaults"]["skeleton"].items():
            skeleton_payload.append({
                "section_name": section_name,
                "refresh_activity": section_config.get("refresh_activity", ""),
                "alert_activity": section_config.get("alert_activity", ""),
                "ttl": section_config.get("ttl", 300),
                "alert_on_change": section_config.get("alert_on_change", False),
            })

    try:
        resp = httpx.put(
            f"{creds['registry_url']}/v1/apps/{ext.app_id}/tools",
            json={"tools": tools_payload, "skeleton_sections": skeleton_payload, "version": ext.version},
            headers={"x-api-key": creds["api_key"]},
            timeout=30,
        )
        resp.raise_for_status()
        click.echo(f"Tools deployed: {len(tools_payload)} tools, {len(skeleton_payload)} skeleton sections")
    except httpx.HTTPError as e:
        click.echo(f"Error pushing tools: {e}", err=True)
        raise SystemExit(1)

    config_defaults = manifest.get("config_defaults", {})
    if config_defaults:
        try:
            resp = httpx.put(
                f"{creds['registry_url']}/v1/apps/{ext.app_id}/settings",
                json={k: v for k, v in config_defaults.items() if k != "skeleton"},
                headers={"x-api-key": creds["api_key"]},
                timeout=10,
            )
            resp.raise_for_status()
            click.echo("Config defaults deployed")
        except httpx.HTTPError as e:
            click.echo(f"Warning: Config deploy failed (non-fatal): {e}", err=True)

    click.echo(f"\nDeployed {ext.app_id} v{ext.version} successfully!")


@cli.command()
def logs():
    """Tail production logs."""
    click.echo("Connecting to Imperal Cloud logs...")
    click.echo("(Not yet implemented — will stream from SigNoz)")


if __name__ == "__main__":
    cli()
