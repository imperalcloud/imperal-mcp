# Privacy Policy - imperal-mcp

**Effective date:** 2026-10-26
**Published by:** Imperal, Inc. - [imperal.io](https://imperal.io)

---

## What imperal-mcp is

`imperal-mcp` is a local stdio MCP server and a set of shell hooks - the exoskeleton for your AI coding agent (Claude
Code, Codex, Cursor, Gemini CLI and others). It runs on your machine. Its local tools (code map, symbol reads, syntax
checks, checkpoints) work offline; memory across sessions, the kernel's step frame and the hallucination check use
your Imperal Cloud account.

---

## Data flows

| What | Where it goes | When |
|------|--------------|------|
| Your Imperal credentials | Stored locally in `~/.imperal/credentials.json` (mode 0600) | On `imperal-mcp login` |
| Your code, as read by the local code tools | Stays on your machine | Always - local tools send nothing |
| Checkpoints | A shadow store on your machine, outside your `.git` | When you call `checkpoint` |
| Session steps: your requests, the agent's calls and their results, its thoughts and answers | Your private space in Imperal Cloud - your agent's memory | When the shell hooks installed by `imperal-mcp setup` (or `claude-setup --with-hooks`) are active, and when you call `frame`, `task` or the memory tools |
| Facts and repo notes | Your private space in Imperal Cloud | When you call `remember_fact` or `save_repo_note` |
| Messages to your other sessions | Your private space in Imperal Cloud | When you call `message_session` |
| App definitions and tool calls | Your Imperal Cloud account | When you call `deploy_ir`, `smoke_ir`, `run_read_tool`, `run_write_tool` or `upload_file` |
| Login | Browser device code + PKCE -> Imperal gateway | No password ever passes through `imperal-mcp` |

All network calls go to your own Imperal account at `https://auth.imperal.io` (or the URL you set in
`IMPERAL_API_URL`), over HTTPS.

---

## Scrubbed before it leaves your machine

Before anything is sent, `imperal-mcp` masks on your machine: private keys, passwords, tokens, JWTs, API keys,
authorization headers, credentials in URLs, emails, phone numbers, payment card numbers and SSNs. Results that come
back from cloud tools are scrubbed of personal data again before your agent sees them.

---

## What imperal-mcp does NOT do

- It does not collect telemetry or analytics.
- It does not send your data to any third party - not Anthropic, not OpenAI, not anyone else. Your agent's own model
  provider is between you and that provider.
- It does not run destructive tools without asking you: destructive cloud tools and `checkpoint_rollback` require your
  confirmation, and money operations require approval in the Imperal panel.
- A message from another agent never approves anything on your behalf.

---

## Your control

- **See and delete.** Everything your agents remember can be viewed and deleted - one item or all of it - from the
  Imperal panel.
- **Delete your account** and your private space is deleted with it.
- **Turn it off.** `imperal-mcp setup --remove` removes exactly what setup added; `imperal-mcp logout` revokes the
  sign-in and deletes the local credentials file.

---

## How your data is protected on the platform

Your memory lives in your own isolated space, in a private storage network that is not exposed to the internet; each
internal service holds its own narrow key. Tokens and credentials of the accounts you connect are encrypted in Vault
with non-exportable keys. No platform secret is stored on a server's disk.

Imperal's platform privacy policy governs data stored in Imperal Cloud: [imperal.io/privacy](https://imperal.io/privacy).

---

## Contact

Questions or concerns: [support@imperal.io](mailto:support@imperal.io)

---

> **Note for marketplace reviewers:** This privacy policy is also hosted at `https://imperal.io/imperal-mcp/privacy`
> (permanent public URL, required by reviewed-tier submission guidelines).
