# imperal-mcp - The Exoskeleton for Your AI Coding Agent 🐝

<!-- mcp-name: io.github.imperalcloud/imperal-mcp -->

[![Imperal MCP on mcprush](https://mcprush.com/badge/imperal-mcp/score.svg)](https://mcprush.com/to/imperal-mcp?ref=badge)
[![PyPI](https://img.shields.io/pypi/v/imperal-mcp)](https://pypi.org/project/imperal-mcp/)
[![Python](https://img.shields.io/badge/python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776ab?logo=python&logoColor=white)](https://pypi.org/project/imperal-mcp/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Protocol: ICNLI](https://img.shields.io/badge/ICNLI-CC%20BY--SA%204.0-ff6b00)](https://icnli.org)
[![Protocol: MCP](https://img.shields.io/badge/MCP-Stdio%20Server-10a37f)](https://modelcontextprotocol.io)

**Stop babysitting your AI.** Put it in an exoskeleton: it remembers everything, sees your whole codebase, can undo any
change and can't fake a result - or hallucinate one past you. Fewer wasted tokens, fewer broken builds. Works with **Claude Code, Cursor, OpenAI Codex, Gemini CLI,
Windsurf, Claude Desktop, Cline and Goose**.

```bash
pip install "imperal-mcp[code]" && imperal-mcp login && imperal-mcp setup
```

The code tools work offline, no account needed. Memory across sessions, the kernel's frame and the hallucination
check run on an [Imperal Cloud](https://panel.imperal.io) account (`imperal-mcp login`) - sign-up is free, plans
and credits: [imperal.io/pricing](https://imperal.io/pricing).

---

## The problem

AI coding agents are brilliant - and work blind:

- **They forget.** Every new session, every switch from Cursor to Claude Code, starts from zero. You explain your
  architecture again. And again.
- **They burn tokens.** To look at one function they read the whole 2,000-line file, then `grep` the repo and read
  three more files.
- **They hallucinate.** A function that doesn't exist. A file it never opened. "I updated the caller" - which one?
  "All tests pass" - nobody ran them. Said with total confidence, and you only find out in production.
- **They break things.** They edit a shared helper without knowing who calls it, and a failed experiment leaves your
  working tree dirty.

## The fix: put your agent in an exoskeleton

`imperal-mcp` wraps the agent you already use. Same model, new abilities:

| Your agent today | In the exoskeleton |
| :--- | :--- |
| Forgets everything between sessions and tools | **Total memory** - every step, finding and decision of every session, across terminals, IDEs, the web panel and Telegram |
| Reads whole files to find one function | **X-ray vision** - a live map of your code: it reads the 28 lines it needs, not 2,000 |
| Edits blind | **Knows the blast radius** - every caller and file a change reaches, *before* the edit |
| Leaves broken experiments behind | **A safety net** - invisible checkpoints; any change undone in one call, your `.git` untouched |
| Invents functions, files and results | **Hallucination check** - every name, file and result it states is matched against what it really read and ran |
| Says "done" when it isn't | **A referee** - a task closes only with proof the kernel saw: a diff, a check that passed, a finding with sources |
| Works alone | **A team** - sees your other agents working right now and talks to them |

An illustration of one task - your own numbers: `token_savings()` measures them in every session.

```text
WITHOUT the exoskeleton
  1. cat service.py (1,800 lines)            -> 72,000 chars dumped into context
  2. grep -rn "process_order" .              -> 140 noisy matches
  3. read 3 more files to trace callers      -> +95,000 chars burned
  4. edit a shared function blind            -> 2 callers broken, a syntax error left behind
  5. "I also updated retry_backoff()"        -> that function doesn't exist
  6. "Done, tests pass!"                     -> it never ran them
  7. open Cursor tomorrow                    -> total amnesia

WITH the exoskeleton
  1. frame                                   -> the task, what is proven, the code around your focus, the world
  2. read_symbol("service.py", "Order.run")  -> only the 28 lines that matter
  3. impact_of_change(["Order.run"])         -> every caller, before you touch a line
  4. checkpoint("before-refactor")           -> undo in one call if it goes wrong
  5. task(goal, items)                       -> an item closes only when the kernel saw the proof
  6. "I also updated retry_backoff()"        -> held back: no file it read holds that name
  7. tomorrow, any tool                      -> recall: the whole history is there
```

---

## Hallucinations: caught before they reach you

You can't trust a sentence just because it sounds sure. So the exoskeleton doesn't trust the model's words - it
checks them against the record of what actually happened in this task.

**On every step**, the names the agent's thinking leans on - functions, files, sizes - are matched against what the
task really read, what its commands really returned and what your code map really holds. A name found nowhere comes
back in the next frame as **NAMED BUT NOT FOUND**, before the agent builds on it.

**On the final answer**, the same check runs once more. Name a symbol nobody read, a file nobody opened, a size
nobody measured - and the answer **doesn't reach you**. It goes back to the agent:

```text
KERNEL FACTS: your answer states what the kernel did not see happen:
- `retry_backoff` -- no file this task read and no output it got contains this name
Correct the answer to the facts, or do the missing work first.
```

The agent then reads the code it skipped, or corrects the claim. Either way, what you get is backed by something real.

**On "done"**, words count for nothing: a plan item closes only on a proof the kernel measured - a diff, a check that
exited 0, a finding with its sources. "Tests pass" without a test run is not a pass.

**What it can't do** - and we'd rather tell you: it doesn't make the model smarter. An agent can still draw a wrong
conclusion from true facts. What it can no longer do is pass off what it never saw.

---

## Powered by ICNLI

**[ICNLI](https://icnli.org)** (Infrastructure Contextual Natural Language Interface) is the open protocol at the
heart of the exoskeleton - and the reason it can promise honesty, not just speed.

Under ICNLI, an agent's work is a **state the kernel can prove**, not a story the model tells:

- **Every step is measured.** What a call read, changed or returned is recorded by the kernel - never taken from the
  model's words.
- **Proven vs. claimed.** The step frame shows what is proven and what is only claimed; a plan item is done only when
  its proof (a diff, a check that exited 0, a finding with sources) was seen.
- **Decisions from facts.** Progress, loops and stalls are computed from what the steps returned, and stated to the
  agent in plain words.
- **One state, every surface.** The same session state serves the terminal, the IDE, the web panel and Telegram.

MCP is how your agent talks to the exoskeleton. **ICNLI is how the exoskeleton thinks.** The specification is open
([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)) at [icnli.org](https://icnli.org).

---

## Quick start

```bash
# 1. Install (Python 3.7 - 3.14; the code map included)
pip install "imperal-mcp[code]"

# 2. Sign in to Imperal Cloud (memory, the kernel's frame, apps)
imperal-mcp login

# 3. Wire every shell found on this machine: server + hooks + protocol
imperal-mcp setup            # Claude Code, Codex, Antigravity CLI, Gemini CLI
```

That's it. From the next prompt on, your agent starts each step from the kernel's frame, remembers across sessions and
gets its final answer checked.

<details>
<summary><b>Other ways to connect</b></summary>

**Claude Code only, in this project:**

```bash
imperal-mcp claude-setup --with-hooks
```

Adds the `imperal` server to `.mcp.json` (keeps your entries, refuses to overwrite malformed JSON), appends the
exoskeleton protocol to `CLAUDE.md`, and installs a `PostToolUse` hook that syntax-checks every `Edit`/`Write`.

**Claude Code CLI:**

```bash
claude mcp add imperal -- imperal-mcp
```

**Cursor / Claude Desktop / Windsurf / Cline** (`.mcp.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "imperal": {
      "command": "imperal-mcp",
      "args": [],
      "env": { "IMPERAL_WORKSPACE": "/absolute/path/to/your/repo" }
    }
  }
}
```

**Any other MCP stdio client:** run `imperal-mcp` with `IMPERAL_WORKSPACE` set to your repository root.

</details>

> **Pricing:** sign-up is free; plans and credits are on [imperal.io/pricing](https://imperal.io/pricing). In imperal-mcp
> only `frame` spends credits; every other tool is free, and the local code tools work offline.

---

## For the geeks: how it works

### The loop

1. **`frame`** - at the start and after each change. The kernel's step frame: the task and plan with what is proven,
   the code around the focus from the exact graph, what the change reaches, the machines and repos, the path so far,
   and a **DECISION** section to act on first. With `imperal-mcp setup`, the shell's prompt hook puts it in context
   automatically.
2. **`task(goal, items)`** - declare the request and the plan; an item closes only by a proof the kernel saw. An item
   that cannot be finished is marked blocked with the reason.
3. **Code** - `orient` -> `outline` -> `read_symbol`; `search_code` / `grep_code` for exact text;
   `impact_of_change` **before** editing a shared symbol. The same tools reach a server's repo with
   `target="host:<alias>"` or `target="ssh:<connection_id>"`.
4. **Safety** - `checkpoint` before risky edits, `checkpoint_diff`, `checkpoint_rollback`; `check_syntax` after.
5. **Memory** - every call, thought and answer is written to the vault by the shell's hooks; look back with `recall`,
   `search_history`, `state_lens`, `vault_log_read`.
6. **The final check** - the stop hook sends the final answer to the kernel: an answer that names a file, symbol or
   size the task never read is handed back to the agent, and open plan items are listed to you.

### Hooks (installed by `imperal-mcp setup`)

| Event | What happens |
| :--- | :--- |
| `session-start` | The session is bound to its kernel state; a missing install is reported |
| `prompt` | Your request is recorded; the kernel's frame for this step is put in context |
| `post-tool` | Every call and its result go to the vault; edits are syntax-checked |
| `stop` | The final answer is checked against the facts; open plan items are named |

### Tool catalog (34 tools, 4 resources, 1 prompt)

**Kernel & task** (Imperal Cloud)

| Tool | What it does |
| :--- | :--- |
| `frame(root?, target?)` | The kernel's step frame - task, proofs, code around the focus, reach of the change, world, path |
| `task(goal, items?)` | Declare the request and the plan; items close only by a measured proof |
| `state_lens(section?, focus?, conversation?)` | What the kernel holds, by section (law, plan, reality, memory, conversation, path) - yours or another live session's |
| `vault_log_read(ref, offset?, limit?, grep?)` | An output the kernel kept in the vault (`vault://logs/...`), paged or grepped |

**Memory & other sessions** (Imperal Cloud)

| Tool | What it does |
| :--- | :--- |
| `recall(ref, offset?, n?, conversation?)` | A past request or answer whole - of this session or another of yours |
| `search_history(query, limit?)` | Your past conversations that hold a text - Webbee, the panel, Telegram, other shells |
| `live_sessions(minutes?, limit?)` | Your other sessions working now, with their newest steps |
| `message_session(conversation, text)` | Write to another live session as an agent; its answer comes back in your frame |
| `recall_context(query, limit?)` | Standing rules, preferences and repo notes, with PII scrubbed |
| `remember_fact(fact, category?, tags?)` | Keep a durable fact or rule across every surface |
| `save_repo_note(note, repo?, citations?)` | Keep a citation-backed note about a repository |

**Code map** (`imperal-mcp[code]`, local or on a server via `target`)

| Tool | What it does |
| :--- | :--- |
| `orient(query, k?)` | One-call orientation: repo profile + top-ranked symbols and matches for the task |
| `repo_profile()` | Languages, file counts, entry points, test hints, git ref |
| `search_code(query, k?, path_glob?, kind?)` | Hybrid symbol + semantic + lexical search |
| `grep_code(pattern, path_glob?, regex?)` | An exact text or regex inside the code |
| `outline(path)` | A file's structure with exact line ranges, without its body |
| `read_symbol(path, name)` | Only one function, class, method or line range (`L120-180`) |
| `graph_slice(symbols, depth?)` | Definitions, signatures, callers and callees |
| `contract_slice(symbols)` | Signatures, returns, raises and real call-site argument shapes |
| `impact_of_change(symbols, full?)` | Every file and call site that depends on what you plan to change |
| `check_syntax(path)` | Tree-sitter (and Python `ast` / JSON) syntax check after an edit |
| `coding_context()` | Project tree and git status snapshot |
| `token_savings()` | Measured characters and lines returned vs. the real files on disk |

**Safety net** (local)

| Tool | What it does |
| :--- | :--- |
| `checkpoint(label?)` | An invisible ShadowGit snapshot - your `.git` history untouched |
| `checkpoint_diff(target?, paths?)` | Diff of the workspace against a checkpoint |
| `checkpoint_rollback(target?)` | Restore a checkpoint (a safety snapshot is taken first; marked destructive, so your client asks) |

**Apps on Imperal Cloud** (ICNLI)

| Tool | What it does |
| :--- | :--- |
| `validate_ir(app_ir)` | Validate an `app.ir.json` locally - the envelope and every declarative step |
| `smoke_ir(app_ir, function, args?)` | Dry-run a handler in an isolated sandbox: `{ok, result, trace}` |
| `deploy_ir(app_ir, app_id)` | Deploy the app to your Imperal Cloud account |
| `list_apps()` / `get_app(app_id)` | Your apps, their manifests, tool schemas and action types |
| `run_read_tool(app_id, function, args?)` | Run a read tool; PII scrubbed from the answer |
| `run_write_tool(app_id, function, args?)` | Run a write tool; destructive ones ask you first, money ones need panel approval |
| `upload_file(path, name?)` | Upload a file to your cloud storage, get a `storage://` URI |

**Resources & prompt:** `imperal://exoskeleton-protocol` (the operating discipline), `imperal://ir-spec`,
`imperal://ui-catalog`, `imperal://examples`, and the `build_imperal_app` prompt for designing, validating,
smoke-testing and deploying an app.

### CLI

```bash
imperal-mcp                  # Start the MCP server over stdio
imperal-mcp login            # Sign in via browser (device code + PKCE); --no-browser prints the URL
imperal-mcp logout           # Revoke the refresh token and delete local credentials
imperal-mcp setup [shells]   # Wire claude | codex | antigravity | gemini (default: the ones found); --remove undoes it
imperal-mcp claude-setup     # Configure .mcp.json and CLAUDE.md for one project (--workspace, --with-hooks)
imperal-mcp install-hooks    # Install the Claude Code PostToolUse syntax-check hook
imperal-mcp hook <event>     # Run a hook event: session-start | prompt | post-tool | stop (JSON on stdin)
imperal-mcp status           # Workspace readiness and index profile
imperal-mcp watch            # Messages from your other agents, one line each, as they arrive (for a shell monitor)
```

### Privacy

See [PRIVACY.md](PRIVACY.md) for every data flow in detail.

### Python 3.7 - 3.14

On Python 3.10+ `imperal-mcp` runs natively. On older system Pythons (3.7 - 3.9) a zero-dependency launcher provisions
an isolated Python 3.12 runtime via `uv` on first launch - the full code map works even on legacy systems.

---

## Built like a vault

Your agent's memory is your work - your code, your decisions, your mistakes. So it's guarded like one.

### What leaves your machine

| Stays on your machine | Goes to your private space in Imperal Cloud |
| :--- | :--- |
| Your code map, symbol reads, syntax checks and checkpoints - **all local tools work offline** | The steps of a session the shell's hooks record: requests, calls and their results, thoughts and answers - that's your agent's memory |
| Your credentials (`~/.imperal/credentials.json`, `0600`) | Facts and repo notes you choose to keep |
| **Secrets and personal data** - removed *before* anything is sent | Apps you deploy |

**Scrubbed on your machine, before sending.** Private keys, passwords, tokens, JWTs, API keys, authorization headers,
credentials in URLs, emails, phone numbers, payment cards and SSNs are masked locally by `imperal-mcp` itself - before
a single byte leaves your machine.

### How it's locked down

- **Your own sealed space.** Every user's memory lives in its own isolated space, in a private storage network that is
  never exposed to the internet. Each internal service holds its own narrow key and reaches only what it needs.
- **Secrets sealed with keys that can't be taken out.** Your connected accounts' tokens and credentials are encrypted
  in Vault with non-exportable keys - a full copy of the database reveals nothing.
- **Zero keys on disk.** No platform secret is ever written to a server's disk: every service gets its keys from
  Vault at start, bound to that one machine.
- **Distributed infrastructure.** Isolated environments across independent data centers and providers - no single
  provider holds the whole platform.
- **Durable by design.** Every agent turn runs as a durable workflow: a restart or an outage costs time, never your
  work.
- **Encrypted in transit.** Everything between your machine and the platform goes over HTTPS; you sign in with OAuth
  2.0 device code + PKCE, and no password ever passes through `imperal-mcp`.

### And on your machine

- **Workspace confinement.** Local tools resolve every path and refuse anything outside your workspace root.
- **Your config files are safe.** `setup`, `claude-setup` and `install-hooks` refuse to overwrite a JSON file they
  cannot parse; `setup --remove` takes away exactly what it added.
- **You stay in charge.** Destructive actions ask you first; money moves only with your approval in the panel. A
  message from another agent informs - it approves nothing.
- **Your memory, your call.** See everything your agents remember and delete any of it - or all of it - from the
  Imperal panel. Delete your account and your space goes with it.

---

## FAQ

**Does it replace Claude Code / Cursor / Codex?**
No. It's an exoskeleton, not a new agent: you keep your tool and your model - the exoskeleton makes them remember,
see, check and prove.

**Which model does it use?**
Yours. The kernel does the bookkeeping - measuring, remembering, checking - and your agent's model does the thinking.

**What does it cost?**
Sign-up is free. Plans, included credits and top-ups are on [imperal.io/pricing](https://imperal.io/pricing). In
imperal-mcp only `frame` (the kernel's step frame) spends credits; every other tool - the code map, checkpoints,
memory, history, messaging - is free.

**Does it work without the cloud?**
The code map, symbol reads, blast radius, syntax checks and checkpoints run fully offline. Memory across sessions,
the kernel's frame and the hallucination check need your Imperal Cloud account.

**How is this different from an MCP server that searches code?**
Search tells your agent where things are. The exoskeleton also remembers what it did, knows what a change will break,
holds it to its plan and checks every claim against what really happened - under one protocol, ICNLI.

**Can I remove it?**
`imperal-mcp setup --remove` takes away exactly what setup added. `imperal-mcp logout` revokes the sign-in and deletes
the local credentials.

---

## Author

Created by **Valentin Scerbacov** ([valentin@imperal.io](mailto:valentin@imperal.io)) and built at
**[Imperal](https://imperal.io)**.

---

## License, protocol & trademarks

- **Code:** [GNU General Public License v3.0 (GPL-3.0-only)](LICENSE).
- **Protocol:** [ICNLI](https://icnli.org), an open specification under
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **Privacy:** see [PRIVACY.md](PRIVACY.md) - local execution, credential storage and PII redaction.
- **Trademarks:** `Imperal`, `Imperal Cloud`, `Webbee` and `ICNLI` are trademarks of **Imperal, Inc.** `Claude`,
  `Claude Code`, `Claude Desktop` and `Anthropic` are trademarks of Anthropic, PBC. `Cursor` is a trademark of
  Anysphere, Inc. `OpenAI` and `Codex` are trademarks of OpenAI, Inc. `Windsurf` is a trademark of Exafunction, Inc.
  (Codeium). `Gemini` is a trademark of Google LLC. All third-party names indicate MCP interoperability only; no
  endorsement or affiliation is implied.
