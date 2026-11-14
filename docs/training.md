# Training

Strong (lifting) logs land in `var/lab.duckdb` as `raw.strong_sets`, then
`staging.stg_strong_sets`. Cardio comes from Apple Health (Strava writes runs and rides
there) as `raw.health_workouts`, then `staging.stg_health_workouts`. Build plan: `docs/plans/training.md`.

## Weekly Strong drop

On the phone, Sunday after the last session:

1. Strong → export data (CSV).
2. In the share sheet, pick Telegram → Rush.

Rush replies `Got N sets, <first> to <last>. Saved strong-<yyyy-mm-dd>.csv.` No reply
means the Mac was off or asleep for more than a day (Telegram drops undelivered updates
after 24 hours): send it again. A second drop the same day replaces the first; each export
holds the full history.

Rush refuses a file that isn't Strong's layout (`Not a Strong export: ...`). That usually
means Strong changed its export; the header is pinned in `light_labs/training/strong.py`.

Reminder: a Shortcuts personal automation, Sunday 18:00, "Show notification: Strong
export to Rush".

## On the Mac

| Step | Where |
|---|---|
| Rush checks the CSV and saves it | `var/training/strong/inbox/` |
| Dagster sensor `strong_dropped` (every minute, skipped during a fight or heavy job) runs `strong_job` | |
| The importer moves inbox files to the archive and reloads the table from the newest | `var/training/strong/` |

By hand: `lab training ingest-strong [<csv>]`.

What the parser assumes:

- Weights are lb (`UNIT`); the export has no unit column. Bodyweight sets log 0.
- Rest-timer rows are not sets and are dropped.
- A letter in Set Order (W, D, F) replaces the set's number; `set_number` is the set's
  position within its exercise, `set_type` the letter's meaning.
- RPE is empty in PJ's export so far.

## Daily Health workouts

Strava → Settings → Applications, Services, and Devices → Health: on. Telegram's Shortcuts
action can't message a bot, so the Shortcut posts to Rush's remote page over the tailnet
instead (`POST /drop/health`, the same check and inbox as Telegram).

Shortcut "Send Cardio to Lab":

1. **Export Workouts** (Health Exporter & Shortcuts): Last 7 days, all activity types.
2. **Get Contents of URL**: `http://<mac>.<tailnet>.ts.net/drop/health` (the address
   `tailscale serve status` prints). Show More: Method POST; Headers `X-Lab-Drop` = `1`;
   Request Body File → the Workouts output from step 1.
3. **Show Result** (only while testing): Rush's reply, e.g. `Got 4 workouts (running), …`.

Shortcuts → Automation → Time of Day 21:00, Daily, Run Immediately → the shortcut. Tailscale
on the phone needs VPN On Demand so it's connected at 21:00, and the Mac must be awake; a
missed night is covered by the next one, since exports overlap and the table is keyed by
HealthKit uuid.

A JSON file shared to Rush on Telegram by hand still works, and so does
`lab training ingest-health [<json>...]`.

The endpoint takes `POST /drop/strong` too: a share-sheet Shortcut (Receive Files from
Share Sheet → Get Contents of URL, as above) sends Strong's export without opening
Telegram. Strong has no Shortcuts actions, so its export always starts in the app.

`stg_health_workouts` keeps every record and flags what marts skip: `is_fragment` (under
3 min), `is_implausible_pace` (slower than 20 min/km), `is_duplicate` (same type within
10 min of a better record). `is_counted` is the rest.

## Marts

| Model | Grain | Use |
|---|---|---|
| `marts.mart_training_weekly` | ISO week (Monday, local time), empty weeks included | Sessions, sets, tonnage, cardio minutes and miles; `acute_chronic_ratio` on training minutes |
| `marts.mart_training_weekly_breakdown` | Week × movement pattern or cardio type | Where the volume went |
| `marts.mart_lift_progress` | Exercise × week trained | Best e1RM and change, best reps, last session's top set; `is_latest_week` |

A new exercise in Strong needs a row in `analytics/seeds/strong_exercises.csv`;
`dbt build` fails until it has one. Strong logs dumbbells per hand; the seed's
`implements` column (2 for most dumbbell lifts) makes tonnage count both. A pull up or dip
logged at 100 lb or more is read as bodyweight (`training_bodyweight_threshold_lb`).

## Planning context

`lab training context [--week 2026-W47]` (default: next week) writes
`var/training/context/<week>.json`: per day, free windows (gaps of 45 min or more,
05:00–21:00) and the weather with `outdoor_ok`.

One-time setup:

1. `lab google auth training`, then sign in and approve "See your calendars' free/busy"
   and "See the list of your calendars". The Calendar API must be enabled in the
   light-labs Google Cloud project.
2. In `.env`: `TRAINING_GOOGLE_ACCOUNT=<the address it printed>` and
   `TRAINING_CALENDARS=primary,Kelly family calendar`.
3. `lab google check training --account <address>` lists the calendars it can see.
4. `var/training/goals.md` has a `- Location: <lat>, <lon>` line for the forecast.

## Weekly plan

`lab training plan [--week 2026-W47]` (default: next week) refreshes the context, then
writes `var/training/plans/<week>.md`. Code sets the week number, deload and every lift's
load and reps; Claude (Sonnet) places the sessions in free windows and writes them up.
Failed checks (5 training days, slots inside free windows, outdoor runs in outdoor hours,
loads from the table) get one retry, then are listed at the bottom of the plan.

Until the work calendar is in `TRAINING_CALENDARS`, weekdays 08:00–17:00 count as busy;
set `TRAINING_ASSUME_WORK=` (empty) in `.env` once it is.

## Delivery

Rush's hourly tick runs `lab training tick`'s logic:

| When | What Rush does |
|---|---|
| Sunday 18:00–23:00 | Asks for any stale input (Strong over 6 days, Health over 36 h); sends next week's plan once a Strong export lands that day, or at 20:00 regardless |
| Daily from 21:00 | Asks for Health if the nightly Shortcut hasn't landed in 36 h |
| A file he asked for arrives | Refreshes the plan once Dagster loads it: next week whole, or this week's remaining days |
| `/replan` in chat, or `lab training replan` | Same refresh, now |
| `/plan`, `/plan next`, `/plan 2026-W47` in chat | Texts that week's stored plan (this week by default); never plans |

`lab training send [--week]` texts an existing plan. State: `var/training/deliver.json`.

The remote page's Training tab (`/training`, `/training/<week>`; tailnet only) renders any
week's plan, and a week's imported note where the lab has no plan. With `RUSH_REMOTE_URL`
set, every plan text ends with that week's link. A week runs Monday to Sunday, so on
Sunday evening the new plan is `/plan next`.
