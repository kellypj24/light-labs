# Hermes spike

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research, MIT) as a
front door to the lab: its Telegram gateway, cron and memory, on Anthropic's API, with the
lab's data reached over MCP. A spike to judge against Rush's own Telegram, heartbeat and
phone page; nothing in the lab depends on it.

## The lab's MCP server

`lab mcp` serves three read-only tools on stdio (`light_labs/core/mcp_server.py`):

| Tool | Returns |
|---|---|
| `queue_pending` | drafts the robots hold for approval |
| `queue_item` | one pending draft with the context it was drafted from |
| `mail_recent` | Rush's triage: sender, subject, label, summary (never a body) |

Nothing approves, rejects or sends: those stay with PJ (Telegram buttons, the phone page,
`lab rush`). Whatever a tool returns goes to the model Hermes runs on.

## Hermes config

`~/.hermes/config.yaml`; secrets (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`) in
`~/.hermes/.env` via `hermes config set`.

```yaml
model:
  provider: anthropic
  default: claude-sonnet-5-5
auth:
  adopt_external_logins: false  # never read Claude Code's login
mcp_servers:
  lab:
    command: uv
    args: ["run", "--locked", "--directory", "<light-labs checkout>", "lab", "mcp"]
    env:
      LAB_VAR: "<light-labs checkout>/var"
```

`TELEGRAM_ALLOWED_USERS=<PJ's Telegram id>` limits the bot to PJ. Hermes's bot is its own
(not Rush's or Roll's): Telegram hands a bot's updates to one poller.
