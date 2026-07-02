from __future__ import annotations

import re

_SYNTHETIC_PREFIXES = ("__panel__", "__widget__", "__webhook__", "skeleton_", "_internal_")
_LEGACY_CHAT = re.compile(r"^tool_.*_chat$")


def is_synthetic(name: str) -> bool:
    return any((name or "").startswith(p) for p in _SYNTHETIC_PREFIXES)


def is_read_only(name: str, action_type: str | None) -> bool:
    """Fail-closed: runnable iff action_type == 'read', not synthetic, and not a
    legacy tool_*_chat BYOLLM orchestrator (opaque effective action)."""
    if is_synthetic(name):
        return False
    if _LEGACY_CHAT.match(name or ""):
        return False
    return action_type == "read"


def classify_tier(name: str, action_type: str | None) -> str:
    """Advisory tier for the MCP write-path UX. The kernel re-grades
    authoritatively (CONTROL != BYPASS) — this is only for local routing.
    Fail-closed: synthetic / legacy tool_*_chat / unknown -> 'blocked'."""
    if is_synthetic(name) or _LEGACY_CHAT.match(name or ""):
        return "blocked"
    if action_type == "read":
        return "read"
    if action_type == "write":
        return "write"
    if action_type == "destructive":
        return "destructive"
    return "blocked"


_MONEY_TOOL_IDS = frozenset({
    "billing.change_plan", "billing.upgrade_plan", "billing.downgrade_plan",
    "billing.buy_tokens", "billing.cancel_subscription",
    "billing.resume_subscription", "billing.renew_subscription",
})


def is_money(app_id: str, function: str) -> bool:
    """Advisory mirror of the kernel money set — used ONLY to route to the panel
    flow (skip terminal consent/autopilot). The kernel re-checks + enforces
    (CONTROL != BYPASS); if this drifts, the kernel still returns
    panel_approval_required and refuses execution."""
    return f"{app_id}.{function}" in _MONEY_TOOL_IDS
