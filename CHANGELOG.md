# Changelog

All notable changes to **`imperal-mcp`** — the local stdio MCP server that lets any
LLM client (Claude Code, Codex, Cursor) build and deploy a declarative Imperal app —
are documented here. Depends on `imperal-sdk`.

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
