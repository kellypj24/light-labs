# lab dash

One terminal view of what needs PJ today. `light_labs/dash/`, stdlib only, no model.

```
lab dash          # live; needs a terminal
lab dash --once   # one frame on stdout (no color when piped)
```

## Sections

| Section | Source | Notes |
|---|---|---|
| Top line | launchd, Dagster heartbeats, Rush's `state.json`, the pollers | Only when something is wrong: a job that failed or stopped, a Dagster daemon with no scheduler or sensor heartbeat for 5 minutes, no Rush tick for 90 minutes, an expired Google sign-in, a failed `gh` call |
| Claude sessions | `~/.claude/sessions/<pid>.json` joined to `~/.claude/projects/*/<sessionId>.jsonl` | Only sessions whose process is alive and started when the record says (a reused pid is not a session). Waiting on PJ first, longest wait on top. Title, context tokens and last reply come from the log's last 512 KB |
| Today | Stored training plan; Google Calendar through the `dash` sign-in | Row number, time, countdown (`done` / `now` / `in 25m`), title, calendar. `▸` marks the current event, or else the next. Declined and cancelled events are left out |
| Waiting on you from the lab | `var/*/queue/pending`, `var/rush/asks.jsonl` | Counts per robot and kind, escalations, age of the oldest. Read-only: approvals stay in Telegram |
| Tasks, Waiting on others | `DASH_TASKS` (default `~/tasks/tasks.md`) | Overdue red, due today or tomorrow yellow |
| Repo review queue | `gh`, and the CI state Rush's GitHub watch keeps | PJ's PRs with failing checks or changes requested, reviews asked of him (not Dependabot's: Roll has those), a red default branch, issues assigned to him. `DASH_REPOS` overrides the repo list in `dash/review.py` |
| Jobs | `launchctl list`, Dagster's run store, `var/evals/*.run.json` | A count of healthy launchd and Dagster jobs, with each failing one listed under it; `j` opens the full list. The latest run per eval stage |

Calendar, GitHub and Ollama are read on background threads (every 5, 10 and 1 minutes)
and the frame shows the last answer, so a refresh never waits on the network. Local
files are re-read every 5 seconds.

## Keys

| Key | Does |
|---|---|
| `r` | refresh now, including the background sources |
| `1`-`9` | open that calendar row's join link, or its event page (https only) |
| `x` then a letter | tick that task's box |
| `u` | undo the last tick |
| `j` | open or close the full job list |
| `R` | re-exec, so code changes load |
| `q` | quit |

ESC alone does nothing. Pasted text is ignored whole.

## Tasks file

```
- [ ] renew the car registration (2026-12-01)
- [ ] [[Ketan]] send the tailnet key
```

A line with `[[Name]]` waits on Name; the date is optional on both. Bills, renewals and
appointments are dated lines here.

The checkbox is the only thing the dashboard writes. A tick goes through only when the
whole line still reads as it did on screen and the file's mtime is the one that was
read; otherwise nothing is written and the list is re-read. While a letter is being
chosen the list on screen is frozen. Undo works until something else writes the file.
The write is a temp file renamed over the original (a symlink's target, not the link),
so the file's inode changes and extended attributes are not carried over.

## Setup

1. Calendar: `lab google auth dash --account <address>`, then `lab google check dash
   --account <address>`. Scopes: `calendar.events.readonly` and
   `calendar.calendarlist.readonly` ([google.md](google.md)). `DASH_GOOGLE_ACCOUNT` and
   `DASH_CALENDARS` in `.env` default to the training planner's
   `TRAINING_GOOGLE_ACCOUNT` and `TRAINING_CALENDARS`.
2. Tasks: create `~/tasks/tasks.md`, or point `DASH_TASKS` at another file.
3. Ghostty: `keybind = global:ctrl+grave_accent=toggle_quick_terminal` puts a terminal
   on a global hotkey; run `lab dash` in it.

claude-toolkit's status line adds a second line naming other sessions waiting on PJ,
from the same registry.

## What it does not do

- No model call. Event titles from the family calendar are other people's data; they
  are drawn in the terminal and go nowhere else. `EventCalendar` refuses every
  sign-in but `dash`; `Calendar` still has no events method.
- No Radar data: the `radar` gate rule keeps it out of Claude sessions, so this was not
  built or tested against it.
- No approvals. The queue section is a count.
- No session cost: the session log on this machine carries no cost record.
