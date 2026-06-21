"""Built-in handler for the synthetic ``secrets`` panel.

When an Extension declares one or more ``@ext.secret(...)`` entries, the SDK
auto-registers a panel with ``panel_id='secrets'`` so the user-facing
Secrets manager appears among the extension's other tabs (Overview /
Analytics / Transactions / ...). The extension author doesn't write any
panel code — the SDK provides this canonical handler.

Federal contract: the handler renders a summary of declared secrets +
links to the full /ext/{ext_id}/secrets page where Panel UI handles
PUT/DELETE through type=password input + cleared-on-submit state. We
do NOT inline the input form here because the canonical UI lives in
Panel React (SecretManagerCard) — duplicating it in declarative ui.*
primitives would split the federal contract (I-SECRETS-NEVER-LOGGED,
no-echo, no-clipboard) across two implementations.
"""
from __future__ import annotations

from typing import Any


async def builtin_secrets_panel_handler(ctx: Any, **_params: Any) -> dict:
    """Render the synthetic secrets panel.

    Returns a UINode dict (post-``.to_dict()``) that the kernel relays to
    Imperal Panel. The panel shows one card per declared secret with
    is_set status badge and a primary action that navigates to
    /ext/{ext_id}/secrets — the full SecretManagerCard route.
    """
    # Import inside the handler to keep SDK init light and avoid
    # circular imports if ui.* itself imports anything from secrets.
    from imperal_sdk import ui

    ext_id = getattr(ctx, "ext_id", "") or getattr(ctx, "extension_id", "") or ""

    # Pull declared secrets from ctx if the kernel populated them; fall
    # back to an empty list so the panel still renders cleanly.
    declared = list(getattr(ctx, "_declared_secrets", {}).values()) if getattr(
        ctx, "_declared_secrets", None
    ) else []

    # Try to fetch live is_set state per declared name (cheap meta read).
    statuses: dict[str, dict] = {}
    if hasattr(ctx, "secrets") and ctx.secrets is not None:
        try:
            live = await ctx.secrets.list()
            for s in live:
                # SecretStatus or dict — handle both.
                name = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
                if name is None:
                    continue
                statuses[name] = {
                    "is_set": bool(getattr(s, "is_set", None) if not isinstance(s, dict) else s.get("is_set", False)),
                    "last_accessed_at": (
                        getattr(s, "last_accessed_at", None)
                        if not isinstance(s, dict)
                        else s.get("last_accessed_at")
                    ),
                }
        except Exception:
            statuses = {}

    cards = []
    for spec in declared:
        name = getattr(spec, "name", None) or (spec.get("name") if isinstance(spec, dict) else None)
        if not name:
            continue
        desc = getattr(spec, "description", "") or (spec.get("description", "") if isinstance(spec, dict) else "")
        write_mode = (
            getattr(spec, "write_mode", "user")
            if not isinstance(spec, dict)
            else spec.get("write_mode", "user")
        )
        status = statuses.get(name, {"is_set": False, "last_accessed_at": None})
        is_set = bool(status.get("is_set"))
        last_read = status.get("last_accessed_at")

        # One card per secret with status + Manage button.
        rows = [ui.Text(desc) if desc else None]
        if is_set:
            rows.append(ui.Badge("Set", color="green"))
            if last_read:
                rows.append(ui.Text(f"Last read: {last_read}", color="muted"))
        else:
            rows.append(ui.Badge("Not set", color="gray"))
        if write_mode == "extension":
            rows.append(ui.Text("(extension-write only — written after authorize)", color="muted"))

        rows.append(ui.Button(
            label="Manage" if is_set else "Set value",
            variant="primary" if not is_set else "secondary",
            on_click=ui.Navigate(path=f"/ext/{ext_id}/secrets#{name}"),
        ))

        cards.append(ui.Card(
            title=name,
            content=ui.Stack(children=[r for r in rows if r is not None]),
        ))

    if not cards:
        cards.append(ui.Card(
            title="No secrets declared",
            content=ui.Stack(children=[
                ui.Text(
                    "This extension does not declare any secrets. If you are "
                    "the developer, add an @ext.secret(...) declaration to "
                    "your app.py and redeploy."
                ),
                ui.Link(
                    text="Read @ext.secret reference →",
                    href="https://docs.imperal.io/en/sdk/decorator-secret-reference/",
                ),
            ]),
        ))

    root = ui.Stack(children=[
        ui.Header(f"Secrets · {ext_id}", level=2),
        ui.Text(
            "Credentials this extension needs — API keys, OAuth tokens. "
            "Stored encrypted in Vault; never visible to admins or in logs."
        ),
        *cards,
        ui.Link(
            text=f"Open full Secrets manager →",
            href=f"/ext/{ext_id}/secrets",
        ),
    ])

    # Match the wrapper contract from @ext.panel decorator — return .to_dict()
    # of the root. The kernel wraps {"ui": ..., "panel_id": "secrets"}.
    if hasattr(root, "to_dict"):
        return root.to_dict()
    return root
