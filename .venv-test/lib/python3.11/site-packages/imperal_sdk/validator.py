# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""Extension validator — checks V1-V24 + V31 rules.

Used by ``imperal validate`` CLI and the Dev Portal publish gate.
Returns structured report with errors, warnings, and info.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+")
VALID_ACTION_TYPES = {"read", "write", "destructive"}
_FN_PREFIX = "fn_"


# === PEP 563 / forward-reference helper =================================
# Validator inspects function annotations. Under
# ``from __future__ import annotations`` (the Python 3.10+ default style)
# every annotation is a STRING, not a class. ``typing.get_type_hints``
# resolves those strings via the function's ``__globals__`` back to real
# classes; without it, ``isinstance(ann, type)`` is always False and every
# type-based check misfires (false positive on V6, false negative on V5).

def _resolve_hints(func) -> dict:
    """Return ``typing.get_type_hints(func)`` or ``{}`` on failure.

    Never raises. Failures are silent — callers fall back to raw
    ``__annotations__`` when the hint dict is missing the key they need.
    """
    try:
        import typing
        return typing.get_type_hints(func)
    except Exception:
        # Common failure modes: circular imports, forward refs to private
        # classes, string annotations referencing modules not imported in
        # this context. None of them are validator bugs — we degrade to
        # substring fallback and keep running.
        return {}


def _looks_like_action_result(value) -> bool:
    """True iff ``value`` is the ActionResult class or a subclass of it.

    Accepts class references (after PEP 563 resolution) AND string
    annotations (pre-resolution fallback). Substring match on 'ActionResult'
    is intentionally lenient — subclasses, aliased re-exports, and
    typing.Union / Optional wrappers are all acceptable.
    """
    if value is None:
        return False
    try:
        from imperal_sdk.chat.action_result import ActionResult as _AR
        if isinstance(value, type) and issubclass(value, _AR):
            return True
    except Exception:
        pass
    if "ActionResult" in str(value):
        return True
    return False


def _is_basemodel_subclass(value) -> bool:
    """True iff ``value`` is a Pydantic BaseModel subclass (post-resolution)."""
    if not isinstance(value, type):
        return False
    try:
        from pydantic import BaseModel
        return issubclass(value, BaseModel)
    except (TypeError, ImportError):
        return False


@dataclass
class ValidationIssue:
    """A single validation issue."""
    rule: str       # "V1", "V2", etc.
    level: str      # "ERROR", "WARN", "INFO"
    message: str
    file: str = ""
    line: int = 0
    fix: str = ""

    def get(self, key: str, default=None):
        """Dict-style .get() for compatibility with manifest-rule consumers.

        Aliases:
          ``severity`` → ``level``   (manifest rules use "severity" key)
          ``detail``   → ``message`` (manifest rules use "detail" key)
        All other keys map to the matching attribute name.
        """
        _ALIASES = {"severity": "level", "detail": "message"}
        attr = _ALIASES.get(key, key)
        return getattr(self, attr, default)


@dataclass
class ValidationReport:
    """Result of validating an extension."""
    app_id: str
    version: str
    issues: list[ValidationIssue] = field(default_factory=list)
    function_count: int = 0
    tool_count: int = 0
    event_count: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "WARN"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_extension(ext) -> ValidationReport:
    """Validate an Extension instance against V1-V24 + V31 rules.

    Args:
        ext: An Extension instance (with app_id, version, tools, etc.)

    Returns:
        ValidationReport with all issues found.
    """
    report = ValidationReport(
        app_id=getattr(ext, "app_id", "unknown"),
        version=getattr(ext, "version", "0.0.0"),
    )

    # V1: app_id format — must be [a-z0-9][a-z0-9-]*[a-z0-9], min 2 chars
    app_id = getattr(ext, "app_id", "")
    if not app_id or not APP_ID_PATTERN.match(app_id):
        safe = app_id.lower().replace(" ", "-") if app_id else ""
        fix_msg = f"Change app_id to '{safe}'" if safe else "Set app_id to a valid lowercase identifier"
        report.issues.append(ValidationIssue(
            rule="V1", level="ERROR",
            message=f"app_id '{app_id}' must match [a-z0-9][a-z0-9-]*[a-z0-9] (2+ chars, no uppercase)",
            fix=fix_msg,
        ))

    # V2: version must be semver
    version = getattr(ext, "version", "")
    if not version or not SEMVER_PATTERN.match(version):
        report.issues.append(ValidationIssue(
            rule="V2", level="ERROR",
            message=f"version '{version}' must be valid semver (e.g. '1.0.0')",
            fix="Set version to a valid semver string",
        ))

    # Count registered @ext.tool entries. Exclude synthetic tools that the
    # SDK auto-registers internally (e.g. __panel__secrets from the
    # EXT-SECRETS-V1 unconditional synthetic Secrets panel) — those are
    # platform-provided, not user-authored, and shouldn't count toward V3
    # "at least one tool" or marketplace tool counts.
    _all_tools = getattr(ext, "_tools", {})
    _SYNTHETIC_PREFIXES = ("__panel__", "__widget__", "__tray__", "__webhook__")
    tools = {
        name: t for name, t in _all_tools.items()
        if not any(name.startswith(p) for p in _SYNTHETIC_PREFIXES)
    }
    report.tool_count = len(tools)

    # Collect all ChatExtension instances registered on this extension
    chat_extensions: dict = getattr(ext, "_chat_extensions", {})

    # Aggregate all @chat.function definitions across every ChatExtension
    functions: dict = {}
    for ce in chat_extensions.values():
        funcs = getattr(ce, "_functions", {})
        functions.update(funcs)
    report.function_count = len(functions)

    # V3: must have at least one @ext.tool or ChatExtension
    if not tools and not chat_extensions:
        report.issues.append(ValidationIssue(
            rule="V3", level="ERROR",
            message="Extension must have at least one @ext.tool or ChatExtension",
            fix="Add a @ext.tool or create a ChatExtension",
        ))

    # V4, V5, V6, V10, V11: check each @chat.function
    for fname, fdef in functions.items():
        # V4: explicit action_type
        action_type = getattr(fdef, "action_type", "")
        if action_type not in VALID_ACTION_TYPES:
            report.issues.append(ValidationIssue(
                rule="V4", level="ERROR",
                message=(
                    f"@chat.function '{fname}' must have explicit action_type "
                    f"('read', 'write', or 'destructive'), got '{action_type}'"
                ),
                fix=f"Add action_type='read' (or 'write'/'destructive') to @chat.function('{fname}')",
            ))

        # V5: must return ActionResult — PEP 563 safe.
        func = getattr(fdef, "func", None)
        if func:
            _v5_hints = _resolve_hints(func)
            _v5_ret = _v5_hints.get("return")
            _v5_raw = getattr(func, "__annotations__", {}).get("return", "")
            _v5_ok = _looks_like_action_result(_v5_ret) or (
                _v5_ret is None and "ActionResult" in str(_v5_raw)
            )
            if not _v5_ok:
                report.issues.append(ValidationIssue(
                    rule="V5", level="ERROR",
                    message=f"@chat.function '{fname}' must return ActionResult",
                    fix="Add return type annotation: -> ActionResult",
                ))

        # V6: params should be Pydantic BaseModel (WARN for now, ERROR in v2)
        if func:
            import inspect
            sig = inspect.signature(func)
            params_list = [
                p for p in sig.parameters.values()
                if p.name not in ("ctx", "self")
            ]
            _v6_hints = _resolve_hints(func)
            has_pydantic_param = False
            for p in params_list:
                resolved = _v6_hints.get(p.name, p.annotation)
                if resolved is inspect.Parameter.empty:
                    continue
                if _is_basemodel_subclass(resolved):
                    has_pydantic_param = True
                    break
            if params_list and not has_pydantic_param:
                report.issues.append(ValidationIssue(
                    rule="V6", level="WARN",
                    message=f"@chat.function '{fname}' params should be a Pydantic BaseModel subclass",
                    fix=(
                        f"Create a Pydantic model for params: "
                        f"class {fname.title().replace('_', '')}Params(BaseModel): ..."
                    ),
                ))

        # V10: write/destructive without event=
        event = getattr(fdef, "event", "")
        if action_type in ("write", "destructive") and not event:
            short_name = fname[len(_FN_PREFIX):] if fname.startswith(_FN_PREFIX) else fname
            suggested_event = f"{app_id}.{short_name}"
            report.issues.append(ValidationIssue(
                rule="V10", level="WARN",
                message=f"@chat.function '{fname}' (action_type='{action_type}') has no event=",
                fix=f"Add event='{suggested_event}' to the decorator",
            ))

        # V11: missing docstring
        func = getattr(fdef, "func", None)
        if func and not getattr(func, "__doc__", None):
            report.issues.append(ValidationIssue(
                rule="V11", level="WARN",
                message=f"@chat.function '{fname}' missing docstring",
                fix="Add a docstring to the function",
            ))

    # V7: no direct import anthropic/openai — check each ChatExtension's module source
    for ce in chat_extensions.values():
        tool_func = getattr(ce, "_entry_func", None) or getattr(ce, "_handle", None)
        if tool_func:
            import inspect
            try:
                source = inspect.getsource(inspect.getmodule(tool_func))
                for banned in ("import anthropic", "import openai", "from anthropic", "from openai"):
                    if banned in source:
                        report.issues.append(ValidationIssue(
                            rule="V7", level="ERROR",
                            message=f"Direct '{banned}' found. Use ctx.ai or get_llm_provider() instead",
                            fix="Replace direct LLM imports with ctx.ai.complete() or get_llm_provider()",
                        ))
                        break
            except (TypeError, OSError):
                pass

    # Count events: functions with event= + @ext.on_event handlers
    event_count = sum(1 for f in functions.values() if getattr(f, "event", ""))
    for _eh in getattr(ext, "_event_handlers", []):
        event_count += 1
    report.event_count = event_count

    # V8: imperal.json manifest check — filesystem only, warn in runtime validation
    report.issues.append(ValidationIssue(
        rule="V8", level="WARN",
        message="Cannot verify imperal.json manifest (runtime validation)",
        fix="Run 'imperal validate ./extension' from CLI for full filesystem check",
    ))

    # V9: missing @ext.health_check
    if getattr(ext, "_health_check", None) is None:
        report.issues.append(ValidationIssue(
            rule="V9", level="WARN",
            message="No @ext.health_check registered",
            fix="Add @ext.health_check decorator to a health check function",
        ))

    # V12: no on_install lifecycle hook
    lifecycle = getattr(ext, "_lifecycle", {})
    if "on_install" not in lifecycle:
        report.issues.append(ValidationIssue(
            rule="V12", level="INFO",
            message="No @ext.on_install lifecycle hook",
            fix="Consider adding @ext.on_install for first-time setup",
        ))

    # V13: tool names starting with "refresh_" that are NOT prefixed
    # "skeleton_refresh_" will not be picked up by the platform's auto-derive
    # skeleton_sections convention.
    _tools = getattr(ext, "_tools", {})
    for tool_name in _tools.keys():
        if not isinstance(tool_name, str):
            continue
        if tool_name.startswith("refresh_") and not tool_name.startswith("skeleton_refresh_"):
            suggested = tool_name[len("refresh_"):]
            report.issues.append(ValidationIssue(
                rule="V13", level="WARN",
                message=(
                    f"Tool {tool_name!r} looks like a skeleton refresh but lacks "
                    f"the 'skeleton_refresh_' prefix required by the platform's "
                    f"auto-derive convention"
                ),
                fix=(
                    f"Rename to 'skeleton_refresh_{suggested}' OR use "
                    f"@ext.skeleton({suggested!r}) decorator which applies the "
                    f"convention automatically"
                ),
            ))
        if tool_name.startswith("alert_") and not tool_name.startswith("skeleton_alert_"):
            suggested = tool_name[len("alert_"):]
            report.issues.append(ValidationIssue(
                rule="V13", level="INFO",
                message=(
                    f"Tool {tool_name!r} looks like a skeleton alert but lacks "
                    f"the 'skeleton_alert_' prefix"
                ),
                fix=(
                    f"Rename to 'skeleton_alert_{suggested}' so the platform "
                    f"auto-wires it when refresh section has alert_on_change=True"
                ),
            ))

    # === V14-V22 contract ===============================================
    # Every extension that passes these is guaranteed to work with the
    # platform's typed-dispatch chain pipeline. No silent write failures,
    # no LLM-router guessing, no hallucinated capabilities.

    display_name = getattr(ext, "display_name", "") or ""
    description = getattr(ext, "description", "") or ""
    icon_path = getattr(ext, "icon", "") or ""
    actions_explicit = getattr(ext, "actions_explicit", True)

    def _ext_functions(chat_ext):
        funcs = getattr(chat_ext, "functions", None)
        if funcs is None:
            funcs = getattr(chat_ext, "_functions", {})
        return funcs or {}

    # V14 — extension description ≥40 chars, ≠ app_id
    if not description or len(description.strip()) < 40 or description.strip() == app_id:
        report.issues.append(ValidationIssue(
            rule="V14", level="ERROR",
            message=(
                f"Extension {app_id!r} description must be ≥40 chars and "
                f"≠ app_id (got len={len(description)}, value={description!r:.40})"
            ),
            fix=(
                "Set Extension(description=...) to a sentence describing what "
                "the extension does. Webbee shows this in 'what can you do?' — "
                "without it the user sees a bare slug."
            ),
        ))

    # V15 — extension display_name ≥3 chars, ≠ app_id
    if not display_name or len(display_name.strip()) < 3:
        report.issues.append(ValidationIssue(
            rule="V15", level="ERROR",
            message=(
                f"Extension {app_id!r} display_name must be ≥3 chars "
                f"(got len={len(display_name)}, value={display_name!r})"
            ),
            fix=(
                "Set Extension(display_name='Notes') — human-readable, "
                "NOT the slug."
            ),
        ))
    elif display_name.strip() == app_id:
        report.issues.append(ValidationIssue(
            rule="V15", level="ERROR",
            message=(
                f"Extension display_name {display_name!r} verbatim equals "
                f"app_id {app_id!r} — provide human-readable name "
                f"(e.g. 'Notes' for app_id='notes')"
            ),
            fix="Use 'Notes' instead of 'notes', 'Mail Inbox' instead of 'mail-inbox', etc.",
        ))

    # V16 — every @chat.function description ≥20 chars (skip __* synthetic)
    chat_extensions: dict = getattr(ext, "_chat_extensions", {})
    for chat_tool_name, chat_ext in (chat_extensions or {}).items():
        for fn_name, fn_def in _ext_functions(chat_ext).items():
            if fn_name.startswith("__"):
                continue
            fn_desc = (getattr(fn_def, "description", "") or "").strip()
            if len(fn_desc) < 20:
                report.issues.append(ValidationIssue(
                    rule="V16", level="ERROR",
                    message=(
                        f"@chat.function {fn_name!r} (tool {chat_tool_name}) "
                        f"description must be ≥20 chars (got len={len(fn_desc)})"
                    ),
                    fix=(
                        "Set @chat.function(description='...') to a sentence "
                        "describing inputs, outputs, and when to use it. The "
                        "LLM uses this to choose tools."
                    ),
                ))

    # V17 — every @chat.function has explicit Pydantic params model
    for chat_tool_name, chat_ext in (chat_extensions or {}).items():
        for fn_name, fn_def in _ext_functions(chat_ext).items():
            if fn_name.startswith("__"):
                continue
            if getattr(fn_def, "_pydantic_model", None) is None:
                report.issues.append(ValidationIssue(
                    rule="V17", level="ERROR",
                    message=(
                        f"@chat.function {fn_name!r} must declare a Pydantic "
                        f"BaseModel param (V17 — no **kwargs, no Any)"
                    ),
                    fix=(
                        "Define `class XParams(BaseModel): ...` and use it as "
                        "the typed handler arg: `async def fn(ctx, params: XParams)`. "
                        "SDK auto-derives params schema from the model."
                    ),
                ))

    # V18 — every @chat.function declares a typed return annotation.
    for chat_tool_name, chat_ext in (chat_extensions or {}).items():
        for fn_name, fn_def in _ext_functions(chat_ext).items():
            if fn_name.startswith("__"):
                continue
            hints = _resolve_hints(fn_def.func)
            ret = hints.get("return") if hints else None
            if ret is None:
                ret = (getattr(fn_def.func, "__annotations__", {}) or {}).get("return")
            ok = (
                _looks_like_action_result(ret)
                or _is_basemodel_subclass(ret)
                or getattr(fn_def, "_return_model", None) is not None
            )
            if not ok:
                report.issues.append(ValidationIssue(
                    rule="V18", level="ERROR",
                    message=(
                        f"@chat.function {fn_name!r} must declare a typed return "
                        f"annotation: ``-> ActionResult`` (or subclass / Pydantic model)"
                    ),
                    fix=(
                        "Annotate the handler return as ``-> ActionResult``. "
                        "Platform reads return_schema from manifest for typed dispatch."
                    ),
                ))

    # V19 — actions_explicit + chain_callable on writes/destructive
    if not actions_explicit:
        report.issues.append(ValidationIssue(
            rule="V19", level="ERROR",
            message=(
                f"Extension {app_id!r} must set actions_explicit=True"
            ),
            fix=(
                "Set Extension(actions_explicit=True). Declares that every "
                "write/destructive @chat.function is chain-callable as a typed "
                "structured call — closes the chain-planner BYOLLM-router gap."
            ),
        ))
    else:
        for chat_tool_name, chat_ext in (chat_extensions or {}).items():
            for fn_name, fn_def in _ext_functions(chat_ext).items():
                if fn_name.startswith("__"):
                    continue
                _fn_action = getattr(fn_def, "action_type", "read")
                _fn_chain = getattr(fn_def, "chain_callable", True)
                if _fn_action in ("write", "destructive") and not _fn_chain:
                    report.issues.append(ValidationIssue(
                        rule="V19", level="ERROR",
                        message=(
                            f"@chat.function {fn_name!r} (action_type={_fn_action}) "
                            f"must have chain_callable=True under actions_explicit=True"
                        ),
                        fix=(
                            "Default is True for writes — only set chain_callable=False "
                            "if you genuinely need LLM-router routing (very rare)."
                        ),
                    ))

    # V20 — every write/destructive @chat.function should declare effects
    # (WARN-level). effects is advisory declared-intent metadata retained for
    # ext convention; the kernel does not consume it today.
    for chat_tool_name, chat_ext in (chat_extensions or {}).items():
        for fn_name, fn_def in _ext_functions(chat_ext).items():
            if fn_name.startswith("__"):
                continue
            _fn_action20 = getattr(fn_def, "action_type", "read")
            _fn_effects20 = getattr(fn_def, "effects", []) or []
            if _fn_action20 in ("write", "destructive") and not _fn_effects20:
                report.issues.append(ValidationIssue(
                    rule="V20", level="WARN",
                    message=(
                        f"@chat.function {fn_name!r} ({_fn_action20}) "
                        f"should declare effects=['create:resource'] etc."
                    ),
                    fix=(
                        "Pass effects=['create:note'] or ['delete:folder'] etc. "
                        "Advisory declared-intent metadata (not consumed by the "
                        "kernel today; retained for extension convention)."
                    ),
                ))

    # V21 — required SVG icon.
    if not icon_path:
        report.issues.append(ValidationIssue(
            rule="V21", level="ERROR",
            message=(
                f"Extension {app_id!r} must declare icon='icon.svg' "
                f"(V21 — required SVG marketplace icon)"
            ),
            fix=(
                "Add an icon.svg file to your extension dir + set "
                "Extension(icon='icon.svg'). Must be valid SVG with viewBox, "
                "max 100KB, no embedded base64 raster."
            ),
        ))
    elif not icon_path.lower().endswith(".svg"):
        report.issues.append(ValidationIssue(
            rule="V21", level="ERROR",
            message=f"Extension icon {icon_path!r} must be SVG (.svg extension)",
            fix="V21 — only SVG icons accepted. Convert raster to SVG.",
        ))
    else:
        import os as _os
        import xml.etree.ElementTree as _ET
        candidate = None
        for cand in (icon_path, _os.path.join(_os.getcwd(), icon_path)):
            if _os.path.exists(cand):
                candidate = cand
                break
        if candidate is not None:
            try:
                sz = _os.path.getsize(candidate)
            except OSError:
                sz = 0
            if sz > 100 * 1024:
                report.issues.append(ValidationIssue(
                    rule="V21", level="ERROR",
                    message=f"Icon {icon_path!r} is {sz} bytes — max 100KB",
                    fix="Optimize SVG (remove metadata, simplify paths) or split assets.",
                ))
            try:
                tree = _ET.parse(candidate)
                root = tree.getroot()
                local_tag = root.tag.rsplit("}", 1)[-1]
                if local_tag != "svg":
                    report.issues.append(ValidationIssue(
                        rule="V21", level="ERROR",
                        message=f"Icon {icon_path!r} root element is <{local_tag}>, must be <svg>",
                        fix="V21 — root element must be <svg>.",
                    ))
                if not root.attrib.get("viewBox"):
                    report.issues.append(ValidationIssue(
                        rule="V21", level="ERROR",
                        message=f"Icon {icon_path!r} missing viewBox attribute on <svg>",
                        fix="V21 — viewBox required for multi-size rendering.",
                    ))
                for img in root.iter():
                    img_local = img.tag.rsplit("}", 1)[-1]
                    if img_local != "image":
                        continue
                    href = (
                        img.attrib.get("href")
                        or img.attrib.get("{http://www.w3.org/1999/xlink}href")
                        or ""
                    )
                    if href.startswith("data:image") and "base64" in href:
                        report.issues.append(ValidationIssue(
                            rule="V21", level="ERROR",
                            message=(
                                f"Icon {icon_path!r} contains embedded base64 "
                                f"raster in <image href=...>"
                            ),
                            fix="V21 — pure SVG only, no embedded PNG/JPEG.",
                        ))
                        break
            except _ET.ParseError as exc:
                report.issues.append(ValidationIssue(
                    rule="V21", level="ERROR",
                    message=f"Icon {icon_path!r} is not valid XML: {exc}",
                    fix="V21 — must parse as well-formed SVG XML.",
                ))

    # V22 — lifecycle hook signatures match SDK contract
    _LIFECYCLE_REQUIRED_KW = {
        "on_install": set(),
        "on_uninstall": set(),
        "on_refresh": {"message"},
        "on_upgrade": {"from_version"},
    }
    lifecycle = getattr(ext, "_lifecycle", {}) or {}
    for hook_name, hook_def in lifecycle.items():
        required = _LIFECYCLE_REQUIRED_KW.get(hook_name)
        if required is None:
            continue
        try:
            import inspect as _insp
            sig = _insp.signature(hook_def.func)
            params = set(sig.parameters.keys())
            missing = required - params
            has_var_kw = any(
                p.kind == _insp.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
            if missing and not has_var_kw:
                report.issues.append(ValidationIssue(
                    rule="V22", level="ERROR",
                    message=(
                        f"Lifecycle hook {hook_name!r} missing required kwargs: "
                        f"{sorted(missing)}."
                    ),
                    fix=(
                        f"Add {', '.join(sorted(missing))}=None to the hook signature, "
                        f"or accept **kwargs."
                    ),
                ))
        except (ValueError, TypeError):
            pass

    # V24 — handler bodies must NOT access ``ctx.skeleton.*``. Skeleton is the
    # LLM context cache; handlers use ``ctx.api`` for real backend ops. AST
    # walk catches actual ``ctx.skeleton`` attribute access expressions and
    # ignores incidental matches inside string literals or comments.
    import ast as _ast
    import inspect as _insp

    class _SkeletonAccessVisitor(_ast.NodeVisitor):
        def __init__(self):
            self.hits: list[int] = []

        def visit_Attribute(self, node: _ast.Attribute) -> None:
            if node.attr == "skeleton":
                inner = node.value
                if isinstance(inner, _ast.Name) and inner.id == "ctx":
                    self.hits.append(node.lineno)
            self.generic_visit(node)

    for chat_tool_name, chat_ext in (chat_extensions or {}).items():
        for fn_name, fn_def in _ext_functions(chat_ext).items():
            if fn_name.startswith("__"):
                continue
            try:
                src = _insp.getsource(fn_def.func)
            except (OSError, TypeError):
                continue
            try:
                tree = _ast.parse(_insp.cleandoc(src) if src.lstrip() != src else src)
            except SyntaxError:
                continue
            visitor = _SkeletonAccessVisitor()
            visitor.visit(tree)
            if visitor.hits:
                report.issues.append(ValidationIssue(
                    rule="V24-AST", level="ERROR",
                    message=(
                        f"@chat.function {fn_name!r} accesses ctx.skeleton at "
                        f"line(s) {visitor.hits} — forbidden. Skeleton is the "
                        f"LLM context cache (read by router/narrator), not a "
                        f"data source."
                    ),
                    fix=(
                        "Use ctx.api.<...>() to fetch from the real backend. "
                        "Skeleton is updated AFTER actions via @ext.skeleton "
                        "refresh functions, not read inline by handlers."
                    ),
                ))

    # V31 — ``system=True`` reserved for first-party platform extensions.
    # System apps are auto-installed for every user, never shown in the
    # marketplace, and cannot be uninstalled. Allowing a third-party
    # developer to set this flag would let them slip past discovery and
    # claim platform-level trust they have not been granted. The Dev Portal
    # enforces an author allowlist server-side; this validator catches the
    # mistake locally so the developer sees the error before publish.
    if bool(getattr(ext, "system", False)):
        author = (os.environ.get("IMPERAL_AUTHOR_ID") or "").strip()
        # Allowlist is sourced from env at install time; empty default means
        # the SDK does not ship an embedded list of first-party authors.
        _allowlist_raw = (os.environ.get("IMPERAL_FIRSTPARTY_AUTHOR_IDS") or "").strip()
        _allowlist = {a.strip() for a in _allowlist_raw.split(",") if a.strip()}
        if author and _allowlist and author not in _allowlist:
            report.issues.append(ValidationIssue(
                rule="V31", level="ERROR",
                message=(
                    f"Extension(system=True) is reserved for first-party "
                    f"platform extensions. Author {author!r} is not in the "
                    f"first-party allowlist."
                ),
                fix=(
                    "Drop ``system=True`` from your Extension(...) call. "
                    "Your app will publish through the normal marketplace "
                    "flow and users will install it explicitly."
                ),
            ))

    # === V23 + V24 — Federal Typed Return Contract (v5.0.1) ============
    #
    # V23: every @chat.function(action_type="read", ...) MUST declare
    #      ``data_model`` (or ``-> ActionResult[T]`` / ``-> SomeBaseModel``)
    #      so the platform can validate ``$REF`` paths against schema and
    #      prevent naming drift between input/output field names.
    #
    # V24: write/destructive tools SHOULD declare ``data_model`` — WARN-only;
    #      can be promoted post-soak.
    #
    # Soak severity is env-toggled via IMPERAL_VALIDATOR_V23_SEVERITY
    # (default "error" since 2026-06-17 P5-final; set "warn" to opt out).
    try:
        _chat_exts = getattr(ext, "_chat_extensions", {}) or {}
        for _tool_name, _chat_ext in _chat_exts.items():
            _fns = getattr(_chat_ext, "_functions", {}) or {}
            _v23_v24_check_data_model_presence(report, [ext], _fns)
    except Exception:
        # Defensive: never let the new check block existing V1-V22+V31.
        pass

    return report


def _v23_v24_check_data_model_presence(report, extensions, functions):
    """Apply V23 (read) + V24 (write/destructive) ``data_model`` rules to each
    @chat.function in the given functions dict (name -> FunctionDef)."""
    _v23_severity = os.environ.get("IMPERAL_VALIDATOR_V23_SEVERITY", "error").lower()
    # P5-final (2026-06-17): V23 defaults to ERROR. Only an explicit env "warn"
    # downgrades it; anything else (including unset) resolves to ERROR.
    _v23_level = "WARN" if _v23_severity == "warn" else "ERROR"
    for fn_name, fn_def in (functions or {}).items():
        _action_type = getattr(fn_def, "action_type", "read")
        _return_model = getattr(fn_def, "_return_model", None)
        if _return_model is not None:
            continue
        if _action_type == "read":
            # Declarative-UI builders (@chat.function(ui_builder=True)) return ui.*
            # output, not an SDL entity — exempt from the data_model requirement.
            if getattr(fn_def, "_ui_builder", False):
                continue
            report.issues.append(ValidationIssue(
                rule="V23", level=_v23_level,
                message=(
                    f"@chat.function {fn_name!r} (action_type=read) is "
                    f"missing data_model declaration. Read tools must "
                    f"declare typed return shape so the platform can "
                    f"validate $REF paths and prevent naming drift."
                ),
                fix=(
                    "Add `data_model=YourEntityRecord` kwarg to the "
                    "@chat.function decorator OR change return annotation "
                    "to `-> ActionResult[YourEntityRecord]`. Define "
                    "YourEntityRecord as a Pydantic BaseModel with field "
                    "names mirroring your input *Params model for "
                    "round-trip symmetry."
                ),
            ))
        elif _action_type in ("write", "destructive"):
            report.issues.append(ValidationIssue(
                rule="V24", level="WARN",
                message=(
                    f"@chat.function {fn_name!r} (action_type="
                    f"{_action_type}) lacks data_model declaration. "
                    f"Recommended: typing write/destructive returns so "
                    f"narrator + audit ledger see the resulting entity "
                    f"shape."
                ),
                fix=(
                    "Add `data_model=YourEntityRecord` kwarg or use "
                    "`-> ActionResult[YourEntityRecord]` return annotation."
                ),
            ))


# Re-export for consumers that import from imperal_sdk.validator directly.
# ``validate_manifest_dict`` lives in ``manifest_schema.py`` (avoids circular
# import at module load time — manifest_schema already defers its own
# ``ValidationIssue`` import inside the function body).
from imperal_sdk.manifest_schema import validate_manifest_dict  # noqa: E402,F401
