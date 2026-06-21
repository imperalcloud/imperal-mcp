# imperal-mcp

A stdio MCP server that lets any LLM (Claude Code, Codex, Cursor, etc.) build and deploy
[Imperal](https://imperal.io) apps using the declarative IR format.

The client's own LLM authors the app; this server validates, smokes, and deploys it — no
hand-written deployment scripts needed.

---

## Install

```bash
pip install imperal-mcp
```

Or from source:

```bash
cd imperal-mcp
pip install -e .
```

---

## Configure (`.mcp.json`)

Add to your project's `.mcp.json` (or Claude Code's global MCP config):

```json
{
  "mcpServers": {
    "imperal": {
      "command": "imperal-mcp",
      "env": {
        "IMPERAL_API_URL": "https://auth.imperal.io",
        "IMPERAL_TOKEN": "<your-imperal-access-jwt>"
      }
    }
  }
}
```

Get your token from [panel.imperal.io](https://panel.imperal.io) → Developer → Access tokens.

---

## Tools

| Tool | Description |
|------|-------------|
| `validate_ir(app_ir)` | Validate an `app.ir.json` locally — envelope structure + every declarative step. No network. Returns `{valid, issues}`. |
| `smoke_ir(app_ir, function, args?)` | Run one function in an isolated store and report `{ok, result, trace}`. |
| `deploy_ir(app_ir, app_id)` | Deploy an `app.ir.json` into the caller's account (creates the app record if needed). |
| `list_apps()` | List the caller's developer apps (PII-masked). |
| `get_app(app_id)` | Get one app's manifest + tools with `action_type` (PII-masked). |
| `run_read_tool(app_id, function, args?)` | Run a `read`-only tool of a deployed app. Refuses `write`/`destructive` tools. |

---

## Resources

| URI | Description |
|-----|-------------|
| `imperal://ir-spec` | IR envelope specification — structure, fields, action vocabulary. |
| `imperal://ui-catalog` | All `ui.*` component names usable in panels and render steps. |
| `imperal://examples` | Example `app.ir.json` (link-saver) to use as a starting point. |

---

## Prompt

`build_imperal_app` — step-by-step guidance for an LLM to go from intent to a deployed app:
read the spec, author the IR, validate, smoke, deploy.

---

## Security

`run_read_tool` is gate-kept: it looks up the tool's `action_type` from `get_app` and refuses
any tool that is not explicitly `action_type: "read"`. Write and destructive tools are never
executed. All read responses pass through a client-side PII scrub (email/phone redaction) before
being returned to the LLM.
