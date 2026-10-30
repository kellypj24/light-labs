# Plan: SQLite as the robots' operational store

Status: approved with this PR; no phase started. Written 2026-10-30.

Robots keep their state in files under `var/`: one JSON per queue item (about 200 across
Rush and Roll), state and cursor files per robot, JSONL logs for mail, shadow labels,
pairs and gate verdicts, and `var/calibration/maps.json`. Each format has its own reader,
its own loader into DuckDB, and no transactions: a reader can catch a half-written file,
which is why `maps.json` is written with a rename. DuckDB can't take their place, since
it allows one writer and Dagster is that writer.

This plan moves the robots' state into one SQLite file, `var/lab.sqlite`, in WAL mode
(many readers next to one writer, nobody blocked). DuckDB stays the analytics database,
written only by Dagster, and reads the SQLite file through its `sqlite` extension.
Postgres is out (PJ, 2026-10-30): it needs a Docker VM running all the time on a laptop
that already hits memory pressure, and robots would fail whenever it is down. Revisit when
a second machine has to write.

Each phase is its own PR. Each lists the files it touches.

## What moves, what stays

| State | Today | Moves to |
|---|---|---|
| Approval queues | `var/<robot>/queue/{pending,sent,rejected}/*.json` | `queue_items` |
| Journals | `var/<robot>/journal.md` | `journal` |
| Robot state and cursors | `state.json`, `board.json`, `github.json`, `telegram.json`, `report.json`, `mail/*.state.json` | `robot_state` (robot, key, JSON value) |
| Rush mail log, disagreements | `var/rush/mail/*.jsonl` | `mail_items` |
| Roll keep shadow records, disagreements | `var/roll/keep/*.jsonl` | `keep_records` |
| Roll cleanup undo records | `var/roll/applied/*.json` | `applied_rules` |
| Shadow pairs | `var/<robot>/pairs/*.jsonl`, Roll's queue | `shadow_pairs` |
| Gate verdicts | `var/gate/verdicts.jsonl` | `gate_verdicts` |
| Calibration maps | `var/calibration/maps.json` | `calibration_maps`, written by Dagster's `calibration` asset |

Stays as files:
- `var/evals/`: the Go runner writes it, and `just eval` is outside the robots.
- `var/<robot>/escalations/*.md`: documents Auto and PJ read and edit.
- `.env` and `memory.md`: config and notes, edited by hand.
- `var/lab.duckdb` and `var/dagster/`.

## Phases

0. **Preconditions.** Before any code depends on them, on this laptop:
   - DuckDB's `sqlite` extension installs (`INSTALL sqlite`, a download the first time)
     and attaches a WAL file read-only while another process is writing to it.
   - The Python that `uv` installs allows `sqlite3` `enable_load_extension`, so
     `sqlite-vec` can load later.
   - Write throughput with `busy_timeout` set: Rush's tick, Roll's chores, the remote page
     and Dagster's reads at once.

   Record the results in this plan.
   Files: none.

1. **Store and schema, written twice.** `light_labs/core/opstore.py`: `connect()` sets
   `journal_mode=WAL`, `busy_timeout`, `foreign_keys`; schema migrations numbered by
   `PRAGMA user_version`. `Store` (`core/store.py`) writes each queue change and journal
   line to SQLite as well as to its files; files stay the source of truth. A parity check
   (`lab store check`) compares the two.
   Files: `light_labs/core/opstore.py`, `light_labs/core/store.py`, `light_labs/cli.py`,
   `tests/test_opstore.py`, `tests/test_store.py`.

2. **Queues read from SQLite.** One-time import of the existing queue files and journals.
   `Store` reads from SQLite; files are still written for a week as a fallback, then no
   more. Rush's remote page and `lab queue status` read SQLite.
   Files: `light_labs/core/store.py`, `light_labs/agents/rush/remote.py`,
   `light_labs/cli.py`, tests that build queue files by hand.

3. **The rest of the robots' state.** State and cursor files, the mail log, keep records,
   undo records, shadow pairs and gate verdicts, each behind its module's existing
   functions (`mail.Inbox`, `keep.shadow`, `gate.record`, `calibrate.collect`). The
   calibration maps move from `maps.json` to a table that Dagster writes and robots read;
   update the spec's Storage row in the same PR.
   Files: `light_labs/core/{gate,calibrate,calibration_results}.py`,
   `light_labs/agents/rush/{mail,board,github,telegram}.py`,
   `light_labs/agents/roll/{inbox,keep,chores}.py`.

4. **Dagster lands from SQLite.** Landing assets `ATTACH 'var/lab.sqlite' (TYPE sqlite,
   READ_ONLY)` and copy into `raw.*`; `queue_results.ingest` and
   `calibration_results.ingest`'s file readers go. `raw.*` table names and the dbt sources
   stay, so staging and marts don't change. The queue sensor fingerprints SQLite's data
   version instead of file mtimes.
   Files: `light_labs/orchestration/{assets,sensors}.py`,
   `light_labs/core/queue_results.py`, `light_labs/core/calibration_results.py`,
   `.claude/skills/dagster-orchestration/SKILL.md`.

5. **Backups.** `VACUUM INTO var/backups/lab-<date>.sqlite` once a day from a Dagster
   schedule, keeping 14. The files never had a backup; one SQLite file makes it a single
   command.
   Files: `light_labs/orchestration/`, `light_labs/core/opstore.py`.

6. **Vectors, when roll-keep's matcher needs them.** `sqlite-vec` in the same file, with
   embeddings from a small local model through Ollama, for roll-keep step 4b's nearest
   neighbours. Not before a matcher uses it.
   Files: `light_labs/core/opstore.py`, `light_labs/agents/roll/keep.py`.

## Decisions (PJ, 2026-10-30)

- SQLite in WAL mode for the robots' state; DuckDB stays analytics-only, written by
  Dagster.
- No Postgres; revisit when a second machine writes.
- Vectors through `sqlite-vec` in the same file, added with roll-keep's matcher.
- Calibration step 2b goes ahead on files (`var/roll/pairs/keep.jsonl`); phase 3 moves
  them.

## Open questions

1. Journals: one `journal` table read by Rush's remote page, or keep `journal.md`, which
   PJ reads by hand? Recommended: the table, plus `lab <robot> journal` to print it.
2. Retention for `mail_items` and `keep_records`, which hold subjects and snippets of real
   mail: delete after 90 days? Recommended: yes. Only disagreements turned into
   synthetic fixtures need to outlive that.
