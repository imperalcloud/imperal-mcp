"""Imperal SDK · UI Actions."""
from __future__ import annotations

from .base import UIAction


def Call(function: str, **params) -> UIAction:
    """Direct function call — bypasses chat, executes @chat.function directly."""
    return UIAction(action="call", params={"function": function, "params": params})


def Navigate(path: str) -> UIAction:
    """Client-side navigation."""
    return UIAction(action="navigate", params={"path": path})


def Send(message: str) -> UIAction:
    """Send a message to chat."""
    return UIAction(action="send", params={"message": message})


def Open(url: str) -> UIAction:
    """Open URL in new browser tab."""
    return UIAction(action="open", params={"url": url})


def TrayResponse(badge=None, panel=None):
    """Structure a system tray handler response.

    Args:
        badge: UINode for the tray icon badge (e.g. Badge("5", color="red")).
               Shown as a small number/dot overlay on the tray icon.
        panel: UINode for the dropdown panel (e.g. List of alerts).
               Shown when user clicks the tray icon.

    Example::

        @ext.tray("unread", icon="Mail", tooltip="Unread")
        async def tray_mail(ctx, **kw):
            count = await ctx.store.count("messages", where={"read": False})
            msgs = await ctx.store.query("messages", where={"read": False}, limit=5)
            return TrayResponse(
                badge=Badge(str(count), color="red" if count else "gray"),
                panel=List(items=[
                    ListItem(id=m["id"], title=m["subject"], subtitle=m["from"])
                    for m in msgs
                ]) if msgs else None,
            )
    """
    from .base import UINode
    props = {}
    if badge is not None:
        props["badge"] = badge
    if panel is not None:
        props["panel"] = panel
    return UINode(type="TrayResponse", props=props)
