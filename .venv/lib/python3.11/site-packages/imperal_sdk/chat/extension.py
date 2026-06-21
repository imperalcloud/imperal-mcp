# Copyright (c) 2026 Imperal, Inc., Valentin Scerbacov, and contributors
# Licensed under the Apache-2.0 License. See LICENSE file for details.
"""ChatExtension — extension registration and typed dispatch surface."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from imperal_sdk.context import Context as _Context

from imperal_sdk.chat.action_result import ActionResult
from imperal_sdk.chat.exceptions import TaskCancelled

log = logging.getLogger(__name__)


# Words that indicate write/destructive actions — used for backwards-compatible
# action_type detection when no explicit action_type is set on a function.
# Identity pattern — system_prompt must NOT contain self-identification.
# The kernel injects OS identity (assistant_name) automatically.
_IDENTITY_PATTERN = re.compile(r"\byou are (?:a |an |the )", re.IGNORECASE)

_ACTION_WORDS = ("send", "create", "delete", "update", "archive", "reply", "forward", "remove", "move", "trash")

@dataclass
class FunctionDef:
    """Typed function declaration.

    The platform reads ``chain_callable`` from the manifest to pick typed
    dispatch (direct ``app/func(args)`` call) vs. legacy ChatExtension
    LLM-router delegation. Defaults to ``True`` for ALL ``action_type``
    values since v4.2.10, so the platform can deterministically execute the
    typed tool without giving the LLM a chance to summarise instead.

    ``effects`` declares the *intended* side-effect surface
    (``["create:note"]``, ``["delete:folder"]``, …). **Reserved /
    advisory:** the kernel does not currently consume it (no narrator /
    audit-ledger read today); it is retained as declared-intent metadata
    emitted into the manifest.

    ``id_projection`` declares the Pydantic params field that carries the
    resolved target id when this tool runs as a downstream chain step.
    Default empty — the platform falls back to a verb-prefix heuristic
    (``delete_note`` -> ``note_id``). Required for compound names where
    the heuristic produces a wrong field (``delete_notes_from_folder``
    would naively yield ``notes_from_folder_id`` instead of ``folder_id``).
    """
    name: str
    func: Callable
    description: str
    params: dict = field(default_factory=dict)
    action_type: str = "read"  # "read", "write", or "destructive"
    event: str = ""  # event name for ActionResult publishing (e.g. "mail.sent")
    chain_callable: bool = True  # platform uses typed dispatch
    effects: list[str] = field(default_factory=list)  # ["create:note", "delete:folder", ...]
    id_projection: str = ""  # params field carrying resolved target id
    background: bool = False  # advisory per-tool hint; kernel does not consume this decorator field (runtime path: ctx.background_task(long_running=…))
    long_running: bool = False  # advisory per-tool hint; kernel does not consume this decorator field
    _pydantic_model: type | None = None  # auto-detected Pydantic BaseModel class
    _pydantic_param: str = ""  # parameter name that receives the model instance
    _return_model: type | None = None  # data_model kwarg OR autodetected return Pydantic model
    _ui_builder: bool = False  # @chat.function(ui_builder=True): Declarative-UI builder; exempt from the V23 data_model rule


class ChatExtension:
    def __init__(self, ext, tool_name: str | None = None, description: str = "",
                 system_prompt: str = "",
                 model: "str | None" = None, max_rounds: int = 10):
        self.ext = ext
        # tool_name is the canonical chat-registration key: it groups the
        # extension's @chat.function tools in the manifest, anchors the per-turn
        # system prompt, and labels scope-guard audit lines. Optional — derived
        # from the extension app_id (``tool_<app_id>_chat``) when omitted; pass
        # it explicitly to pin a production-stable routing name.
        tool_name = tool_name or f"tool_{ext.app_id}_chat"
        self.tool_name = tool_name
        self.description = description
        self.system_prompt = system_prompt
        if model is not None:
            if not getattr(ChatExtension, "_model_deprecation_warned", False):
                log.warning(
                    f"ChatExtension(tool_name={tool_name!r}, model=...): "
                    "the `model=` parameter is deprecated since SDK 3.3.0. "
                    "LLM model resolution moved to platform ctx-injection (see "
                    "ctx._llm_configs). Will be removed in SDK 6.0.0. "
                    "Remove `model=` from extension app.py."
                )
                ChatExtension._model_deprecation_warned = True
            self.model = model
        else:
            self.model = ""
        self.max_rounds = max_rounds
        self._functions: dict[str, FunctionDef] = {}

        if system_prompt and _IDENTITY_PATTERN.search(system_prompt):
            log.warning(
                f"[SDK] ChatExtension '{tool_name}': system_prompt contains 'You are ...' — "
                "this will be overridden by platform OS identity. "
                "Use a neutral capability description instead. "
                "Example: 'Notes module — manage user notes and folders.'"
            )

        # v5.0.0 removed orchestrator-tool auto-registration: ChatExtension is
        # purely a @chat.function bundle declaration, and the platform chain
        # executor dispatches each function directly via typed dispatch — the
        # host LLM no longer sees a single ``tool_<app_id>_chat`` umbrella tool.
        # ``tool_name`` is retained as the canonical registration key (see the
        # __init__ note above) — it is NOT deprecated.
        ext._chat_extensions = getattr(ext, "_chat_extensions", {})
        ext._chat_extensions[tool_name] = self

    def function(self, name: str, description: str, params: dict | None = None,
                 action_type: str = "read", event: str = "",
                 chain_callable: bool | None = None,
                 effects: list[str] | None = None,
                 id_projection: str | None = None,
                 background: bool = False,
                 long_running: bool = False,
                 data_model: type | None = None,
                 ui_builder: bool = False):
        """Register a chat function.

        Args:
            name: Function name (used in tool_use calls).
            description: What this function does, ≥20 chars (V16). Shown to LLM.
            params: Parameter definitions dict. SDK auto-derives from a Pydantic
                BaseModel param annotation when omitted (V17 — no ``**kwargs``
                or untyped handlers).
            action_type: ``"read"``, ``"write"``, or ``"destructive"``. Drives
                kernel action verification and the 2-step confirmation gate.
            event: Event name for ActionResult publishing.
            chain_callable: When ``True`` the platform issues a direct typed
                call ``app/func(args)`` instead of delegating to the
                ChatExtension LLM router. Defaults to ``True`` for ALL
                action_types since v4.2.10.
            effects: Declared (advisory) side-effect surface —
                ``["create:note"]``, ``["delete:folder"]``, etc. Emitted
                into the manifest as declared-intent metadata; the kernel
                does not currently consume this decorator field.
            id_projection: Name of the params field that carries the
                resolved target id when this tool runs as a downstream
                chain step (e.g. ``"folder_id"`` for
                ``delete_notes_from_folder``).
            background: Advisory per-tool hint. The kernel does not consume
                this decorator field directly; the runtime long-running path
                is ``ctx.background_task(long_running=…)``. Retained for
                extension convention (third-party extensions declare it).
            long_running: Advisory per-tool hint, like ``background`` — not
                consumed by the kernel from this decorator field.
            data_model: **v5.0.1 — Federal Typed Return Contract.** Explicit
                Pydantic ``BaseModel`` subclass declaring the shape of
                ``ActionResult.data`` for this tool. Federal contract:
                I-SDK-DECORATOR-DATA-MODEL-KWARG. When declared, it
                populates ``FunctionDef._return_model`` directly, takes
                precedence over return-annotation auto-detect, and triggers:

                  1. Manifest ``return_schema`` emission.
                  2. Platform catalog ingestion of ``return_model``.
                  3. Classifier envelope rendering of ``return_fields``.
                  4. ``$REF`` resolver path validation against the schema.

                **MUST** be present for ``action_type="read"`` (V23 —
                initially WARN, ERROR after soak via
                ``IMPERAL_VALIDATOR_V23_SEVERITY``). Recommended for
                write/destructive (V24, WARN-only).

                Use the same field names as the corresponding input
                ``CreateXParams`` for round-trip symmetry — this closes the
                ``content_text`` (input) / ``content`` (output) drift class.
        """
        if chain_callable is None:
            chain_callable = True

        def decorator(func: Callable) -> Callable:
            # Auto-detect Pydantic BaseModel params + return type.
            # Resolution priority for _return_model:
            #   1. Explicit `data_model` kwarg — wins
            #   2. Direct `-> SomeBaseModel` return annotation
            #   3. `-> ActionResult[T]` generic extraction
            #   4. None of above → _return_model = None
            resolved_params = params
            _detected_model = None
            _detected_param = ""
            _detected_return_model = None
            try:
                import typing as _typing
                hints = _typing.get_type_hints(func)
                ret_ann = hints.get("return")
                if ret_ann is not None:
                    try:
                        from pydantic import BaseModel as _BM
                        # (2) Direct -> SomeBaseModel
                        if isinstance(ret_ann, type) and issubclass(ret_ann, _BM):
                            _detected_return_model = ret_ann
                        else:
                            # (3) -> ActionResult[T] generic — extract T via
                            # typing.get_args. typing.get_origin returns the
                            # generic class (ActionResult), get_args returns
                            # the typevar binding (NoteRecord,).
                            _origin = _typing.get_origin(ret_ann)
                            _args = _typing.get_args(ret_ann)
                            if _origin is not None and _args:
                                _origin_name = getattr(_origin, "__name__", "")
                                if _origin_name == "ActionResult":
                                    _t_arg = _args[0]
                                    if (
                                        isinstance(_t_arg, type)
                                        and issubclass(_t_arg, _BM)
                                    ):
                                        _detected_return_model = _t_arg
                    except (TypeError, ImportError):
                        pass
            except Exception:
                pass
            # (1) Explicit data_model kwarg WINS over auto-detect.
            if data_model is not None:
                try:
                    from pydantic import BaseModel as _BM_chk
                    if isinstance(data_model, type) and issubclass(data_model, _BM_chk):
                        _detected_return_model = data_model
                except (TypeError, ImportError):
                    pass
            if resolved_params is None:
                import inspect
                import typing as _typing2
                # Use typing.get_type_hints to resolve PEP 563 string
                # annotations to real classes (no manual codepath needed).
                try:
                    _resolved_hints = _typing2.get_type_hints(func)
                except Exception:
                    _resolved_hints = {}
                sig = inspect.signature(func)
                for pname, param in sig.parameters.items():
                    if pname in ("ctx", "self"):
                        continue
                    ann = _resolved_hints.get(pname, param.annotation)
                    if ann == inspect.Parameter.empty:
                        continue
                    try:
                        from pydantic import BaseModel
                        if isinstance(ann, type) and issubclass(ann, BaseModel):
                            schema = ann.model_json_schema()
                            resolved_params = {}
                            for field_name, field_info in schema.get("properties", {}).items():
                                resolved_params[field_name] = {
                                    "type": field_info.get("type", "string"),
                                    "description": field_info.get("description", field_info.get("title", "")),
                                }
                                if field_name not in schema.get("required", []):
                                    resolved_params[field_name]["default"] = field_info.get("default")
                            _detected_model = ann
                            _detected_param = pname
                            break
                    except (TypeError, ImportError):
                        pass
            if resolved_params is None:
                resolved_params = {}

            self._functions[name] = FunctionDef(
                name=name, func=func, description=description,
                params=resolved_params, action_type=action_type, event=event,
                chain_callable=chain_callable,
                effects=list(effects or []),
                id_projection=id_projection or "",
                background=background,
                long_running=long_running,
                _pydantic_model=_detected_model, _pydantic_param=_detected_param,
                _return_model=_detected_return_model,
                _ui_builder=ui_builder,
            )
            return func
        return decorator

    @property
    def functions(self) -> dict[str, FunctionDef]:
        return self._functions
