# System 1 and System 2: local first, frontier on escalation

Agreed with PJ 2026-10-30. Applies to every robot and every pipeline that can call a paid
model.

Kahneman's two systems, mapped onto the lab:

| | System 1: local (Ollama) | System 2: frontier (`claude:<model>`) |
|---|---|---|
| Speed, cost | Fast, free per call, always on | Slow, metered |
| Work | Classify, extract, match, route, redact, draft | New problems, ambiguous tradeoffs, hard reviews |
| Data | Sees everything | Sees what System 1 lets through |
| Invoked | By default | Only on escalation |

An escalation costs tokens and discloses context. Prompts sent to a provider can't be
recalled, so the design minimizes both: fewer calls, and less in each call.

## Escalation

System 1 escalates when:

- its answer is low confidence (`decide.ask` token probabilities, matcher distance);
- the input is unseen (new sender domain, new repo, new task kind);
- the label falls in a class with a weak record (from shadow data, revised as it grows);
- the answer doesn't parse;
- the stakes are high enough that a miss costs more than the call (lost keeps, merges).

The default payload is a sanitized, generalized sub-problem: the question with identifying
detail replaced by placeholders, built locally by `light_labs/core/sanitize.py` (written
for Roll, `docs/plans/roll-keep.md` step 4b).

## Full context: two gates

Full context goes to System 2 only when both pass:

1. **Sensitivity.** It reveals nothing sensitive, especially proprietary ideas. Fixed rules
   first, a local classifier later; a model judging its own leaks is the weakest gate.
   Never sent, by rule:
   - client data (recoup, dentasys-modernization) and anything from their repos;
   - personal mail senders and other people's systems (Agent Net, `memory.md`);
   - credentials (already redacted on ingest, #70);
   - unreleased ideas: design notes, plans and theses PJ hasn't published.
2. **Harness value.** What System 2 returns improves System 1's harness enough to be worth
   the disclosure: a rule, a matcher entry, a fixture, a routing change.

Fail either gate and the call goes sanitized, or not at all.

## Harness, not training

Model weights never change. System 2's answers feed System 1's harness, so the same case
stops escalating:

| Harness part | Fed by |
|---|---|
| Rules and guards | Repeated System 2 decisions that reduce to a condition |
| Matchers (domain tables, templates, nearest neighbours) | Labelled records |
| Prompts and `robots` skills | Patterns in System 2 critiques |
| Routing (which brain, which tier) | Agreement rates by class and tier |
| Eval fixtures | Disagreements, rewritten as synthetic (`keep-fixtures`, `chores-fixtures`) |

Read as an expert system:

| Expert system | Lab |
|---|---|
| Knowledge engineer | System 2, on escalation |
| Knowledge base | Rules, matchers, prompts, fixtures |
| Inference engine | Local model plus router |
| Domain expert | PJ |

Classic expert systems failed on two things: hand-built knowledge bases and brittleness
outside their rules. System 2 removes the hand-building. Brittleness is caught only by
measuring escalation.

## Measuring escalation

Each robot that escalates gets an eval stage scored on escalate vs handle, where the costly
miss is a case it should have escalated and didn't. A confidently wrong System 1 never
escalates, so this rate matters more than its accuracy on the cases it does escalate.
Fixtures come from shadow runs: System 1 and System 2 answer the same input, and the
disagreements System 1 was confident on become the hard cases.

## Enforcement

Gate 1 is code, not discipline: every `claude:` call passes through one gate in
`light_labs/core`, and a test fails when anything reaches Claude around it. A Claude call
with repo tools reads files the gate never sees, so tool access is limited to repos on an
allowlist. Being built: `docs/plans/decision-framework.md`, step 1.

## Decision framework

Our own framework on `light_labs/core/decide.py`, modelled on TypeSafe's Jev (typed
decisions with calibrated probabilities; mastra.ai/articles/jev). Nothing calls Jev.
Questions are typed (choice, yes/no, score), answers carry calibrated confidence, and
routing rules are conditions over named answers. Being built:
`docs/plans/decision-framework.md`.

### Storage (PJ, 2026-10-30)

Authored rules in files, derived data in DuckDB:

| What | Where | Why |
|---|---|---|
| Routing rules | `rules/<robot>.yaml`, read by robots at runtime from the deployed release | PR review, git history, CI tests; no DuckDB lock on Rush's hourly tick |
| Rules, queryable | dbt seed of the YAML, loaded by Dagster | Joins with decision records |
| Rule hits | Each decision record names the rule that fired | Marts give hit rate, agreement with Claude and missed escalations per rule |
| Rule proposals from System 2 | DuckDB table, written through Dagster; a command turns accepted ones into a PR against the YAML | Fast capture, reviewed adoption |
| Calibration maps | Dagster asset in DuckDB, read-only by robots | Fitted from records, rebuildable |

## Where the lab stands

| Pipeline | State |
|---|---|
| Roll `mail-keep` | Local labels; sanitized escalation in progress (step 4b) |
| Roll chores | Inverted for now: Claude decides every PR, Roll's answer is shadow. Roll takes over per tier once she earns the `dependabot-merge` weapon |
| Rush triage | Escalations drafted by Auto, approved by PJ |

## Open

Open questions on the build live in `docs/plans/decision-framework.md`.
