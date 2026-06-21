"""ActionResult[T] — universal return type for @chat.function.

Supports both plain dict (backward compat) and Pydantic BaseModel (typed path).
Use factory methods .success() and .error() — do not construct directly.

IMPORTANT: `summary` is ALWAYS shown to the user in chat when the function is
called via DUI (ui.Call). Write clear, user-facing summaries.
For functions without summary, write/custom actions get generic "✓ done" feedback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class ActionResult(Generic[T]):
    """Universal return type for @chat.function handlers.

    Generic over T (Pydantic BaseModel). When T is not specified,
    data is treated as plain dict for backward compatibility.

    Fields:
        status: "success" or "error"
        data: Response payload (dict or Pydantic model)
        summary: User-facing message shown in chat. ALWAYS displayed for DUI calls.
        error: Error message (only for status="error")
        retryable: If True, user can retry the action
        ui: Inline UINode tree for chat rendering (optional)
        refresh_panels: List of panel IDs to refresh after action (e.g. ["sidebar"]).
            If not set, ALL panels refresh. Set to specific IDs for targeted refresh.

    NOTE: Always use factory methods .success() / .error(), or pass all kwargs
    explicitly when constructing directly.
    """

    status: str
    data: T | dict = field(default_factory=dict)
    summary: str = ""
    error: str | None = None
    retryable: bool = False
    ui: Any | None = None
    refresh_panels: list[str] | None = None

    @staticmethod
    def success(
        data: T | dict,
        summary: str,
        *,
        ui: Any | None = None,
        refresh_panels: list[str] | None = None,
    ) -> ActionResult[T]:
        """Create a success result.

        Args:
            data: Response payload.
            summary: User-facing message. ALWAYS shown in chat for DUI calls.
                Write clear, actionable summaries.
            ui: Optional inline UINode for rich chat rendering.
            refresh_panels: Optional list of panel IDs to refresh (e.g. ["sidebar"]).
                If None, all panels refresh. If empty list [], no panels refresh.
        """
        return ActionResult(
            status="success", data=data, summary=summary,
            error=None, retryable=False, ui=ui,
            refresh_panels=refresh_panels,
        )

    @staticmethod
    def error(error: str, retryable: bool = False) -> ActionResult:
        """Create an error result."""
        return ActionResult(
            status="error", data={}, summary="", error=error,
            retryable=retryable,
        )

    def to_dict(self) -> dict:
        """Serialize to dict. Pydantic models are converted via model_dump()."""
        d: dict = {"status": self.status, "summary": self.summary}
        if isinstance(self.data, BaseModel):
            d["data"] = self.data.model_dump()
        else:
            d["data"] = self.data
        # Guard: error might be the staticmethod if constructed without explicit error=
        err = self.error
        if err is not None and isinstance(err, str):
            d["error"] = err
        if self.retryable:
            d["retryable"] = self.retryable
        if self.ui is not None:
            d["ui"] = self.ui.to_dict() if hasattr(self.ui, 'to_dict') else self.ui
        if self.refresh_panels is not None:
            d["refresh_panels"] = self.refresh_panels
        return d

    @staticmethod
    def from_dict(d: dict) -> ActionResult:
        """Deserialize from dict. Data remains as plain dict."""
        return ActionResult(
            status=d.get("status", "error"),
            data=d.get("data", {}),
            summary=d.get("summary", ""),
            error=d.get("error", None),
            retryable=d.get("retryable", False),
            refresh_panels=d.get("refresh_panels", None),
        )

    def validate_against(self, model_class):
        """Validate ``self.data`` against a Pydantic ``BaseModel`` class.

        Federal contract: I-SDK-RETURN-DATA-VALIDATED-AT-EMIT.

        Used by the platform dispatch boundary when
        ``FunctionDef._return_model`` is declared. Extension authors can
        also call this explicitly for early type assurance.

        Behavior:
          - If ``self.data`` is already an instance of ``model_class`` →
            return ``self`` (no-op, already validated by Pydantic construction).
          - If ``self.data`` is a dict → attempt
            ``model_class.model_validate(data)``. On mismatch, logs a
            structured warning with offending fields and returns ``self``
            unmodified (warn-only in v5.0.1; hard fail post-soak).
          - On any other type or validation error → returns ``self`` unmodified.

        Contract: the platform cross-references ``model_class`` fields
        against ``$REF`` paths in chain steps; mismatches between declared
        ``model_class`` and actual emitted data ARE bugs. This helper
        surfaces them.
        """
        if self.data is None:
            return self
        if isinstance(self.data, model_class):
            return self
        if isinstance(self.data, dict):
            try:
                model_class.model_validate(self.data)
            except Exception as _err:
                import logging as _logging
                _logging.getLogger("imperal_sdk.action_result").warning(
                    "data_model mismatch model=%s offending_fields=%s",
                    getattr(model_class, "__name__", "?"), str(_err)[:300],
                )
        return self
