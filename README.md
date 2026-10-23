# imperal-mcp — The ICNLI-Powered SuperSuite for LLMs & AI Agents 🐝

<!-- mcp-name: io.github.imperalcloud/imperal-mcp -->

[![PyPI](https://img.shields.io/pypi/v/imperal-mcp)](https://pypi.org/project/imperal-mcp/)
[![Python](https://img.shields.io/badge/python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776ab?logo=python&logoColor=white)](https://pypi.org/project/imperal-mcp/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Protocol: ICNLI](https://img.shields.io/badge/ICNLI-CC%20BY--SA%204.0-ff6b00)](https://icnli.org)
[![Protocol: MCP](https://img.shields.io/badge/MCP-Stdio%20Server-10a37f)](https://modelcontextprotocol.io)

**Python 3.7 – 3.14** · `pip install "imperal-mcp[code]"` works out of the box on every one of them.

> **Stop running your LLM blind.**
> `imperal-mcp` is the **all-in-one SuperSuite & Exoskeleton for LLMs** — upgrading **Claude Code, Claude Desktop, Cursor, OpenAI Codex, Windsurf, Gemini CLI, Cline, and Goose** with a live Tree-sitter AST call graph, surgical symbol reading, invisible ShadowGit checkpoints, cross-platform cloud memory, and a full-stack cloud app builder powered by **[ICNLI](https://icnli.org)** and **[Imperal Cloud](https://imperal.io)**.

With a single install, your coding agent **stops dumping whole files into context**, **maps and navigates unfamiliar repositories in one call**, **checks blast radius and syntax automatically on every edit**, **remembers your architecture across every IDE, terminal, and chat surface**, and **builds, deploys, and monetizes full-stack cloud apps on the Imperal Marketplace**.

---

## Why Developers Switch to `imperal-mcp` Immediately

Watch what happens to a typical LLM coding session the moment you attach `imperal-mcp`:

```text
WITHOUT imperal-mcp (Standard Agent Workflow)
  1. cat / Read 1,800-line service.py         -> 72,000 chars dumped into context
  2. grep -rn "process_Order" across repo     -> 140 noisy text matches
  3. Read 3 more full files to trace callers  -> +95,000 chars burned
  4. Edit shared function blind               -> breaks 2 callers & leaves syntax error
  5. Switch from Cursor to Claude Code        -> total amnesia; re-explain architecture from scratch

WITH imperal-mcp (The SuperSuite Exoskeleton)
  1. orient("process_order")                  -> repo profile + top ranked AST symbols in 1 call
  2. outline("service.py")                    -> compact structural map with exact line ranges
  3. read_symbol("service.py", "Order.run")   -> reads ONLY the 28 lines you need
  4. impact_of_change(["Order.run"])          -> lists every dependent file & caller before you touch a line
  5. PostToolUse hook -> check_syntax         -> catches syntax errors in milliseconds after every Edit/Write
  6. checkpoint("before-refactor")            -> instant ShadowGit snapshot outside .git (rollback in 1 call)
  7. recall_context / save_repo_note          -> every rule & repo note follows you across Claude, Cursor & Telegram
```

### The 5 Structural Bottlenecks `imperal-mcp` Eliminates

| Bottleneck in Standard LLM Workflows | What the `imperal-mcp` SuperSuite Delivers | Why You Feel the Difference Immediately |
|--------------------------------------|--------------------------------------------|-----------------------------------------|
| **Unnecessary Token & Context Burn** — Agents read entire multi-thousand-line files and raw `grep` dumps into the context window just to inspect a single function. | **Surgical AST & Call-Graph Slicing** (`outline`, `read_symbol`, `graph_slice`, `contract_slice`) returns *only* the requested symbol definition, signature, and call edges. | **Keep your context window razor-sharp** — load 30 lines of AST-verified code instead of 2,000 lines of noise, and audit exact savings with `token_savings()`. |
| **Slow, Repetitive Orientation** — Every new task starts with dozens of sequential `find`, `ls`, `grep`, and `cat` calls before the model understands the project layout. | **One-Shot Structural Orientation** (`orient`, `repo_profile`, `search_code`, `coding_context`) maps languages, entrypoints, test runners, and ranked symbols from a live code graph. | **Zero cold-start lag** — your agent understands the repo architecture on turn 1. |
| **Context Loss & Amnesia Across Tools** — Switch from Cursor to Claude Code, or from your terminal to web or mobile, and your LLM forgets your architecture, rules, and decisions. | **Cross-Platform Unified Cloud Memory** (`recall_context`, `remember_fact`, `save_repo_note`) syncs user directives and citation-backed repo notes across every MCP client, the Imperal Web Panel, and Telegram. | **Never repeat yourself again** — one persistent engineering brain across every surface and model you use. |
| **Fear of Breaking Shared Code** — LLMs modify shared helpers without checking downstream callers or contracts, and failed multi-file experiments dirty `.git`. | **Blast-Radius Calculus & ShadowGit Snapshots** (`impact_of_change`, `check_syntax`, `checkpoint`, `checkpoint_diff`, `checkpoint_rollback`) verify dependents before edits and snapshot working trees outside `.git`. | **Refactor with total confidence** — know who calls what before editing, and roll back failed experiments without touching `git log`. |
| **Dead-End Local Scripts** — Most MCP servers only wrap a single API; you cannot turn your workflows into reusable apps or revenue streams. | **Full-Stack App Builder & Marketplace Monetization** (`validate_ir`, `smoke_ir`, `deploy_ir`, `run_read_tool`, `run_write_tool`, `upload_file`) lets you build, deploy, and monetize cloud apps on the **Imperal Marketplace**. | **Turn workflows into revenue** — build cloud extensions for yourself, your team, or the entire Imperal ecosystem. |

---

## The 5 Core Pillars of the SuperSuite

### 1. Surgical Context & Honest Token Telemetry (AST Symbol Slicing)
Stuffing an LLM's context window with thousands of lines of unrelated code wastes tokens, slows down time-to-first-token, and degrades reasoning accuracy.
- **Map First, Read Only What Matters**: Instead of reading an entire 1,500-line module into context, your agent calls `outline(path)` to view a compact structural map of classes, methods, and functions with exact line ranges, then calls `read_symbol(path, "ClassName.method")` (or `L120-180`) to load only the target span.
- **Honest, On-Disk Telemetry (`token_savings()`)**: Call `token_savings()` at any point in your session to inspect exact, measured character and line counts (`returned_chars` vs `baseline_chars`, `returned_lines` vs `baseline_lines`, `baseline_files`, and per-tool breakdowns). Baselines are measured directly from the real matched files on disk (`baseline_basis: "matched_files_on_disk"`) — never inflated against the whole repository or synthetic multipliers.

### 2. Live Code Graph, Call Contracts & Blast-Radius Analysis
When installed with `imperal-mcp[code]`, the server maintains an incremental **Tree-sitter AST & dependency graph** (with a built-in Python `ast` fallback so Python syntax checks and outlines work even in minimal environments):
- **`orient(query)`** — One-call task launchpad combining the repository profile with the top-ranked symbols and code matches for your task.
- **`repo_profile()` & `coding_context()`** — Instant overview of languages, file counts, architectural hubs, test command hints, and git working-tree status.
- **`search_code(query, kind, path_glob)`** — Hybrid symbol, semantic, and lexical search across the indexed workspace.
- **`graph_slice(symbols, depth)`** — Batch lookup of symbol definitions, signatures, direct callers, and callees.
- **`contract_slice(symbols)`** — Inspect exact function signatures, return annotations, raised exceptions, and real call-site argument shapes.
- **`impact_of_change(symbols)`** — Compute every downstream file and caller symbol that depends on the code you plan to edit *before* making changes.
- **`check_syntax(path)`** — Instant syntax validation after every edit, plus optional automatic `PostToolUse` hooks for Claude Code.

### 3. Persistent Memory & Context Across Every Platform and Surface
Your architectural knowledge should never be locked inside a single IDE tab or model vendor:
- **`remember_fact(fact, category, tags)`** — Store standing engineering rules, user preferences, and operational directives in Imperal Cloud Memory.
- **`save_repo_note(note, repo, citations)`** — Record durable repository conventions, build commands, and architectural invariants tied to your project.
- **`recall_context(query)`** — Retrieve relevant user facts and repository notes from any MCP-compatible client (**Claude Code, Cursor, Windsurf, Codex, Gemini CLI**), the **Imperal Web Panel**, or **Telegram**.

### 4. Build, Deploy & Monetize Apps on the Imperal Marketplace
Powered by **[ICNLI (Infrastructure Contextual Natural Language Interface)](https://icnli.org)**, `imperal-mcp` is a complete **Cloud Application SDK & Execution Engine**:
- **Author Full-Stack Cloud Apps from Natural Language**: Using the built-in MCP resources (`imperal://ir-spec`, `imperal://ui-catalog`, `imperal://examples`) and the `build_imperal_app` prompt, your LLM compiles your intent into a declarative **Imperal Intermediate Representation (`app.ir.json`)** bundle — complete with UI views, state schemas, connectors, and typed tool handlers.
- **Validate, Smoke-Test & Deploy in Seconds**:
  1. `validate_ir(app_ir)` — Statically verify the IR envelope and every declarative step locally.
  2. `smoke_ir(app_ir, function, args)` — Execute a live dry-run inside an isolated sandbox store on Imperal Cloud and inspect `{ok, result, trace}`.
  3. `deploy_ir(app_ir, app_id)` — Deploy the verified app directly into your Imperal Cloud account.
- **Publish & Monetize on the Imperal Marketplace**: Once your app is deployed and tested, you can publish it to the **[Imperal Marketplace](https://panel.imperal.io)** — sharing or selling custom SaaS connectors, DevOps automations, analytics suites, and domain workflows to other developers and businesses.

### 5. Invisible ShadowGit Safety Net & Capability-Gated Cloud Execution
- **ShadowGit Checkpoints (`checkpoint`, `checkpoint_diff`, `checkpoint_rollback`)**: Snapshot your workspace before risky refactors into an isolated shadow git store without creating noisy WIP commits in your real `.git` history. Compare diffs at any point or roll back when an experiment fails (`checkpoint_rollback` is explicitly marked destructive so your MCP client prompts for confirmation before overwriting working files).
- **Workspace Boundary Protection**: All local code and file tools enforce strict workspace path resolution — requests targeting paths or `root` directories outside the configured workspace root (such as `~/.zshrc` or `/etc`) are rejected with `OutsideWorkspaceError`.
- **Three-Tier Cloud Safety (`read` / `write` / `destructive`)**:
  - `run_read_tool` executes read-only operations and automatically scrubs PII from responses.
  - `run_write_tool` executes standard write tools directly, requires interactive human consent (MCP elicitation) for `destructive` tools, and enforces out-of-band panel approval for financial/money operations.

## Complete Tool & Resource Catalog (25 Tools + 5 Resources)

### Local Code Intelligence & Call Graph (`imperal-mcp[code]`)

| Tool | Read-Only | Destructive | What It Does |
| :--- | :---: | :---: | :--- |
| `orient(query, root?)` | Yes | No | **One-call task orientation**: combines repository profile (`files`, `languages`, `git`, `test_hints`, `sample_symbols`) with top semantic + lexical code matches for `query`. |
| `repo_profile(root?)` | Yes | No | Returns structured repository overview: file count, language distribution, current git ref, test runner hints, and key entry-point symbols. |
| `search_code(query, k?, path_glob?, kind?, root?)` | Yes | No | Hybrid **semantic + lexical + symbol** search across the indexed workspace (`kind`: `all`, `symbol`, or `file`). |
| `outline(path, root?)` | Yes | No | Builds a structural map of a source file (classes, functions, methods, and major regions with exact 1-based line ranges) without loading the full file body. |
| `read_symbol(path, name, root?)` | Yes | No | Reads **only** a specific function, class, method (`Class.method`), or line range (`L10-50`) with 1-based line numbers. |
| `graph_slice(symbols, depth?, root?)` | Yes | No | Returns definition location, signature, direct callers, and direct callees from the live AST call graph for one or more symbols. |
| `contract_slice(symbols?, query?, kind?, k?, root?)` | Yes | No | Extracts verified symbol contracts (definitions, signatures, and call-site evidence) in one call. |
| `impact_of_change(symbols, root?)` | Yes | No | Computes downstream blast radius: every file and symbol that calls or depends on the symbols you plan to modify. |
| `check_syntax(path, root?)` | Yes | No | Validates syntax of a source file after edits (Tree-sitter for multi-language ASTs + Python `ast` and JSON stdlib validation; returns `supported: false, clean: null` for unsupported file types). |
| `coding_context(root?)` | Yes | No | Returns git branch, `HEAD`, dirty working-tree files, and recent commits for instant situational awareness. |
| `token_savings()` | Yes | No | Reports **measured** session character and line telemetry against the real matched files on disk (`baseline_basis: "matched_files_on_disk"`, `baseline_files`, `returned_chars`, `baseline_chars`, `saved_chars`, `returned_lines`, `baseline_lines`, `saved_lines`, `compression_pct`, `by_tool`). |

### Local ShadowGit Checkpoints (`imperal-mcp[code]`)

| Tool | Read-Only | Destructive | What It Does |
| :--- | :---: | :---: | :--- |
| `checkpoint(label?, touched_paths?, root?)` | No | No | Snapshots workspace state into an isolated ShadowGit store without touching `.git` history. |
| `checkpoint_diff(target?, root?)` | Yes | No | Shows unified diff between current working files and a ShadowGit checkpoint (`step` number or ref). |
| `checkpoint_rollback(target?, root?)` | No | **Yes** | Restores workspace files from a ShadowGit checkpoint (`destructiveHint=True` so MCP clients prompt before overwriting working files). |

### Cross-Platform Cloud Memory (`Imperal Cloud`)

| Tool | Read-Only | Destructive | What It Does |
| :--- | :---: | :---: | :--- |
| `recall_context(query?, category?, limit?)` | Yes | No | Recalls durable standing rules, architectural decisions, user preferences, and cross-surface facts from Imperal Cloud (`memory-index`), with automatic PII scrubbing. |
| `remember_fact(fact, category?, tags?)` | No | No | Stores a durable fact, standing rule, or user preference into unified Imperal Cloud memory across Terminal, Web Panel, and Telegram. |
| `save_repo_note(note, repo?, citations?)` | No | No | Saves a citation-backed architectural or repository note (`file:line`) into Imperal Cloud memory. |

### Imperal Cloud App Builder, Sandbox & Execution (`ICNLI`)

| Tool | Read-Only | Destructive | What It Does |
| :--- | :---: | :---: | :--- |
| `validate_ir(app_ir)` | Yes | No | Offline structural + semantic validator for an `app.ir.json` bundle (`ir_version: "1.0"`, state, views, handlers). |
| `smoke_ir(app_ir, function, args?)` | Yes | No | Executes a handler step-by-step inside an isolated sandbox store on Imperal Cloud and returns `{ok, result, trace}`. |
| `deploy_ir(app_ir, app_id?)` | No | No | Validates and deploys an `app.ir.json` application to your Imperal Cloud account. |
| `list_apps()` | Yes | No | Lists all installed and available apps in your Imperal Cloud account with `{id, name, version, description, category, status}`. |
| `get_app(app_id)` | Yes | No | Returns full app manifest, tool schemas, and `action_type` classifications (`read` / `write` / `destructive`). |
| `run_read_tool(app_id, function, params?)` | Yes | No | Executes a `read`-tier cloud tool and scrubs PII (`email`, `phone`, `ssn`, `card`, `jwt`, `api_key`, `iban`) from the response. |
| `run_write_tool(app_id, function, params?)` | No | **Yes** | Executes `write` tools directly, prompts for interactive human consent on `destructive` tools (`approve_once` / `autopilot` / `reject`), and blocks direct financial transfers in favor of panel confirmation. |
| `upload_file(path, name?)` | No | No | Uploads a local file to your Imperal Cloud storage and returns a ` storage:// ` URI for use in cloud tool calls. |

### Built-In MCP Resources

| Resource URI | Content |
| :--- | :--- |
| `imperal://exoskeleton-protocol` | Operating discipline for LLMs: orient first, surgical AST reads, blast-radius checks, and syntax verification. |
| `imperal://ui-catalog` | Reference of the 17 declarative UI components available in `app.ir.json` views. |
| `imperal://ir-spec` | Full specification of the `app.ir.json` envelope, state schema, and the 17 deterministic handler step types. |
| `imperal://examples` | Complete, runnable `app.ir.json` reference applications. |
| `imperal://build-prompt` | Step-by-step system playbook for designing, validating, smoke-testing, and deploying Imperal apps. |

---

## Installation & Quick Start

### 1. Install the Package

```bash
# Full SuperSuite (Cloud + Local AST Code Graph, Call Graph, Search & ShadowGit)
pip install "imperal-mcp[code]"

# Lightweight Cloud-only install (App Builder, Cloud Tools & Cross-Surface Memory)
pip install imperal-mcp
```

> **Python 3.7 – 3.14 compatibility**: On Python 3.10+, `imperal-mcp` runs natively. On older system Pythons (3.7 – 3.9), the zero-dependency `_launch.py` bootstrapper automatically provisions an isolated Python 3.12 runtime via `uv` and installs `imperal-mcp[code]==<version>` on first launch — so the full AST & Call-Graph Exoskeleton works seamlessly even on legacy systems.

### 2. Authenticate with Imperal Cloud (for Cloud Memory & Apps)

```bash
imperal-mcp login
```

This starts a browser-based **OAuth 2.0 Device Authorization + PKCE** flow against Imperal Cloud (`api` / `gateway`) and stores your credentials in `~/.config/imperal/credentials.json` with `0600` permissions. (Local code intelligence tools work offline even before you log in.)

### 3. Connect Your LLM Client

#### Option A: One-Command Setup for Claude Code (Recommended)

Run inside your project repository:

```bash
imperal-mcp claude-setup --with-hooks
```

What this does safely and idempotently:
- Adds the `imperal` server to `.mcp.json` (preserving any existing `mcpServers` entries and refusing to overwrite malformed JSON files).
- Appends the `IMPERAL-MCP-EXOSKELETON` operating section to `CLAUDE.md` (preserving all existing project instructions).
- Installs a `PostToolUse` hook in `.claude/settings.local.json` using the exact Python environment binary that ran `claude-setup`. After `Edit`, `MultiEdit`, or `Write`, the hook runs `check_syntax` and reports any syntax errors to `stderr` with exit code `2` so Claude Code sees and fixes broken syntax immediately.

#### Option B: Claude Code CLI

```bash
claude mcp add imperal -- imperal-mcp
```

#### Option C: Cursor / Claude Desktop / Windsurf / Cline (`.mcp.json` or `claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "imperal": {
      "command": "imperal-mcp",
      "args": [],
      "env": {
        "IMPERAL_WORKSPACE": "/absolute/path/to/your/repo"
      }
    }
  }
}
```

#### Option D: OpenAI Codex / Gemini CLI / Goose

Point any MCP-compatible stdio client at the `imperal-mcp` executable with `IMPERAL_WORKSPACE` set to your repository root.

---

## CLI Reference

```bash
imperal-mcp                  # Start the MCP server over stdio
imperal-mcp login            # Sign in via browser (Device Code + PKCE); supports --no-browser
imperal-mcp logout           # Revoke refresh token and delete local credentials
imperal-mcp claude-setup     # Configure .mcp.json and CLAUDE.md (--workspace, --with-hooks)
imperal-mcp install-hooks    # Install PostToolUse syntax-check hook in .claude/settings.local.json
imperal-mcp hook             # Run a Claude Code hook event handler (post-tool-use)
imperal-mcp status           # Print JSON readiness and repository profile for --workspace
```

---

## Architecture & Security Guarantees

1. **Public Cloud Topology (`api`, `gateway`, `worker`)**:
   All cloud requests communicate over HTTPS with Imperal Cloud's `api` and `gateway` endpoints, dispatching isolated app executions and sandbox smoke runs to `worker` runtimes.
2. **Strict Workspace Confinement**:
   Every local tool resolves paths and `root` overrides via `os.path.realpath` and verifies `os.path.commonpath([workspace_root, candidate]) == workspace_root`. Attempts to read outside the workspace raise `OutsideWorkspaceError`.
3. **Config File Integrity**:
   `claude-setup` and `install-hooks` parse existing `.mcp.json` and `.claude/settings.local.json` strictly — if a user file has a JSON syntax error, the CLI refuses to overwrite it rather than wiping existing settings.
4. **Defensive PII Scrubbing**:
   All cloud read and memory payloads pass through `defensive_scrub`, redacting emails, phone numbers, SSNs, payment cards, JWTs, API keys, and IBANs before entering the model context.

---

## License, Protocol & Trademarks

- **Code License**: Licensed under the **[GNU General Public License v3.0 (GPL-3.0-only)](LICENSE)**.
- **Protocol Specification**: Powered by **[ICNLI (Infrastructure Contextual Natural Language Interface)](https://icnli.org)**, an open specification licensed under **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)**.
- **Privacy Policy**: See **[PRIVACY.md](PRIVACY.md)** for details on local execution, credential storage, and PII redaction.
- **Trademarks & Attribution**:
  `Imperal`, `Imperal Cloud`, `Webbee`, and `ICNLI` are trademarks of **Imperal, Inc.**
  `Claude`, `Claude Code`, `Claude Desktop`, and `Anthropic` are trademarks of Anthropic, PBC. `Cursor` is a trademark of Anysphere, Inc. `OpenAI` and `Codex` are trademarks of OpenAI, Inc. `Windsurf` is a trademark of Exafunction, Inc. (Codeium). `Gemini` is a trademark of Google LLC. All third-party product and company names are used solely to indicate MCP interoperability and compatibility; no endorsement or affiliation is implied.

