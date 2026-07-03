"""ChatResult and FunctionCall — typed return envelope for extension dispatch.

Provides to_dict()/from_dict() for kernel serialization (the platform
runtime expects dict). Built by the kernel's typed-dispatch layer after each
extension function invocation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from imperal_sdk.types.action_result import ActionResult


@dataclass
class FunctionCall:
    """Record of a single @chat.function invocation."""

    name: str
    params: dict
    action_type: str
    success: bool
    result: ActionResult | None = None
    intercepted: bool = False
    event: str = ""

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "params": self.params,
            "action_type": self.action_type,
            "success": self.success,
            "intercepted": self.intercepted,
            "event": self.event,
        }
        if self.result is not None:
            # P2 Task 20 hotfix 2026-04-23: accept ActionResult (.to_dict()),
            # plain dict (structured error_code from _execute_function exception path),
            # or fall through to str repr. Defensive — NEVER raise on serialisation.
            if hasattr(self.result, 'to_dict'):
                d["result"] = self.result.to_dict()
            elif isinstance(self.result, dict):
                d["result"] = self.result
            else:
                d["result"] = {'repr': str(self.result)[:500]}
        return d

    @staticmethod
    def from_dict(d: dict) -> FunctionCall:
        from imperal_sdk.types.action_result import ActionResult

        result = None
        if d.get("result"):
            result = ActionResult.from_dict(d["result"])
        return FunctionCall(
            name=d.get("name", ""),
            params=d.get("params", {}),
            action_type=d.get("action_type", "read"),
            success=d.get("success", False),
            result=result,
            intercepted=d.get("intercepted", False),
            event=d.get("event", ""),
        )


@dataclass
class ChatResult:
    """Typed return envelope from the kernel's typed-dispatch layer. Replaces ad-hoc dict."""

    response: str
    handled: bool = False
    functions_called: list[FunctionCall] = field(default_factory=list)
    had_successful_action: bool = False
    message_type: str = "text"
    action_meta: dict = field(default_factory=dict)
    intercepted: bool = False
    task_cancelled: bool = False
    # P2 Task 27 — Narration Contract Hybrid. When the LLM completes a turn
    # by invoking EMIT_NARRATION_TOOL, the parsed NarrationEmission is stored
    # here as a plain dict (model_dump) so the platform runtime can serialize it.
    # None when the LLM used free-form text or the emission failed Pydantic
    # validation (fallback to malformed-but-best-effort prose).
    narration_emission: Optional[dict] = None

    def to_dict(self) -> dict:
        """Serialize to dict for kernel transport."""
        return {
            "response": self.response,
            "_handled": self.handled,
            "_functions_called": [fc.to_dict() for fc in self.functions_called],
            "_had_successful_action": self.had_successful_action,
            "_message_type": self.message_type,
            "_action_meta": self.action_meta,
            "_intercepted": self.intercepted,
            "_task_cancelled": self.task_cancelled,
            "_narration_emission": self.narration_emission,
        }

    @staticmethod
    def from_dict(d: dict) -> ChatResult:
        """Deserialize from kernel dict format."""
        return ChatResult(
            response=d.get("response", ""),
            handled=d.get("_handled", False),
            functions_called=[
                FunctionCall.from_dict(fc) for fc in d.get("_functions_called", [])
            ],
            had_successful_action=d.get("_had_successful_action", False),
            message_type=d.get("_message_type", "text"),
            action_meta=d.get("_action_meta", {}),
            intercepted=d.get("_intercepted", False),
            task_cancelled=d.get("_task_cancelled", False),
            narration_emission=d.get("_narration_emission"),
        )
