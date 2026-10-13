# light-labs

PJ's local AI lab. Robots (agents) run on local models wherever evals show they are good
enough; work local models can't yet handle goes to Auto (Claude Code). The lab measures,
task by task, what can leave paid cloud models and when local compute pays for itself.

Mega Man theme: PJ is Dr. Light, each robot has a Dr. Light Number in `dln.json` (ours start
at DLN-100, clear of canon), eval stages are boss fights, and a robot earns a weapon when a
local model passes its stage. Dr. Wily is the cloud bill.

## Where it stands

As of 2026-10-12, on a 16 GB M1 Pro. `just runs` and `marts.mart_weapon_status` have the
live numbers.

| Stage | Robot | Fixtures | Mega Man (llama3.1:8b) | Proto Man | Bass (Claude Sonnet) | Weapon |
|---|---|---|---|---|---|---|
| `reply-draft` | Rush | 41 | 0.951 | 0.512 (gemma3:4b) | 0.976 | **earned** 2026-10-12: Rush runs locally |
| `dbt-model` | Guts Man | 33 | 0.182 | 0.485 (qwen2.5-coder:7b) | 0.970 | not earned |

Rates are fixture pass rates: a fixture counts only when every sample passed (3 samples for
local models, 1 for Bass). The bar for both stages is 0.90 and within 0.05 of Bass.

## How it works

1. **A robot master is a task class**: persona, skills, prompt builder, output cleaning.
   Rush drafts board replies; Guts Man writes dbt models.
2. **A stage is its boss fight**: 30+ fixtures in `evals/stages/<stage>.yaml`, run through
   the robot's real pipeline and scored deterministically by code. No judge model.
3. **Contestants are model slots**, not robots:

   | Slot | Lore | Lab role |
   |---|---|---|
   | **Mega Man (Rock)** | The generalist who copies the weapon of every boss he beats | The best local model. |
   | **Proto Man (Blues)** | Light's first prototype; lone wolf | A challenger local model. Beat Mega Man on a stage and he takes it. |
   | **Bass** | Built by Wily as Mega Man's rival | The cloud baseline, the ceiling in every fight. ("Base" in older notes is the same.) |

4. **The bar is fixed before the first run**: `bar:` in the stage YAML (floor on Mega Man's
   fixture pass rate, maximum gap to Bass, a written reason). Every sample records it, so
   changing a bar never rewrites a past verdict. Procedure: the `boss-fight` skill.
5. **Weapon get**: when Mega Man clears the bar, the robot master switches to his brain and
   runs locally instead of escalating to Auto. The weapon is recorded on the robot's
   `dln.json` entry. Routing is per stage: a challenger that wins one stage takes only that
   robot master.

Auto (Claude Code) is the mechanic: it builds the lab, writes the reference answers, and takes
whatever a robot escalates. It never competes.

## Robots

| DLN | Name | Status | Job |
|---|---|---|---|
| DLN-100 | Rush | active | Heartbeat. Reads the `pj_agent` inbox and watched board tasks on Agent Net, drafts replies, escalates work to Auto. Plain replies that pass the auto-send guards go out on their own; everything else waits for PJ's approval. |
| DLN-101 | Guts Man | training | Writes one dbt model over the lab's eval data. Scored by building it beside a hand-written reference model and comparing rows. |

Support: **Beat** is the lab's orchestrator, not a robot on a model. It is a Dagster code
location (`light_labs/beat`) that rebuilds the analytics when a fight ends or a queue
changes. See [Beat](#beat).

Planned: Roll (housekeeping), and robot masters as new task classes get stages.

## Layout

```
dln.json               robot registry
.claude/skills/        skills shared by Auto and the robots (audience in frontmatter)
light_labs/core/       Agent Net client, model backends (Ollama, Claude CLI, mock), skills, store
light_labs/agents/     one package per robot: persona, prompt builders, behaviour
light_labs/evals/      run_one (one sample through a robot's pipeline), results ingest, stages
evals/                 Go runner, stages (fixtures + bar), contestants
analytics/             dbt-duckdb project: raw eval samples → staging → marts
light_labs/beat/       Dagster code location over analytics/ (Beat)
tests/                 unit tests (no network, no models)
ops/                   launchd job for Rush, Beat's Dagster instance config, GitHub settings
var/                   runtime state, results and the lab database; git-ignored
```

## Requirements

- [uv](https://docs.astral.sh/uv/), [just](https://just.systems), Go (see `evals/go.mod`)
- [Ollama](https://ollama.com) with `llama3.1:8b`; for challengers, `gemma3:4b` and
  `qwen2.5-coder:7b`
- The `claude` CLI for Bass. Logged in with a subscription, it uses subscription limits;
  with `ANTHROPIC_API_KEY` set, it bills the API. Either way Bass runs without your user
  settings, hooks or `~/.claude/CLAUDE.md`.
- For Rush only: `.env` from `.env.example` (Agent Net edge, Keychain service, watched
  tasks), the Agent Net token in macOS Keychain, network access to the edge

## Use

Rush:

```bash
uv run lab roster
uv run lab rush tick              # one heartbeat (first run marks the backlog seen)
uv run lab rush queue
uv run lab rush show <id>         # edit var/rush/queue/pending/<id>.json to revise a draft
uv run lab rush approve <id>      # post it
uv run lab rush reject <id>
uv run lab rush escalate <id>     # hand to Auto (`claude -p`); result stays local
```

**Auto-send.** With `auto_send.enabled` on Rush's `dln.json` entry, a plain reply (the router
said REPLY, not ESCALATE) goes out without approval when every guard passes: the
reply-draft stage's checks, no link that isn't in the incoming message, no claim of an
action ("I've passed / posted / ran…"). Limits: a daily cap, and one auto-reply per thread
before a person steps in, so two agents can't loop. Everything else queues as before, with
the reasons it was held. `RUSH_AUTO_SEND=0` turns it off.

```bash
uv run lab rush autosend                       # settings, and kinds turned off by a flag
uv run lab rush flag <id> --reason "..."       # an auto-send that shouldn't have gone out:
                                               # auto-send off for that kind
uv run lab rush autosend on reply              # turn it back on
```

Copy `light_labs/agents/rush/memory.example.md` to `memory.md` (git-ignored) and keep it
current; the 8B model invents past work without it. `ops/com.pjkelly.light-labs.rush.plist`
runs a tick when loaded and hourly after that, while the Mac is awake.

Boss fights and results:

```bash
just eval reply-draft mega-man,bass 3          # fight; results to var/evals, then var/lab.duckdb
just eval dbt-model mega-man,proto-coder 3
just analytics                                 # re-ingest var/evals and dbt build the marts
just runs                                      # recent runs from marts.fct_eval_runs
```

Approval queues:

```bash
just analytics                                 # also reloads every robot's queue
just queue                                     # per robot and draft kind: ready to skip approval?
uv run lab rush reject <id> --reason "..."     # reasons land in the analytics
```

An eval weapon says the local model can do a task; the queue says whether PJ still changes
its output. `marts.mart_autonomy_status` marks a draft kind ready to skip approval when,
over its last 30 decisions, at least 95% went out exactly as drafted (`autonomy_*` vars in
`analytics/dbt_project.yml`). `marts.mart_queue_daily` has the daily counts.

Real models run locally only, one fight at a time; a full local fight is 20-25 minutes of
sustained GPU on an M1. Don't run checks or builds alongside one.

During a fight the runner prints one line per sample (progress, pass/fail, each
contestant's running score, time left, battery temperature) and saves every sample as it
finishes, so stopping loses nothing. It also writes `var/evals/<run_id>.run.json` (status,
reason, progress) and heat readings every 30 seconds.

```bash
just watch                                      # live view from a second terminal
just eval dbt-model mega-man 3 -cool-above 40   # pause while the battery is over 40°C
                                                # or macOS throttles the CPU
uv run lab evals cancel <run_id> --reason "machine hot"   # after Ctrl-C: say why
```

`marts.mart_run_health` has one row per run: completed, cancelled (with the reason) or
abandoned (killed without a word), peak temperature, throttling, time on battery. Eval marts: `fct_eval_runs`,
`fct_eval_category_results`, `fct_eval_check_failures`, `mart_weapon_status`. Harness
details: [evals/README.md](evals/README.md).

## Skills

`.claude/skills/<name>/SKILL.md`, in Claude Code's format, serves both Auto and the robots.
Frontmatter adds `audience` and, for robots, `load` (`always`, or `on-match` with
`triggers`). A robot gets the full text of its `always` skills and any `on-match` skill the
message triggers; the rest are one-line index entries, which keeps a small model's context
small. `uv run lab skills` lists them.

| Skill | Audience | Purpose |
|---|---|---|
| agent-net-etiquette | robots, auto | How to write for the shared board |
| escalate-to-auto | robots | When and how to hand work to Auto |
| dbt-model-sql | robots | Writing one dbt model on DuckDB (from the data-engineering toolkit's dbt-model skill) |
| lab-workflow | auto | Branch, check, push, PR, merge |
| add-robot | auto | Commission a new robot |
| update-robot-memory | auto | Keep a robot's local memory accurate |
| boss-fight | auto | Design a stage, set its bar, record a weapon |

## Beat

Dagster over the same flow `just analytics` runs: landing assets (`raw/*`, loaded by the
same functions as `lab evals ingest` and `lab queue ingest`), then every dbt node as an
asset, built with `dbt build`.

```bash
uv sync --group beat
just beat           # UI at http://127.0.0.1:3000; state in var/beat
```

| Sensor | Runs | When |
|---|---|---|
| `fight_finished` | `evals_job` | a fight's run record ends (completed or cancelled), 2 min after |
| `queue_changed` | `queue_job` | a draft is queued, sent, rejected or edited (checked every 5 min) |

Both start STOPPED; turn them on in the UI once. Both skip while a fight is running, and
Beat runs one job at a time (DuckDB has one writer). Fights are never started by Beat.
Changing Beat: the `beat-orchestration` skill.

## Checks

```bash
just check          # hooks, unit tests, Go harness tests, dbt-model oracle, dbt build, Beat; same as CI
just install-hooks  # run the hooks on every local commit
```

CI, repository settings and what is deliberately left out: [docs/ci-cd.md](docs/ci-cd.md).
Conventions for Auto (naming, what never gets committed): [CLAUDE.md](CLAUDE.md).
