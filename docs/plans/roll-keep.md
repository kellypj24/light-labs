# Plan: Roll learns what to keep (`mail-keep` stage)

Status: step 1 done 2026-10-26 (21,029 Roll/Promotions restored from Trash); step 2 done 2026-10-26
(`mail-keep` stage, 49 fixtures, `light_labs/agents/roll/keep.py`); step 3 done (qwen2.5:14b earned the
weapon, run mail-keep-20261026T180251Z); step 4 done (every `Roll/*` label shadow-labelled); step 4b in progress (sanitized view and
sanitized `keep-fixtures` in `light_labs/agents/roll/sanitize.py`; matchers, escalation and
the name pass of the scrubber to come). Written 2026-10-19.

Roll's cleanup rules today are Gmail searches by category and age (`roll/inbox.py`). They
moved 50k emails out of the inbox and into `Roll/*` labels, but deciding what can be
deleted needs more than a search. This plan gives Roll a model-backed stage that tags
mail worth keeping, so deletion becomes "old and not kept" instead of a growing list of
keyword exclusions.

## Why searches are not enough (2026-10-19)

Deleting Updates older than a year with a hand-built Gmail search failed three ways:

| Failure | Example |
|---|---|
| Category is too coarse | Updates holds invoices, receipts, security alerts, school notices, insurance, 401(k) disclosures and pediatric visit notes next to recruiter spam |
| Keyword exclusions leak | Chase activation and sign-in notices, Experian/FICO alerts, Amazon orders, "No School Reminder" all passed `-subject:(...)` filters |
| Search syntax is fragile | One `401(K)` term closed a group early; the exclusions silently became matches |

Each fix was another sender or word. The mail-triage stage already showed that a local
model with sender, subject, category and snippet can sort mail; this applies the same
idea to retention.

## Labels

Keep classes (Gmail labels `Roll/Keep/<class>`):

| Class | Covers |
|---|---|
| `finance` | bank, card, credit bureau, brokerage, retirement, payment notices |
| `security` | sign-in alerts, password and 2FA changes, account recovery |
| `receipts` | orders, invoices, shipping, subscriptions started or cancelled |
| `school` | schools, childcare, district, bus and PTA notices |
| `health` | providers, visit notes, results, pharmacy |
| `insurance` | policies, claims, benefits enrollment |
| `legal-tax` | tax forms, government, contracts, terms PJ signed |
| `people` | a real person wrote to PJ |

Discard classes (`Roll/Discard/<class>`): `promotion`, `newsletter`, `job-alert`
(recruiters, job boards), `notification` (social, Strava, app nags), `marketing` (vendor
announcements, pricing, ToS blasts).

One label per message. The output is `keep/<class>` or `discard/<class>`.

## Stage: `mail-keep`

`evals/stages/mail-keep.yaml`, robot Roll, scored like mail-triage (`Expect.label`).

- Fixtures: at least 40 synthetic emails (example.org senders, invented people), at least
  3 per class. Seed them from the 2026-10-19 misses rewritten as synthetic: card
  activation, credit score change, order shipped, no-school day, district newsletter,
  401(k) disclosure, pediatric visit notes, insurance wellness reminder, recruiter blast,
  job-board saved search, vendor pricing change, Strava kudos.
- Hard cases, scored per category: keep-mail written in marketing style (a bank promo
  that also states a balance), discard-mail using keep words ("order now", "security
  tips"), school newsletters vs one-off school notices.
- Bar, fixed before the first run: `min_fixture_rate: 0.90`, `max_gap: 0.05`. The costly
  error is a keep labelled discard; the report breaks that rate out, and the weapon also
  requires zero keep-to-discard misses on the `finance`, `security` and `health` fixtures.
- Contestants: mega-man (`qwen2.5:14b`, Rush's mail model), proto, bass. Real mail never
  goes to Bass.
- Pipeline: reuse `rush/mail.py` `prompt()` and the two-call shape that fixed mail-triage
  (classify one word, then nothing else; no summary needed here).

## Steps

Each step is its own PR.

1. **Rescue the trashed Promotions.** Done 2026-10-26. `lab roll untrash --label <label>`
   removes `TRASH` through Roll's existing `relabel` (batchModify), so mail returns to the
   archive, not the inbox, and `google.py` gained no trash call; `relabel` now refuses to
   add `TRASH` or `SPAM`. Ran on `Roll/Promotions`: 21,029 restored, ids in
   `var/roll/applied/untrash-*.json`.
2. **Stage and fixtures.** `mail-keep.yaml`, `run_one` wiring for Roll, mock contestant
   in CI. Update `evals/README.md`'s stage table and Roll's `dln.json` entry (its `job`
   still describes only commit messages and branch triage).
3. **Fight.** `just eval mail-keep mega-man,proto,bass 3 -cool-above 40`, one model at a
   time. Ask PJ before starting; estimate from mail-triage (about 4 minutes per local model).
4. **Shadow labelling.** `lab roll keep --label Roll/Updates [--sample 300]`: a random
   sample of the label's archived mail, classified by the weapon brain (`qwen2.5:14b`) and
   by the teacher (`claude:sonnet`, PJ's decision; `ROLL_KEEP_TEACHER=` turns it off).
   Nothing is labelled in Gmail. Records go to `var/roll/keep/`; Telegram gets class counts,
   agreement, and every lost keep (local discard, teacher keep). PJ doesn't hand-label:
   `lab roll keep-fixtures` rewrites disagreements, lost keeps first, as synthetic fixture
   candidates (`var/roll/keep/fixture-candidates.jsonl`) for the stage.
4b. **Sanitized escalation.** Roll labels locally and asks the teacher only on the slice it
   gets wrong, through a sanitized view. Shadow data (Updates and Promotions, 400 emails,
   2026-10-28): agreement 175/200 on `promotion`, 59/60 `job-alert`, 34/36 `receipts`,
   0/19 `people`, 9/18 `finance`, 3/13 `health` and `legal-tax`; zero lost keeps. Most
   disagreements are discard-vs-discard (promotion vs marketing or newsletter).
   - Scoring: agreement is keep vs discard; discard subclasses count as one.
   - Matchers before the model, all local: a sender-domain table of past labels from
     Roll's own records; template matching on sender plus subject (rapidfuzz or MinHash)
     so the same mailing reuses its label; nearest neighbours in a small local embedding
     model over labelled mail, whose distance is a confidence; detectors for card numbers,
     amounts and tracking numbers (finance and receipts signals, and the scrubber's input).
   - Escalate when the label is in a weak class (`people`, `finance`, `health`,
     `legal-tax`, revised from shadow data), the answer is unparsed (`keep/unsure`), the
     sender domain is unseen, or the matchers' confidence is low.
   - The sanitized view: sender domain and its kind (bank, retailer, school, personal
     mail), no display name or local part; Gmail category, unsubscribe, List-Id; subject
     and snippet with amounts, digit runs, names, addresses and URLs replaced by
     placeholders. Scrubbing is local (detectors plus the weapon brain); raw text never
     leaves the laptop.
   - Personal-mail senders (gmail.com and the like) never go to Anthropic: Roll keeps them
     as `keep/people`.
   - `lab roll keep-fixtures` rewrites from the sanitized view too.
   - Before the teacher switches over: re-label the stored disagreements with Sonnet on
     the sanitized view and compare with its full-view answers. Where it loses the full
     view's edge (`people` is the likely case), that slice stays local and kept.
5. **Apply labels.** With the weapon earned, or PJ's approval per label, Roll applies
   `Roll/Keep/*` and `Roll/Discard/*` across the `Roll/*` archive. Undo is recorded like
   cleanup rules.
6. **Deletion stays PJ's.** Roll offers a search, for example `label:Roll/Discard/job-alert
   older_than:1y -label:Roll/Keep`, and PJ deletes in Gmail. Roll gets no trash call.

## Decisions (PJ, 2026-10-28)

- Step 4b as written: keep-vs-discard scoring, rule-based escalation (weak classes,
  unparsed, unseen domain), personal-mail senders stay local, `keep-fixtures` sanitized,
  local matching tools ahead of the model.
- Check the laptop's load (CPU, GPU, containers, Dagster runs) before every fight or
  local-model job.

## Decisions (PJ, 2026-10-26)

- Teacher: `claude:sonnet` may teach on real archived mail in step 4, as Rush's triage does.
- `people` mail can become discardable, behind heavy guards. Proposed for step 5, each one
  required: the sender is a relay or automated address (`via`, `noreply`, a network's
  domain), not a person's own mailbox; PJ never replied in the thread; not starred or
  important; past the `people` age below; and PJ approves each sender batch, never a
  blanket rule. Anything else from a person stays `keep/people`.
- Age before Roll proposes deletion, by discard class (30 days is the floor):

  | Class | Age |
  |---|---|
  | `promotion`, `notification` | 30 days |
  | `job-alert` | 60 days |
  | `newsletter`, `marketing` | 90 days |
  | `people` (guarded, above) | 1 year |

  Tune per class after shadow labelling shows how the classes look in the archive.
