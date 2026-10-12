# Boss fights

Each task class a robot does is a **stage**. A stage has fixtures (inputs plus what a good
output must do), and **contestants** fight it: Rock (the local model a robot runs on), Proto
Man (a challenger local model), Bass (the cloud baseline). When Rock gets close enough to
Bass at a fraction of the cost, he gets the weapon: the task class joins his `weapons` in
`dln.json` and that work stays local.

## Run

```bash
just eval                                  # reply-draft, rock, 3 samples per fixture
just eval reply-draft rock,proto,bass 3    # full fight
just eval reply-draft rock 3 -filter work  # one category (or fixture id substring)
```

Real models run **locally only**, one model at a time on a laptop (`-concurrency 1`, the
default). A full Rock run of reply-draft is 41 fixtures x 3 samples: about 10-15 minutes of
sustained GPU on an M1. Bass uses the `claude` CLI and costs subscription usage or API
spend; the report shows it.

Every sample is written to `var/evals/<stage>-<time>.jsonl` (draft, escalation, checks,
latency, cost) for later comparison.

## How it works

| Piece | Role |
|---|---|
| `stages/<stage>.yaml` | fixtures, plus stage `defaults` applied to every fixture (lists accumulate) |
| `stages/<stage>.memory.md` | synthetic robot memory the fixtures rely on |
| `contestants.yaml` | name, role and brain spec (`ollama:<tag>`, `claude:<model>`, `mock`) |
| Go runner (`main.go`, `runner.go`) | fans out contestant x fixture x sample, one subprocess each |
| `light_labs/evals/run_one.py` | runs one sample through the robot's **real** pipeline (the heartbeat's prompt builders, skills, cleaning and escalation parsing) and prints a JSON envelope |
| `scorer.go` | deterministic checks only: escalation, length, contains, must-not-contain/match |
| `report.go` | pass rates per contestant and category, latency, cost, failures |

Subprocess contract: `uv run python -m light_labs.evals.run_one --input-json '{...}'` prints
exactly one `{"ok", "result", "stats", "error"}` object, even on failure. Change both sides
together.

CI runs `gofmt`, `go vet`, `go test` and a smoke run against the `mock` contestant. The
smoke run checks the wiring and fails only if a sample could not run; the mock's scores
mean nothing.

## Stages

| Stage | Robot | Fixtures | Categories |
|---|---|---|---|
| `reply-draft` | Rush | 41 | chat, question, work, decision, identity, comment |

## Reading results

- **samples**: share of all samples passing every check. **fixtures**: share of fixtures
  where every sample passed (the stricter number).
- Local models are nondeterministic. Compare runs with the same `-samples`, and treat a
  difference of a fixture or two on a 41-fixture stage as noise.
- Bass without `ANTHROPIC_API_KEY` is marked "not isolated": the `claude` CLI then loads
  the user's global CLAUDE.md, so it is not a clean baseline in that mode.
- Not yet covered: a judge pass for what code can't check (tone, grounding). Add it only
  for checks the deterministic scorer can't express.

## Adding a stage or fixtures

Follow the `boss-fight` skill. Floor: 30 fixtures per stage before reading anything into
the numbers. The repo is public, so fixtures use synthetic names and content only.
