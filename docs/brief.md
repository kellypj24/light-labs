# Morning brief

`lab brief` (`light_labs/agents/rush/brief.py`): what needs PJ today, in Rush's chat at
07:50, followed by Rush's three oldest waiting drafts with Send and Reject. It replaces
the Hermes cron job (paused 2026-11-24, [hermes.md](hermes.md)) and is meant to retire
the Claude desktop morning task.

## What it reads

| Section | Reader | Goes to Claude |
|---|---|---|
| Today's events and tomorrow morning's, from `BRIEF_CALENDARS` | `core/google.py` `Events`, the `brief` sign-in | counts and times only: events today, first start, starts before 9, work-against-family overlaps, stretches of 3+ events with no break |
| Event titles and places | same | never; code writes one line per event (up to 8), family ones tagged, then conflicts and tomorrow morning |
| Mail from the last 26 hours labelled `needs_reply`, or carrying a bill or deadline | Rush's triage (`mail_recent`) | non-personal senders only, subject and summary through `sanitize.scrub` |
| Personal mail (`sanitize.is_personal`) | same | never; code writes the line |
| PJ's PRs with failing checks, failing CI on watched repos | `github_status` | all but the client repos (`gate.CLIENT_REPOS`), which code writes |
| Approval queue | `queue_pending` | counts and the oldest item's robot, kind and age; never a draft |
| Board items mentioning PJ or Rush | `board_tasks` | title, status, 120 characters of the last comment |
| Robot health | `robot_status` | Rush with no tick in 3 hours; journal trouble from the last 3 hours |
| Today's forecast | `training/weather.py` (api.weather.gov) | high, low, wind chill, precipitation |

One `claude -p` call (`RUSH_BRIEF_BRAIN`, default `claude:sonnet`, gate source
`rush/brief`) writes at most 10 lines from the cloud-safe facts; the first is the phone
banner. It runs on the Claude Code login, so there is no API key to expire. Mail and board
text are other people's words: the call has no tools and the prompt marks them as data.

## Calendar sign-in

```
lab google auth brief --account <mailbox>    # browser consent, once
lab google check brief --account <mailbox>   # lists the calendars it can see
```

The `brief` sign-in holds `calendar.events.readonly` and `calendar.calendarlist.readonly`,
apart from the training planner's free/busy token. `BRIEF_GOOGLE_ACCOUNT` and
`BRIEF_CALENDARS` in `.env` default to `TRAINING_GOOGLE_ACCOUNT` and `TRAINING_CALENDARS`;
every calendar but `primary` is tagged `(family)`. Until the sign-in exists the brief
goes out with `No calendar this run`.

## When something fails

| Failure | Result |
|---|---|
| Claude signed out, timed out, or denied by the gate | the same facts in a fixed layout, last line `Written without Claude (<why>).` |
| A reader raises (board timeout, weather.gov down) | its section is left out, one line names it |
| Nothing to report | `Nothing needs you this morning.` |

## Memory

`var/rush/brief/state.json` holds the mail ids flagged in the last sent brief; a thread
flagged again reads `[still open]`. Each sent brief is kept as `var/rush/brief/<date>.txt`.

## Running it

```
lab brief               # print, send nothing, record nothing
lab brief --no-claude   # fixed layout, no model
lab brief --send        # text it in Rush's chat with the drafts
just brief-install      # the 07:50 LaunchAgent (ops/com.pjkelly.light-labs.brief.plist)
```

## Against the desktop task

The desktop task reads Gmail and Calendar directly and writes a Drive note per run. The
lab brief covers its calendar, mail (through Rush's triage), weather and run-to-run
memory, and adds the queue, CI, board and robot health. Differences: event titles and
personal mail never reach Claude, so the banner line names an event by its time; mail is
what Rush labelled, not a fresh read of the inbox. The desktop task stays until two lab
briefs in a row pass PJ's review.
