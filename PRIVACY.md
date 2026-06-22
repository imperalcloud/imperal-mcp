# Privacy Policy — imperal-mcp

**Effective date:** 2026-06-22  
**Published by:** Imperal, Inc. — [imperal.io](https://imperal.io)

---

## What imperal-mcp is

`imperal-mcp` is a local stdio MCP server. It runs on your machine and gives LLM agents (Claude Code, Codex, Cursor, etc.) the ability to build and deploy apps on the Imperal platform.

---

## Data flows

| What | Where it goes | Notes |
|------|--------------|-------|
| Your Imperal credentials | Stored locally in `~/.imperal/credentials.json` (mode 0600) | Never sent to third parties |
| App IR definitions you author | Sent to `https://auth.imperal.io/v1/…` (your Imperal account) | Only when you explicitly call `deploy_ir` or `smoke_ir` |
| Read-tool results | Returned to your local LLM agent after a client-side PII scrub | Email and phone patterns are redacted before the agent sees them |
| Login flow | Browser PKCE → Imperal gateway → one-time code exchanged locally | No password or token is ever passed through the MCP server itself |

---

## What imperal-mcp does NOT do

- It does not collect telemetry or analytics.
- It does not send data to any third party (not Anthropic, not OpenAI, not anyone else).
- It does not store conversation history.
- It does not execute write or destructive tool calls — `run_read_tool` gate-checks the tool's `action_type` and refuses anything that is not `read`.

---

## Data stored on your machine

| Path | Content | When created |
|------|---------|--------------|
| `~/.imperal/credentials.json` | Access token + refresh token (mode 0600) | On `imperal-mcp login` |

Running `imperal-mcp logout` removes this file.

---

## Data sent to Imperal

All network calls go to your own Imperal account at `https://auth.imperal.io` (or the URL you set in `IMPERAL_API_URL`). Imperal's own privacy policy governs how data is stored on the platform side: [imperal.io/privacy](https://imperal.io/privacy).

---

## Contact

Questions or concerns: [support@imperal.io](mailto:support@imperal.io)

---

> **Note for marketplace reviewers:** This privacy policy is also hosted at `https://imperal.io/imperal-mcp/privacy` (permanent public URL, required by reviewed-tier submission guidelines).
