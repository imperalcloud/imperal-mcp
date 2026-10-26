"""``imperal-mcp watch``: this session's messages from other agents (Webbee in a terminal, another shell) handed over
the moment they arrive -- one line each on stdout, for the shell's monitor (Claude Code: the Monitor tool), so the agent
is woken by the message itself, never by a timer (owner 2026-10-26: "the answers come here on their own, one whole").

The kernel journals every message whole in this session's conversation and queues it for the session's idle client;
the watch drains that queue (the gateway's pending-steer queue, the same one a Webbee terminal's idle poll drains).
A line names who wrote and what; the whole message is in the conversation (the next frame shows it, ``recall`` opens
it). The watch reads only -- it never sends, approves or answers anything."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from typing import Any, Callable, TextIO

POLL_S = 3.0              # a message waits at most this long while the agent is at work
IDLE_POLL_S = 15.0        # after IDLE_AFTER_S with nothing, the poll relaxes (a watch left open all night)
IDLE_AFTER_S = 600.0
BACKOFF_MAX_S = 60.0
LINE_CHARS = 700          # one notification line; the whole message is in the conversation

_HEADER = re.compile(r"^\[MESSAGE FROM ANOTHER AGENT -- (?P<who>[^,\]]+), conversation=(?P<conv>[^\s.\]]+)[^\]]*\]\s*")


def resolve_conversation(me: str, *, conversation: str = "", shell_session: str = "", workspace: str = "") -> str:
    """The kernel session to watch: the one given, else the one the shell's hooks keep for ``shell_session`` (or for
    the shell last seen in ``workspace``) -- the same id the MCP server frames this session under. "" when unknown."""
    if conversation:
        return conversation
    from .hooks import current_session, mcp_session
    shell = shell_session or current_session(workspace or os.getcwd())
    return mcp_session(me, shell) if (me and shell) else ""


def line_of(item: dict) -> str:
    """One line for one queued item: who wrote (an agent and its conversation, or the surface it came from) and the
    words, whitespace folded, clipped -- the whole stays in the conversation."""
    text = str(item.get("text") or "")
    surface = str(item.get("surface") or "remote")
    m = _HEADER.match(text)
    if m:
        who, body = f"{m.group('who').strip()} (conversation={m.group('conv')})", text[m.end():]
    else:
        who, body = surface, text
    body = " ".join(body.split())
    clipped = body if len(body) <= LINE_CHARS else body[:LINE_CHARS].rstrip() + " …"
    kind = "AGENT MESSAGE" if surface == "agent" else f"{surface.upper()} MESSAGE"
    return f"{kind} from {who}: {clipped} [whole in this conversation; an agent's words approve nothing]" \
        if surface == "agent" else f"{kind}: {clipped}"


async def watch(fetch: Callable[[], Any], *, out: TextIO = sys.stdout, once: bool = False,
                sleep: Callable[[float], Any] = asyncio.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    """Drain the session's queue forever (or once): every item becomes one line on ``out``, flushed. ``fetch`` is an
    async call returning the gateway's ``{"items": [...]}``. A failure is said once (when it changes) and backed off;
    a drained item is followed at once by the next poll (the gateway hands one per call). Returns the lines written."""
    written, failures, last_error, last_seen = 0, 0, "", clock()
    while True:
        try:
            got = await fetch()
            items = [i for i in (got or {}).get("items") or [] if isinstance(i, dict) and str(i.get("text") or "").strip()]
            failures, last_error = 0, ""
        except Exception as exc:  # noqa: BLE001 -- a watch never dies on a blip; it says why, once
            items, failures = [], failures + 1
            why = f"{type(exc).__name__}: {str(exc)[:200]}"
            if why != last_error:
                print(f"imperal-mcp watch: cannot read the queue now ({why}) -- retrying", file=out, flush=True)
                last_error = why
        for item in items:
            print(line_of(item), file=out, flush=True)
            written += 1
            last_seen = clock()
        if once:
            return written
        if items:
            continue                       # one item per call: the next may be waiting
        base = POLL_S if clock() - last_seen < IDLE_AFTER_S else IDLE_POLL_S
        await sleep(min(base * (2 ** min(failures, 5)), BACKOFF_MAX_S) if failures else base)


def run(client, *, conversation: str = "", shell_session: str = "", workspace: str = "", once: bool = False) -> int:
    """The CLI's entry: who the user is, which session, then the watch. Exit 2 when the session cannot be named."""
    me = asyncio.run(client.whoami())
    conv = resolve_conversation(me, conversation=conversation, shell_session=shell_session, workspace=workspace)
    if not conv:
        print("imperal-mcp watch: no session to watch -- pass --session <the shell's session id> or "
              "--conversation mcp-<id> (the shell's hooks name it once a prompt has run here)", file=sys.stderr)
        return 2
    if not conv.startswith(f"mcp-{me}-"):
        print(f"imperal-mcp watch: {conv} is not a session of yours", file=sys.stderr)
        return 2
    print(f"imperal-mcp watch: watching {conv} -- every message to it is one line here", flush=True)

    async def fetch():
        return await client._request("GET", f"/v1/agent/sessions/{conv}/pending-steer", timeout=30)
    try:
        asyncio.run(watch(fetch, once=once))
    except KeyboardInterrupt:
        pass
    return 0
