# light-labs

PJ's local AI lab. Robots (agents) run on local models wherever evals show they are good
enough; work that local models can't yet handle goes to Auto (Claude Code). The point is to
measure, task by task, what can leave paid cloud models and when local compute pays for itself.

Mega Man theme: PJ is Dr. Light, each robot has a Dr. Light Number in `dln.json` (ours start
at DLN-100 to stay clear of canon), eval suites are boss fights, and a robot earns a weapon
when its local model passes a task class. Dr. Wily is the cloud bill.

## Layout

```
dln.json               robot registry
light_labs/core/       Agent Net client, Ollama backend, per-robot store (queue, journal, state)
light_labs/agents/     one package per robot: config, persona, memory, behaviour
evals/                 boss fights: Go runner, stages (fixtures), contestants
analytics/             dbt-duckdb project over the eval results (raw → staging → marts)
ops/                   launchd jobs
var/<robot>/           runtime state, git-ignored
```

## The eval loop: Mega Man, Proto Man and Bass

Three roles run every boss fight:

| Robot | Lore | Lab role |
|---|---|---|
| **Mega Man (Rock)** | The generalist who copies the weapon of every boss he beats | **The local generalist.** The best local model, working through the routing table. Each weapon he holds is a task class a local model has proven it can do. He is the robot who shrinks the cloud bill. |
| **Proto Man (Blues)** | Light's first prototype: unstable core, lone wolf, whistles before he appears | **The challenger.** Runs the next candidate model on the same tasks in shadow. Beat Mega Man on the evals and he takes the slot. |
| **Bass** | Built by Wily as Mega Man's rival | **The cloud baseline.** Claude or GPT on the same fixtures, the ceiling in every fight. Mega Man clears a stage when he gets close enough to Bass at a fraction of the cost. |

Mega Man, Proto Man and Bass are model slots (local best, local challenger, cloud). A robot
master is a task class: its persona, skills, prompt and stage. When Mega Man clears a robot
master's stage he gets its weapon: that robot master switches to his brain and runs locally
instead of escalating to Auto. You still invoke the robot master; the weapon is recorded
on its `dln.json` entry (stage, brain, run_id). Routing is per stage, so a challenger that
wins one stage takes only that robot master.

"Close enough" is a per-stage bar fixed before the first run: a floor on Mega Man's fixture
pass rate and a maximum gap to Bass, with a written reason (`bar:` in each
`evals/stages/<stage>.yaml`; procedure in the `boss-fight` skill). Bass is the canon
spelling; "Base" in older notes and call transcripts means the same cloud baseline.

Mega Man fights each stage against Bass, Proto Man keeps trying to take Mega Man's place, and every
cleared stage is a task Wily no longer bills for. Auto (Claude Code) is separate: the mechanic
who builds, not a competitor.

## Robots

| DLN | Name | Role |
|---|---|---|
| DLN-100 | Rush | Heartbeat. Reads the `pj_agent` inbox and watched board tasks, drafts replies into an approval queue, escalates to Auto. |
| DLN-101 | Guts Man | In training on the `dbt-model` stage (`evals/stages/dbt-model.yaml`): writes one dbt model over the lab's eval data, scored by building it and matching a reference model's rows. Dr. Light's construction robot: lifts and places blocks. |

Planned: Mega Man, Proto Man and Bass for the eval loop above; Beat (watcher), Roll
(housekeeping) and robot masters as task classes earn them.

## Use

```bash
uv run lab roster
uv run lab rush tick              # one heartbeat (first run marks the backlog seen)
uv run lab rush tick --backfill   # first run only: draft for the existing backlog too
uv run lab rush queue
uv run lab rush show <id>         # edit var/rush/queue/pending/<id>.json to revise a draft
uv run lab rush approve <id>      # post it
uv run lab rush reject <id>
uv run lab rush escalate <id>     # hand to Auto (`claude -p`); result stays local
```

Eval results:

```bash
just eval reply-draft mega-man 3   # fight; results land in var/evals, then var/lab.duckdb
just analytics                    # re-ingest var/evals and dbt build the marts
just runs                         # recent runs from marts.fct_eval_runs
```

`marts.mart_weapon_status` says whether Mega Man has earned each stage's weapon: his
latest full run against Bass's, thresholds in `analytics/dbt_project.yml`.

Rush posts nothing without `approve`. Copy `light_labs/agents/rush/memory.example.md` to
`memory.md` (git-ignored) and keep it current; the 8B model invents past work without it.

## Requirements

- `.env` from `.env.example`: Agent Net edge URL, Keychain service, watched tasks
- Ollama with `llama3.1:8b` (or set `RUSH_MODEL`)
- Agent Net token in macOS Keychain under that service name
- Network access to the Agent Net edge (here, over Tailscale)

## Schedule

`ops/com.pjkelly.light-labs.rush.plist` runs `lab rush tick` hourly via launchd while the Mac
is awake. Not installed by default.

## Skills

`.claude/skills/<name>/SKILL.md`, in Claude Code's format, serves both Auto and the robots.
Frontmatter adds `audience` (`auto`, `robots`, or both) and, for robots, `load` (`always`,
or `on-match` with `triggers`). A robot gets the full text of its `always` skills and of any
`on-match` skill the message triggers; the rest appear as one-line index entries, which keeps
a small model's context small. `uv run lab skills` lists them.

| Skill | Audience | Purpose |
|---|---|---|
| agent-net-etiquette | robots, auto | How to write for the shared board |
| escalate-to-auto | robots | When and how to hand work to Auto |
| lab-workflow | auto | Branch, check, push, PR, merge |
| add-robot | auto | Commission a new robot |
| update-robot-memory | auto | Keep a robot's local memory accurate |
| boss-fight | auto | Design an eval stage |

## Checks

```bash
just check          # pre-commit hooks, unit tests and eval-harness checks, same as CI
just eval           # boss fight with real local models (see evals/README.md)
just install-hooks  # run the hooks on every local commit
```

CI, repository settings and what is deliberately left out: [docs/ci-cd.md](docs/ci-cd.md).
