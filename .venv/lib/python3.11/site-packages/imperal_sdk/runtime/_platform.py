"""Substrate-neutral platform-runtime shim.

Single owner of the SDK's optional platform-runtime imports. When the platform
runtime is unavailable (SDK running standalone, e.g. unit tests), each helper
degrades gracefully with engine-neutral wording — the underlying module names
never surface in user-facing warnings or tracebacks.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("imperal_sdk.platform")

_FALLBACK_SCOPE = {
    "allowed": False,
    "reason": "platform runtime unavailable",
    "target_user_id": "",
    "required_scope": "",
    "force_confirmation": False,
    "cross_user": False,
    "verdict": "no_platform_fallback",
}


def check_target_scope(**kwargs: Any) -> dict:
    """Delegate the target-scope check to the platform runtime; safe fallback if absent."""
    try:
        from imperal_kernel.pipeline.scope_guard import _check_target_scope
    except ImportError:
        return dict(_FALLBACK_SCOPE)
    return _check_target_scope(**kwargs)


async def record_action_via_chokepoint(*, app_id: str, event_type: str,
                                       data: dict, kctx_dict: dict) -> bool:
    """Route an extension emit through the platform audit chokepoint.

    Returns True if the chokepoint handled it; False if the platform runtime is
    unavailable (caller falls back to publish_event_fallback).
    """
    try:
        from imperal_kernel.audit import record_action, AuditStatus, AuditSource
    except ImportError:
        log.warning("platform runtime unavailable — using direct event publish")
        return False
    tenant_id = kctx_dict.get("tenant_id", "default")
    user_id = kctx_dict.get("user_id", "")
    kctx = type("_SDKEmitKctx", (), {"user": type("_SDKEmitUser", (), {
        "imperal_id": user_id, "tenant_id": tenant_id,
        "email": kctx_dict.get("email", ""),
    })()})()
    plan = type("_SDKEmitPlan", (), {
        "app_id": app_id, "tool": "<emit>", "tenant_id": tenant_id, "is_destructive": False,
    })()
    result = type("_SDKEmitResult", (), {"status": "success", "data": data, "event": event_type})()
    await record_action(
        plan=plan, kctx=kctx, result=result,
        status=AuditStatus.completed, source=AuditSource.user,
        action_meta={"action_type": "write", "intent_type": "write",
                     "event_type": f"{app_id}.{event_type}", "extension_emit": True},
    )
    return True


async def publish_event_fallback(*, event_type: str, data: dict, source_app: str,
                                 user_id: str, tenant_id: str) -> None:
    """Legacy direct event-store publish (used only when the chokepoint is unavailable)."""
    try:
        from imperal_kernel.core.redis import get_shared_redis
    except ImportError:
        log.error("platform event store unavailable — emit dropped")
        return
    r = get_shared_redis()
    event = json.dumps({"event_type": event_type, "data": data, "source_app": source_app,
                        "user_id": user_id, "tenant_id": tenant_id})
    await r.publish(f"imperal:events:{tenant_id}", event)


try:  # best-effort availability flag
    import imperal_kernel.audit  # noqa: F401
    PLATFORM_RUNTIME_AVAILABLE = True
except ImportError:
    PLATFORM_RUNTIME_AVAILABLE = False
