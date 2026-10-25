# Changelog

All notable changes to **`imperal-mcp`** — the local stdio MCP server that lets any
LLM client (Claude Code, Codex, Cursor) build and deploy a declarative Imperal app —
are documented here. Depends on `imperal-sdk`.

## 0.7.1 — 2026-10-25 — imperal-mcp's own calls reach the vault

### Fixed
- With the shell's hooks on, a call of imperal-mcp's own tools (impact_of_change, read_symbol, grep_code ...) is
  recorded by the hook with its whole answer -- before, the server kept it for a frame that never came, so the
  final answer's check called names those tools showed "made up". The server no longer records them twice.

## 0.7.0 — 2026-10-25 — memory for any shell

### Added
- **`imperal-mcp setup`**: sets up imperal-mcp in every shell found on this machine -- Claude Code, Codex,
  Antigravity CLI, Gemini CLI: the MCP server, the four hooks and the protocol block in the shell's global
  instructions file. `--remove` takes away exactly what it put; a config that does not parse is never written.
- **`imperal-mcp hook session-start | prompt | post-tool | stop`**: one command for every shell's hooks. Every tool
  call, request, thought and answer of the session reaches Imperal's vault (credentials redacted before anything
  leaves the machine; secret files and secret-printing commands withheld; `IMPERAL_MCP_IGNORE` folders never
  recorded). Each request gets the kernel's frame in its context; a final answer with open plan items is handed
  back until each is proven or named with its reason (then the open ones are listed); the session start carries
  the protocol and where the work stands.
- Bounded answers (20 000 characters, `full=true` for everything) and `IMPERAL_MCP_EXTRA_ROOTS`.

### Changed
- The protocol (server instructions, setup blocks, session start) tells any shell what imperal-mcp is and why it
  comes first. The MCP server and the hooks share one kernel session per shell.

## 0.6.6 — 2026-10-25 — a paid frame says why it was refused

### Changed
- **`frame`**: the kernel's frame is priced in Imperal's system pricing (credits per frame, set by the platform admin;
  pointers such as `state_lens` / `recall` stay free). A frame refused for credits returns the kernel's reason
  ("not enough credits for a frame ... -- top up in the panel") and keeps its step, so a retry is never charged twice.

## 0.6.5 — 2026-10-25 — an exact text, a server's line range, callers by name

### Added
- **`grep_code(pattern, root, target, path_glob, k, regex)`**: an exact text inside the code -- a string in a function
  body the symbol search does not index. A server's repo is searched in the vault's synced text (literal only); a local
  repo in its indexable files (never a secret, never a link out of the repo).
- **`read_symbol(name="L120-180", target=...)`** reads a line range of a server's file.
- **`impact_of_change`** lists the callers found only by name (`by_name`: an instance's method the scope rules cannot
  link), marked as such.

### Fixed
- An unavailable answer names its real cause instead of "no synced copy".

## 0.6.4 — 2026-10-25 — a server read never hangs the server

### Fixed
- **`outline` / `read_symbol` run on a worker thread** like every code tool: in 0.6.3 a read of a server's file after
  another code call could wait for the very event loop it blocked, and the whole MCP server hung.
- A call on a server is recorded with its full path there, so the kernel's frame follows the work to that repo.

## 0.6.3 — 2026-10-25 — never a whole folder; frame and file reads follow the target

### Changed
- **A folder that is no repository is never indexed or synced whole** (a home folder, a folder of projects): the code
  tools say so and ask for `root=<a repository inside it>`. Requires `webbee >= 0.5.11` (the same rule for its sync).
- **`frame(root, target)`** takes the repo the work is in, a server's repo too (`target="host:<alias>"`).
- **`outline` / `read_symbol` take `target`**: a server's file is read from the code graph in the vault.
- The kernel's frame for an external agent no longer carries Webbee's reality-probe order.

## 0.6.2 — 2026-10-24 — a server's repo stays fresh; one machine id on macOS

### Changed
- **A repo on a server you reach with your own ssh (`target="host:<alias>"`, `root=<path>`) is synced into the vault graph**
  by webbee's SFTP sync (nothing is written there; only changed files are read): the first time before the question,
  then refreshed behind it at most once a minute -- a question never waits for a listing it already has. Every answer
  carries `synced_at`.
- **Requires `webbee >= 0.5.10`**: one machine id per machine on macOS (the hardware UUID) -- a restart no longer
  registers a new machine and syncs the repo again.

## 0.6.1 — 2026-10-24 — the code tools ask the exact graph; the kernel's frame for your agent

### Changed
- **Code tools answer from the exact code graph in your Imperal vault** (`orient`, `repo_profile`, `search_code`, `graph_slice`, `impact_of_change`, `contract_slice`): the workspace is synced first, callers come by scope rules with their lines, uses inside the same file and tests are told apart, search by meaning works through the gateway. Every tool takes an optional `target` (`local`, `ssh:<connection>`, `host:<alias>`). Without the vault the local index answers and says `coarse`. `outline` / `read_symbol` still read the file on disk.
- **`recall_context`** keeps the notes of the repo you are in (other repos' notes and duplicates dropped).
- **`token_savings`** reports calls and what they returned -- no "saved" estimate.

### Added
- **`task(goal, items)`** and **`frame()`**: the Imperal kernel's step frame for your work -- the same frame a Webbee step gets: your task and plan with what is proven, the code around your focus, what your change reaches, the world, your path. Edits are measured by a workspace snapshot, never claimed.
- **`state_lens`**, **`recall`**, **`vault_log_read`**: what the frame's pointers name, for your session.

### Security
- The frame's exchange never carries a secret file's text (`.env*`, keys, `secrets/`, `.ssh/` ...) and masks personal data.

### Requires
- `imperal-sdk >= 6.2.0`, `webbee >= 0.5.9`.

## 0.6.0 — 2026-10-23 — Exoskeleton SuperSuite: local code intelligence, checkpoints & agent hooks

### Added
- **12 local Exoskeleton MCP tools (`imperal_mcp.exoskeleton`):**
  - **Code graph & surgical navigation:** `orient`, `repo_profile`, `search_code`, `outline`, `read_symbol`, `graph_slice`, `impact_of_change`, and `contract_slice` powered by `webbee` and `imperal-sdk` (`imperal-mcp[code]`).
  - **Reversible shadow-git checkpoints:** `checkpoint_create`, `checkpoint_diff`, and `checkpoint_rollback` for safe workspace snapshots without polluting project git history.
  - **Persistent repo memory & live telemetry:** `coding_context` (durable architectural decisions, gotchas, and convention rules in `.webbee/memory/`) and `token_savings` (session token savings measured against exact matched files on disk).
- **Agent hooks CLI (`imperal-mcp install-hooks` & `imperal-mcp hook`):**
  - Installs non-destructive `UserPromptSubmit` and `PreToolUse` hooks into `.claude/settings.local.json` and `.cursor/hooks.json` (preserving existing user settings and hook entries) to guide agents toward code-graph navigation and automatic checkpoints before file edits.
- **`imperal-mcp[code]` optional extra** in `pyproject.toml` (with automatic `imperal-mcp[code]==<version>` installation in the Python 3.7–3.9 managed runtime launcher).

### Fixed
- **`imperal-mcp login`** now invokes `auth.login_device(cfg)` directly via `asyncio.run(...)` with no external workspace dependencies.

## 0.5.10 — 2026-10-23 — Python versions at the top of the README

### Changed
- README: the supported Python versions (3.7 – 3.14) at the top of the page.

## 0.5.9 — 2026-10-23 — The one-time setup ignores the folder it starts in

### Fixed
- uv runs with `--no-config` from the launcher's own folder: a `uv.toml`, `pyproject.toml` or
  `.python-version` in the folder an agent starts `imperal-mcp` from can no longer pick the package
  index or the interpreter for the Python 3.12 runtime (Python 3.7-3.9 only).

## 0.5.8 — 2026-10-23 — Any Python from 3.7

### Changed
- **`pip install imperal-mcp` works on Python 3.7, 3.8 and 3.9.** The MCP SDK and pydantic 2 need
  3.10+, so on an older Python the install is light: the `imperal-mcp` command
  (`imperal_mcp/_launch.py`, standard library only, 3.7 syntax) sets up the same release on its own
  Python 3.12 once with uv, then hands over to it. uv comes as a wheel on 3.8+; on 3.7 the launcher
  downloads uv's release build from GitHub and checks its published SHA-256. Setup output goes to
  stderr only (stdout is the MCP channel). On 3.10+ nothing changes.
- Checked before release on clean Python 3.7 (arm64 and x86_64), 3.9 and 3.12: install, sign-in CLI,
  and 15/15 full MCP sessions (initialize + tools/list) through the launcher.

### Fixed
- `import imperal_mcp` no longer fails where `importlib.metadata` is missing (Python 3.7).

## 0.5.7 — 2026-10-23 — Installs on Python 3.10, install guide that works

### Fixed
- **`pip install imperal-mcp` failed with "No matching distribution found"** on every Python
  below 3.11 — Ubuntu 22.04 (3.10) among them — though the code runs on 3.10 (whole suite green
  on 3.10.22). `requires-python` is now `>=3.10`, the floor of the `mcp` package itself.
- **The README sent people to `pip install --user`,** which Homebrew Python and Debian 12+ refuse
  (`externally-managed-environment`), and said nothing about the Python version (macOS ships 3.9).
  The install line is now `uv tool install imperal-mcp` (uv brings its own Python) or `pipx`,
  with a table for the four errors people actually hit.

## 0.5.6 — 2026-10-22 — License: GPL-3.0

### Changed
- **License is now GPL-3.0-only** (was Apache-2.0): LICENSE, package metadata and classifier,
  the Claude Code plugin manifests, and `core.py`'s header (which said AGPL-3.0). Releases up to
  0.5.5 remain available under Apache-2.0.

## 0.5.5 — 2026-10-22 — PII masking: back to "when unsure, mask"

### Fixed
- 0.5.4 replaced the broad phone matcher with a list of phone shapes, which let unformatted and
  foreign numbers through unmasked (380991234567, 030 12345678). The broad matcher is back; only
  matches made entirely of certain non-phones (IPv4 with or without a port, versions, ISO dates,
  port ranges) are left as they are. A US dotted 123.456.7890 is still a phone.

## 0.5.4 — 2026-10-22 — Released `mcp<2` pin, MCP Registry catches up, PII masking stops eating IPs

### Fixed
- **`mcp<2` now actually ships.** The pin was committed after 0.5.3 without a version bump, so
  the release workflow skipped it and PyPI 0.5.3 still allowed `mcp>=2` (FastMCP API break).
- **MCP Registry listed 0.2.3 since July.** `server.json` kept its own version (0.2.3); the
  registry refuses a version it already has, and `continue-on-error` hid every refusal. The
  release workflow now writes the released version into `server.json` and the Claude Code
  plugin files before publishing, and a registry failure shows as a warning on the run.
  `server.json` gains `repository`.
- **PII masking no longer turns non-phones into `<PHONE>`:** IPv4 addresses (with ports),
  versions (3.11.15), ISO dates and port ranges are left intact; real phone shapes
  (+country, (area), 123.456.7890, 555-123-4567, national 0XX-…) are still masked.
- **One version source.** `imperal_mcp.__version__` reads the installed package metadata
  (pyproject.toml) instead of a hand-kept string; a test keeps `server.json` and
  `.claude-plugin/*.json` equal to pyproject.toml. Plugin descriptions list all 8 tools.

## 0.5.3 — 2026-09-25 — ICNLI core primitives

### Added
- `imperal_mcp.core`: zero-dependency ICNLI core primitives -- cancellation tokens, a stream
  emitter, a schema validator and the component base (`CancellationToken`, `StreamEmitter`,
  `SchemaValidator`, `ICNLIComponent`, re-exported from `imperal_mcp`).
- `upload_file`: upload a local file from the terminal and place it anywhere on the platform,
  streamed from disk (never as a base64 tool argument).

## 0.5.2 — 2026-07-20 — Auth taxonomy: only a 401 logs you out

### Fixed
- Only an HTTP 401 from the refresh endpoint is a logout; 5xx and network errors raise
  `TransientAuthError` and keep the session. `ensure_access_token(force=True)` forces a refresh.

## 0.5.1 — 2026-07-15 — Harden token refresh against the multi-process rotation race

Patch — fixes an intermittent "session expired" that could hit even a just-logged-in
user. The gateway rotates refresh tokens SINGLE-USE (an atomic claim revokes the
presented token and mints a new pair); `ensure_access_token` had no concurrency guard
and `save_creds` wrote in place, so (a) two tasks in one process, or (b) two processes
sharing the on-disk creds file, could race the same refresh_token — the loser 401ed as
a false logout. Proven live 2026-07-15 against a Webbee client that calls this SDK
frequently (idle-steer poller vs. a starting turn).

### Fixed
- **In-process serialization** — a module-level `asyncio.Lock` around the refresh
  section of `ensure_access_token`; concurrent callers never double-refresh (the
  losers re-check the now-updated on-disk creds instead of racing the network).
- **Cross-process retry** — on a refresh failure, re-read creds from disk after a
  short pause; if the refresh_token there differs from the one just attempted (a
  sibling process already won the rotation and saved), retry once with the fresh
  token. If it's unchanged, it's a genuine logout — raise as before, no blind retry.
- **Atomic save** — `save_creds` now writes to a temp file in the same directory and
  `os.replace`s it onto the real path (atomic rename on POSIX), instead of truncating
  the destination in place; a reader (or a crash mid-write) can no longer observe a
  partial/empty credentials file. 0600 permissions preserved.

### Notes
- The client-side death-window between the gateway's server-side rotation and this
  SDK's `save_creds` call cannot be fully eliminated here — save happens immediately
  after the new pair is fetched, minimizing but not closing the gap. Closing it fully
  needs a gateway-side grace window (tracked separately, server-side).

## 0.5.0 — 2026-07-04 — Device-code login: ONE reliable sign-in for every surface

**Breaking (auth internals).** Replaces the loopback browser-callback login with the
OAuth 2.0 Device Authorization Grant (RFC 8628), so signing in works identically on a
local machine, over SSH, in WSL, in a container, or headless — no `127.0.0.1/callback`
that a remote browser can never reach. Design:
`superpowers/specs/2026-07-04-webbee-device-code-login-design.md`.

### Changed
- **`imperal-mcp login`** now uses the device-code flow: the terminal prints a short
  code and a URL (`https://panel.imperal.io/device`); you open the URL in any browser
  (even on a phone), enter the code, and the terminal polls until it receives tokens.
- `auth.login_device(cfg, *, on_prompt=None, open_browser=True)` (async) is the single
  login entry point. `on_prompt(user_code, verification_uri, verification_uri_complete)`
  lets a host UI (the Webbee dock) render the prompt into its own feed instead of stdout.

### Removed
- Loopback login internals: `auth.login` (sync), `auth.exchange_code`, the local
  `HTTPServer` callback handler, and the `127.0.0.1/callback` redirect. PKCE and CLI
  token issuance (`token_use="cli"`) are unchanged.

## 0.4.0 — 2026-07-02 — Write-path + Money gate: run tools, not just build apps

Minor — adds a guarded **execution** path (write / destructive / money) alongside the existing
build→deploy door. No breaking changes to existing tool names. All authority stays kernel-side
(CONTROL ≠ BYPASS): the MCP tiering is advisory; the kernel re-grades, bills, and audits every op.
Plans: `superpowers/plans/2026-07-02-imperal-mcp-write-path-plan.md` +
`superpowers/plans/2026-07-02-imperal-mcp-money-gate-plan.md`.

### Added
- **`run_write_tool(app_id, function, args)`** — runs a `write` or `destructive` tool of a deployed
  app via the kernel's guarded step-executor (`OperateToolWorkflow` → `execute_tool_step`).
  - `write` runs directly (billed + audited kernel-side).
  - `destructive` requires **explicit consent first** via MCP elicitation (approve-once / autopilot /
    reject); consent always precedes execution — the tool never runs the op before you approve.
  - **Human-enabled session autopilot** — once you choose "autopilot", further destructive ops in the
    session run without re-prompting (never agent- or model-enabled).
- **Money tier (out-of-band panel approval)** — money/billing tools (plan changes, buy-credits,
  subscription lifecycle) execute **only** after a human releases them in an authenticated browser
  panel session. The agent's own token cannot self-release (server-side enforced). `run_write_tool`
  surfaces the panel URL via `elicit_url` and returns `pending_panel_approval`; re-run to complete
  after you approve.
- **`client.operate(...)`** → `POST /v1/extensions/{app_id}/operate`; advisory `classify_tier` /
  `is_money` gates for local UX.

### Security
- Consent (destructive) and human panel release (money) are the load-bearing guards; the kernel
  refuses to execute a money op without a verified panel release. Read-only tools remain on
  `run_read_tool`. PII is masked on every result egress.

## 0.3.0 — 2026-06-23 — Flawless MCP door (Phase 1): a deterministic build→deploy path

Minor — reliability/UX hardening of the deploy door. No breaking changes to tool names.
Part of the "Flawless MCP door" program (`superpowers/plans/2026-06-23-flawless-mcp-door-phase1-plan-1-imperal-mcp.md`).

### Added / Changed
- **`ensure_registered` auto-explorer** — the server transparently ensures the caller is a
  registered developer before a deploy, instead of failing with a raw 403 when `dev_tier`
  is missing (ONB-1).
- **`ensure_app` get-or-create** — deploying to an `app_id` that doesn't exist yet creates it
  (owner-scoped), and re-deploying an existing owned app updates it, rather than erroring on
  duplicate (ONB-2 / DEP-3).
- **Transient-only retry** — network/5xx blips retry with backoff; deterministic 4xx
  (validation, auth, conflict) fail fast — no more retrying an un-retryable error.
- **Truthful errors** — surfaced messages reflect the actual gateway response (no more
  optimistic "done" when the deploy didn't happen). Aligns with the anti-fabrication doctrine.

### Notes
- 72 tests, CI green, tag `v0.3.0`. Live smoke is run by the operator (the gateway python
  whitelist blocks an automated smoke from CI).

## 0.2.0 — 2026-06-21 — Browser login (OAuth PKCE + loopback)

Minor — additive auth flow; no token handling required by the user.

### Added
- **`imperal-mcp login`** — opens the panel `/cli-authorize` page, completes an OAuth
  PKCE + loopback-redirect exchange against the auth gateway (`POST /v1/auth/cli/codes`
  → `POST /v1/auth/cli/token`), and stores the resulting session locally. No API key to
  copy/paste. `.mcp.json` stays `{ "mcpServers": { "imperal": { "command": "imperal-mcp" } } }`.

## 0.1.0 — 2026-06-21 — Initial release: build · validate · smoke · deploy · read-operate

Minor — first published version. Part of the Developer-Platform Exposure program
(`superpowers/specs/2026-06-21-developer-platform-exposure-design.md`).

### Added
- **Local stdio MCP server** (Python, FastMCP) on PyPI as `imperal-mcp`. The client's own
  LLM authors a declarative app (`app.ir.json`); the server provides the rails.
- **Resources** that arm the client LLM: `imperal://ir-spec`, `imperal://ui-catalog`
  (from `imperal_sdk.ui.__all__`), `imperal://examples`; prompt `build_imperal_app`.
- **Build tools:** `validate_ir(app_ir)` (LOCAL, no network), `smoke_ir(app_ir, function, args)`
  (isolated `MockContext`), `deploy_ir(app_ir, app_id)`.
- **Read-only operate (PII-masked):** `list_apps`, `get_app`, `run_read_tool(app_id, function, args)`
  — runs ONLY tools whose `action_type == "read"`; refuses write/destructive; fail-closed on unknown.
