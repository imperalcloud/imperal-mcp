"""P4 Task 43 — Kernel-mediated cross-extension dispatch primitive.

When an extension's inner LLM discovers mid-turn that it needs another
extension's capability (e.g., mail extension needs notes content to
compose digest), it MUST use ``hub_dispatch`` to delegate. Kernel spawns
the target extension in an isolated sandbox, returns structured result.

This is the ONLY sanctioned cross-extension path post-Isolation-B1.
Direct tool-name calls to another extension's functions are physically
impossible (EMIT_NARRATION_TOOL + own-tool schema = the complete universe).

Spec refs:
  - docs/superpowers/specs/2026-04-23-federal-grade-chat-integrity-design.md §4.3
  - Invariants: I-EXT-TOOL-ISOLATION, I-HUB-DISPATCH-DEPTH-3,
    I-HUB-DISPATCH-NO-CYCLE, I-HUB-DISPATCH-RBAC
"""
from __future__ import annotations

HUB_DISPATCH_TOOL = {
    "name": "hub_dispatch",
    "description": (
        "Delegate a specific task to another extension. Use when your "
        "extension discovered mid-turn that it needs data or action from "
        "a different extension to complete the user's request. The kernel "
        "spawns an isolated sandbox for the target extension, returns "
        "structured result here in your next round's tool_result. "
        "Do NOT use for simple questions — use when you need a real action "
        "or data fetch. Max delegation depth: 3."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["app_id", "reasoning", "query"],
        "properties": {
            "app_id": {
                "type": "string",
                "description": (
                    "Target extension app_id (e.g., 'notes', 'sql-db', "
                    "'mail'). Must exist in the user's installed + enabled "
                    "app list; kernel rejects unknown."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Why delegation is needed. Appears in the audit log "
                    "visible to the user + federal forensics. Be specific."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query for the target extension's "
                    "inner LLM loop. The target sees only this query + its "
                    "own tool schema."
                ),
            },
        },
    },
}


def is_hub_dispatch_tool_use(tool_name: str) -> bool:
    """Fast identity check used in handler dispatch branching."""
    return tool_name == "hub_dispatch"


__all__ = ["HUB_DISPATCH_TOOL", "is_hub_dispatch_tool_use"]
