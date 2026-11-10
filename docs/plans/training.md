# Plan: training logs and weekly workout planning

Status: agreed 2026-11-08. Steps 1–5 done (#110, #112–#116); step 6 in review. Written 2026-11-08.

Moves the exercise-planning task from Claude desktop into the lab. Strong (lifting) and
Strava (cardio, through Apple Health) logs flow through Dagster into `var/lab.duckdb`; marts summarise load and
progress; a planner drafts next week's sessions from the marts and PJ's goals. Each step
is its own PR. Each step lists the files it touches; a change to those files on `main`
before the step starts means re-reading the step.

## Sources

| Source | Access | Effort | Data |
|---|---|---|---|
| Strong | No API, and no Shortcuts actions (checked 2026-11-08). CSV export from the app, shared to Rush on Telegram | ~5 taps a week | Every set: exercise, weight, reps, RPE, notes |
| Strava → Apple Health | Strava writes runs and rides to Health; the Health Exporter & Shortcuts app ($2.99) exports workouts as JSON in a Shortcut, sent to Rush on Telegram. Strava's API is subscriber-only (checked 2026-11-09) | None once the automation runs | Workouts: type, start, end, duration, indoor, source, distance, calories, HR when the Watch recorded it |

Strong exports the full history every time, so each drop is a complete snapshot: the
newest file replaces `raw.strong_sets`, and older files are archived, not merged. A lost
or skipped week costs nothing.

## Steps

1. **Strong drop and landing.**
   - Phone: Strong → Export Data → share sheet → Telegram → Rush's chat. No Shortcut
     for the drop; a Shortcuts personal automation only fires the weekly reminder.
     Setup steps go in `docs/training.md`; nothing on the phone is in the repo.
     (iCloud Drive was dropped 2026-11-08: PJ doesn't sync iCloud Drive to this Mac.)
   - Rush: `Telegram.handle` takes a `document` message from PJ's chat, fetches it with
     `getFile` (bot limit 20 MB), checks the header against `strong.py`'s pinned header,
     and writes it to `var/training/strong/inbox/strong-<yyyy-mm-dd>.csv`. It replies
     "Got N sets, <first>–<last>" or "Not a Strong export: <reason>". Rush only lands
     the file; Dagster ingests it. Telegram keeps updates for a day, so a drop sent while
     the Mac sleeps longer than that is lost: no reply means send it again.
   - Mac: `light_labs/training/strong.py` moves inbox files to `var/training/strong/` and
     loads the newest into `raw.strong_sets` (snapshot replace, `source_file` and
     `exported_on` columns). Strong's layout differs across versions and between iOS and
     Android, and weights have no unit column. The parser pins the expected header,
     refuses unknown columns and Set Order values instead of guessing, and takes the
     unit from `UNIT` (lb). Rest-timer rows are dropped; a letter in Set Order (W, D, F)
     becomes `set_type`, and `set_number` is the position within the exercise.
   - Dagster: `raw/strong_sets` asset, and a sensor `strong_dropped` on the inbox
     fingerprint (as `queue_fingerprint`), skipping during a fight or heavy job.
   - CLI: `lab training ingest-strong [<csv>]`.
   - dbt: `stg_strong_sets` (the repo's `stg_<table>` naming), one row per set with a
     stable `set_id` (hash of date, workout, exercise, set position).
   - Test: fixture CSV from a real export with values replaced.
   Files: `light_labs/training/{__init__,strong}.py`, `light_labs/agents/rush/telegram.py`, `light_labs/orchestration/{assets,jobs,sensors}.py`,
   `light_labs/cli.py`, `analytics/models/staging/{_sources.yml,stg_strong_sets.{sql,yml}}`,
   `tests/test_training_strong.py`, `tests/test_telegram.py`, `tests/test_orchestration.py`, `docs/training.md`.

2. **Health workouts landing.**
   - Phone: a Shortcut runs Health Exporter & Shortcuts' Export Workouts (last 7 days;
     the action offers 7 or 30) and posts the JSON to Rush's remote page,
     `POST /drop/health` over the tailnet, daily at 21:00 by personal automation.
     Telegram's Shortcuts action can't message a bot. Setup in `docs/training.md`.
   - Rush: `training.drops.land` checks the data with `training.health.parse` and saves
     it to `var/training/health/inbox/health-<yyyy-mm-dd-hhmmss>.json`; every drop is
     kept, since each covers a window. The same function serves Telegram drops and
     `POST /drop/strong`.
   - `light_labs/training/health.py`: moves drops to `var/training/health/` and upserts
     `raw.health_workouts` by HealthKit uuid. Statistics are kept whole as JSON beside
     distance (metres), calories and heart rate.
   - Dagster: `raw/health_workouts` asset, sensor `health_dropped` on the inbox.
   - dbt: `stg_health_workouts`, with `is_fragment` (under 3 min), `is_implausible_pace`
     (slower than 20 min/km: a recording that ran on for a day), `is_duplicate` (same
     type within 10 min; keep the record with HR, then plausible pace, then shorter) and
     `is_counted`. All three occur in PJ's first 30 days of runs.
   - CLI: `lab training ingest-health [<json>...]`.
   Files: `light_labs/training/health.py`, `light_labs/agents/rush/telegram.py`,
   `light_labs/orchestration/{assets,jobs,sensors}.py`, `light_labs/cli.py`,
   `analytics/models/staging/*health*`, `tests/test_training_health.py`.

3. **Marts.**
   - Seed `seeds/strong_exercises.csv`: exercise → movement pattern (squat, hinge, lunge,
     horizontal/vertical push and pull, power, arms, shoulders, calves) and
     `is_bodyweight_lift`. A `not_null` test on `int_training_sets.movement_pattern`
     fails when Strong logs an exercise the seed lacks.
   - `int_training_sets`: pattern, added weight, tonnage, Epley e1RM. Strong logs dumbbells
     per hand; the seed's `implements` (2 for most dumbbell lifts) makes tonnage count
     both. A bodyweight lift logged at 100 lb or more logged PJ's
     bodyweight: 0 added weight, no tonnage, progress on reps. e1RM only from loaded,
     non-bodyweight sets of 1–10 reps.
   - `int_training_sessions`: Strong workouts and counted Health workouts (not strength
     types, which Strong covers) as one session grain, local time (America/New_York).
   - `mart_training_weekly`: one row per ISO week from the first session to this week,
     empty weeks included: sessions, sets, tonnage, cardio minutes and miles, and
     acute:chronic load on training minutes (no RPE is logged; HR is sparse), as of the
     week's last day or today.
   - `mart_training_weekly_breakdown`: per week, sets and tonnage by movement pattern and
     minutes and miles by cardio type.
   - `mart_lift_progress`: per exercise and week, best e1RM and its change, best reps,
     and the top set of the week's last session; `is_latest_week` is where progression
     starts.
   - Vars in `dbt_project.yml`: bodyweight threshold, e1RM rep cap, strength activity
     types, timezone.
   Files: `analytics/seeds/strong_exercises.csv`, `analytics/models/{intermediate,marts}/*training*`,
   `analytics/models/marts/mart_lift_progress.*`, `analytics/dbt_project.yml`.

4. **Context: calendar, weather, history.** Computed when the planner runs and written
   to `var/training/context/<yyyy>-W<ww>.json` (`lab training context [--week]`), never
   stored in DuckDB.
   - Calendar: one Google free/busy query over the calendars named in
     `TRAINING_CALENDARS` (`.env`; `primary` plus "Kelly family calendar", the iCloud
     family calendar PJ already subscribes to in Google Calendar). The `training`
     sign-in has `calendar.freebusy` and `calendar.calendarlist.readonly` only: busy
     blocks and calendar names, never an event's title, so other people's events reach
     the lab only as busy time. Google refreshes a subscribed calendar every 8–24 h,
     which is enough for a week ahead. Free windows are gaps of 45 min or more between
     05:00 and 21:00 local.
   - Weather: api.weather.gov grid data for the `- Location:` line in `goals.md`. Per
     day: daytime (07–19) minimum and maximum, wind chill and precipitation chance, the
     low, and `outdoor_windows`: the daytime hours with air ≥ 38°F, wind chill ≥ 32°F
     and not ≥ 50% precip at ≤ 34°F (PJ's limits in `goals.md`). `outdoor_ok` when
     there is at least one. Days past the forecast are null.
   - History: the desktop task's only note, week 1, copied once from Drive ("Claude task
     log") to `var/training/history/2026-W46.md`. No code.
   Files: `light_labs/core/google.py`, `light_labs/training/{calendar,weather,context}.py`,
   `light_labs/cli.py`, `tests/test_training_context.py`.

5. **Planner.** `lab training plan [--week]` (default: next week) writes
   `var/training/plans/<yyyy>-W<ww>.md` and the model's JSON beside it.
   - Code owns the numbers: week number and deload from `goals.md` (week 1 = 2026-11-09,
     every 4th a deload) or acute:chronic above 1.3; every lift's load and reps. A lift
     keeps the rep scheme PJ trains (the more reps of its last two weekly top sets);
     reaching it adds 5 lb (barbell) or 2.5 lb per hand (dumbbell), falling short repeats
     the load, bodyweight lifts add a rep, a deload takes 90%. Lifts not trained in 12
     weeks are left out.
   - Claude (`claude:sonnet`, gate source `training/plan`, recorded, not denied) gets
     goals.md, the step 4 context, the progression table, six weeks of load and the last
     plan, and returns JSON: days, slots, sessions, items, one line of why.
   - Checks in code: all 7 dates, exactly 5 training days, every slot inside a free
     window, every outdoor run inside that day's outdoor hours, table lifts at the
     table's load and reps. One retry with the failures, then the plan is written with
     them listed.
   - Until the work calendar is shared into `TRAINING_CALENDARS`, weekdays 08:00–17:00
     count as busy (`TRAINING_ASSUME_WORK`; empty turns it off).
   - First run (2026-W47): passed every check on the first reply, ~30 s.
   Files: `light_labs/training/plan.py`, `light_labs/core/gate.py`, `light_labs/cli.py`,
   `tests/test_training_plan.py`, seed `implements`, `int_training_sets`.

6. **Delivery.** `training/deliver.py`, run by Rush's hourly tick (before the board, so an
   unreachable Agent Net never holds the plan), state in `var/training/deliver.json`.
   - Sunday from 18:00: Strong is stale past 6 days, Health past 36 h; Rush texts how to
     send each stale one. Next week's plan goes out once a Strong export lands that day,
     or at 20:00 with what there is, saying what it was built without. Planner errors are
     texted and retried hourly until 23:00.
   - Daily from 21:00: Rush asks for Health when it is stale.
   - A requested file (Telegram or the tailnet drop) refreshes the plan once Dagster has
     loaded it: next week whole before it starts, else the current week's remaining days
     (`plan.run(from_date=...)`, training days owed = 5 minus days logged). Unrequested
     drops never re-plan. `/replan` refreshes on demand.
   - Plain text in Rush's chat, split between days under Telegram's 4,096-character
     limit. `lab training send [--week]` and `lab training tick` by hand.
   - Calendar events come later and need a `calendar.events` scope, asked first. The
     desktop task keeps running until two lab plans in a row pass PJ's review.
   Files: `light_labs/training/{deliver,plan}.py`, `light_labs/agents/rush/telegram.py`,
   `light_labs/cli.py`, `tests/test_training_deliver.py`, `tests/test_telegram.py`.

## Decided (2026-11-08)

- Weights in lb.
- Goals and constraints live in `var/training/goals.md`, not committed, seeded from the
  desktop task. The task's Drive-memory and tool-call instructions are replaced by steps
  1–4.
- Planner brain: Claude (Sonnet) through `ClaudeCLI`, new gate source `training`. It
  sees PJ's logs, free/busy windows and weather, never event titles. A local model gets
  a boss fight once 8+ weeks of plans PJ edited exist to score against.
- Gate rule: training data is allowed (record only). The family calendar reaches the gate
  only as free/busy.
- A module (`light_labs/training`), not a robot. Rush delivers. A robot comes when a local
  model earns the planner weapon (`add-robot`).
- IC4 rides are logged on Strava, which writes them to Health. No ride yet (2026-11-09):
  the first one shows its `activityType` and `indoor`, and the plan adapts then. Bag rounds are to be
  logged in Strong as custom exercises (duration, rounds); none are in the 2026-11-08
  export, which has no timed sets at all. The seed in step 3 maps those to
  `conditioning`.
- Strong export reminder Sunday 18:00. The plan is generated when the drop lands, with a
  fallback at Sunday 20:00 without it.
- Cardio comes from Apple Health, not Strava's API (subscriber-only). Health Auto Export
  or a personal HealthKit app only if HR or other detail turns out to matter.
- Apple Health is the cardio source (step 2). Strong also writes its sessions there
  (no sets); lifting still comes from Strong's CSV.
- Strong drop goes to Rush on Telegram, not iCloud Drive.

## Open decisions

None.
