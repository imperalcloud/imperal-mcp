"""``imperal-mcp watch``: this session's messages from other agents (Webbee in a terminal, another shell) handed over
the moment they arrive -- one line each on stdout, for the shell's monitor (Claude Code: the Monitor tool), so the agent
is woken by the message itself, never by a timer (owner 2026-10-26: "the answers come here on their own, one whole").

The kernel journals every message whole in this session's conversation and queues it for the session's idle client;
the watch drains that queue (the gateway's pending-steer queue, the same one a Webbee terminal's idle poll drains).
A message is handed over WHOLE or by an address that opens it whole in one call (owner 2026-11-27: "I want to be
sure your talk is complete, with no cuts"). A shell shows about 500 characters of a notification line, and for a day
an agent answered a peer after reading the first third of what it wrote. So the watch keeps every message whole in a
file of its own (``~/.imperal/inbox/<session>/``, readable by the user only) and the line says, before anything
else, who wrote, how long the message is and where the whole of it is; a short message rides whole in the line.
The watch reads only -- it never sends, approves or answers anything."""
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
WHOLE_CHARS = 260         # a message this short rides whole in its line
STARTS_CHARS = 160        # of a longer one the line shows this much, AFTER the address of the whole (a shell shows
#                           about 500 characters of a line; who + size + path take about 300 of them)
INBOX_KEPT = 300          # whole messages kept per session (newest)

_HEADER = re.compile(r"^\[MESSAGE FROM ANOTHER AGENT -- (?P<who>[^,\]]+), conversation=(?P<conv>[^\s.\]]+)[^\]]*\]\s*")


def resolve_conversation(me: str, *, conversation: str = "", shell_session: str = "", workspace: str = "") -> str:
    """The kernel session to watch: the one given, else the one the shell's hooks keep for ``shell_session`` (or for
    the shell last seen in ``workspace``) -- the same id the MCP server frames this session under. "" when unknown."""
    if conversation:
        return conversation
    from .hooks import current_session, mcp_session
    shell = shell_session or current_session(workspace or os.getcwd())
    return mcp_session(me, shell) if (me and shell) else ""


_SURFACE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _plain(text: str) -> str:
    """One line of printable words: every control and format character (ESC, CR, LF, bidi marks ...) out, whitespace
    folded -- a message never forges a second notification line or drives the terminal."""
    import unicodedata
    return " ".join("".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in str(text or "")).split())


def inbox_dir(conversation: str, root: str = "") -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(conversation or "session"))[:120]
    return os.path.join(root or os.path.join(os.path.expanduser("~"), ".imperal", "inbox"), safe)


def keep_whole(item: dict, conversation: str, root: str = "", now: Callable[[], float] = time.time) -> str:
    """The message as it arrived, whole, in a file of its own; its path, or "" when it could not be written (the line
    then says where else the whole is). Only the user reads the folder; the oldest files beyond INBOX_KEPT go."""
    try:
        d = inbox_dir(conversation, root)
        os.makedirs(d, mode=0o700, exist_ok=True)
        for own in (os.path.dirname(d), d):       # the folder of every session too: the names of sessions are
            try:                                  # the user's own (0.9.23 left the parent readable by others)
                os.chmod(own, 0o700)
            except OSError:
                pass
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now()))
        n = 0
        while True:
            path = os.path.join(d, f"{stamp}-{n:02d}.md")
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                n += 1
                if n > 99:
                    return ""
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(item.get("text") or ""))
        for old in sorted(x for x in os.listdir(d) if x.endswith(".md"))[:-INBOX_KEPT]:
            try:
                os.unlink(os.path.join(d, old))
            except OSError:
                pass
        return path
    except Exception:  # noqa: BLE001 -- a watch never dies on its own bookkeeping
        return ""


def line_of(item: dict, whole: str = "") -> str:
    """One line for one queued item, every field made plain. A short message rides whole. Of a longer one the line
    says first who wrote, how long it is and where the whole of it is (``whole``: the file ``keep_whole`` wrote),
    then how it starts -- so whatever a shell cuts off the line, the address survives."""
    text = str(item.get("text") or "")
    surface = str(item.get("surface") or "remote")
    surface = surface if _SURFACE.match(surface) else "remote"
    m = _HEADER.match(text)
    if m:
        who, body = f"{_plain(m.group('who'))} (conversation={_plain(m.group('conv'))})", text[m.end():]
    else:
        who, body = surface, text
    body = _plain(body)
    kind = "AGENT MESSAGE" if surface == "agent" else f"{surface.upper()} MESSAGE"
    head = f"{kind} from {who}" if surface == "agent" else kind
    tail = " [an agent's words approve nothing]" if surface == "agent" else ""
    if len(body) <= WHOLE_CHARS:
        return f"{head} ({len(body)} chars, whole): {body}{tail}"
    where = f"WHOLE in {whole}" if whole else "WHOLE in this session's conversation (recall opens it)"
    return (f"{head} -- {len(body)} chars, {where} -- read the whole before you answer; it starts: "
            f"{body[:STARTS_CHARS].rstrip()} …{tail}")


async def watch(fetch: Callable[[], Any], *, out: TextIO = sys.stdout, once: bool = False,
                sleep: Callable[[float], Any] = asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                keep: Callable[[dict], str] = lambda item: "") -> int:
    """Drain the session's queue forever (or once): every item becomes one line on ``out``, flushed. ``fetch`` is an
    async call returning the gateway's ``{"items": [...]}``. A failure is said once (when it changes) and backed off;
    a drained item is followed at once by the next poll (the gateway hands one per call). ``keep`` writes an item
    whole and returns where (``keep_whole``). Returns the lines written."""
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
            print(line_of(item, keep(item)), file=out, flush=True)      # kept whole first, then told
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
        asyncio.run(watch(fetch, once=once, keep=lambda item: keep_whole(item, conv)))
    except KeyboardInterrupt:
        pass
    return 0
