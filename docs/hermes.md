# Hermes spike

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research, MIT) as a
front door to the lab: its Telegram gateway, cron and memory, on Anthropic's API, with the
lab's data reached over MCP. A spike to judge against Rush's own Telegram, heartbeat and
phone page; nothing in the lab depends on it.

## The lab's MCP server

`lab mcp` serves these tools on stdio (`light_labs/core/mcp_server.py`):

| Tool | Returns |
|---|---|
| `queue_pending` | drafts the robots hold for approval |
| `queue_item` | one pending draft with the context it was drafted from |
| `mail_recent` | Rush's triage: sender, subject, label, summary (never a body) |
| `board_tasks` | Agent Net tasks updated recently, with mentions of PJ or Rush flagged |
| `github_status` | PJ's open PRs (review, checks) and failing CI on watched repos |
| `robot_status` | a robot's journal tail; Roll's last inbox report and when it was taken |
| `rush_present` | a request: Rush shows chosen drafts in its own chat with Send/Reject |

Hermes coordinates; Rush and Roll do the work and keep their own chats and buttons.
Nothing here approves, rejects or sends: `rush_present` only puts drafts in front of PJ,
and his tap in Rush's chat sends. Whatever a tool returns goes to the model Hermes runs on.

Board posts are other agents' text, so Hermes's own shell, file, code, browser,
computer-use and delegation toolsets are off for Telegram and cron (`hermes tools disable
... --platform telegram|cron`); otherwise a crafted post could reach a shell on the Mac.

## Hermes config

`~/.hermes/config.yaml`; secrets (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`) in
`~/.hermes/.env` via `hermes config set`.

```yaml
model:
  provider: anthropic
  default: claude-haiku-5-5  # Sonnet is ~3x the cost; Haiku is enough for the lab tools
auth:
  adopt_external_logins: false  # never read Claude Code's login
mcp_servers:
  lab:
    command: uv
    args: ["run", "--locked", "--directory", "~/.hermes/lab/current", "lab", "mcp"]
    env:
      LAB_VAR: "<light-labs checkout>/var"
```

Hermes runs a deployed commit, not a checkout: `lab deploy hermes` exports `origin/main`
into `~/.hermes/lab/releases/<sha>` (no `.git`; `.env` and Rush's `memory.md` linked from
the checkout), runs `uv sync --locked`, and swaps `~/.hermes/lab/current` to it. Whatever
branch the checkout has open never reaches Hermes. `lab git land` redeploys after each
merge while the deploy tracks main. To try a branch: `lab deploy hermes --ref <branch>`;
it stays there through merges until `lab deploy hermes` puts it back on main.
`~/.hermes/lab/current/DEPLOYED.json` names the ref and commit; the last 3 releases are kept.
A deploy that changes the commit runs `hermes gateway restart`: the gateway reads
`config.yaml` and starts the lab MCP server only at startup, so without a restart it keeps
the old release (and, after pruning, a deleted directory).

`TELEGRAM_ALLOWED_USERS=<PJ's Telegram id>` limits the bot to PJ. Hermes's bot is its own
(not Rush's or Roll's): Telegram hands a bot's updates to one poller.

## Morning brief

A Hermes cron job (`hermes cron list`: `morning-brief`, `0 8 * * *` local) reads every tool
and sends PJ at most 12 lines on Telegram: what needs him, the queue, board mentions,
robot health. About 3 cents a run on Haiku. `hermes insights` shows the spend.
