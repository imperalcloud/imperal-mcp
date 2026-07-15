# Changelog

All notable changes to **`imperal-mcp`** — the local stdio MCP server that lets any
LLM client (Claude Code, Codex, Cursor) build and deploy a declarative Imperal app —
are documented here. Depends on `imperal-sdk`.

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
