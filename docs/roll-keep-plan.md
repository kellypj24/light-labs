# Plan: Roll learns what to keep (`mail-keep` stage)

Status: planned, not started. Written 2026-10-19.

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

1. **Rescue the trashed Promotions.** About 20k `Roll/Promotions` messages went to Trash on
   2026-10-19 and are purged around 2026-11-18. Add `untrash` to `google.py` for Roll
   only (restores; still no delete, trash or send), and `lab roll untrash --label
   Roll/Promotions`. Untrash removes only `TRASH`, so mail returns to the archive, not the
   inbox. Update `tests/test_google.py`'s no-destructive-calls check to allow `untrash`.
2. **Stage and fixtures.** `mail-keep.yaml`, `run_one` wiring for Roll, mock contestant
   in CI. Update `evals/README.md`'s stage table and Roll's `dln.json` entry (its `job`
   still describes only commit messages and branch triage).
3. **Fight.** `just eval mail-keep mega-man,proto,bass 3 -cool-above 40`, one model at a
   time. Ask PJ before starting; estimate from mail-triage (about 4 minutes per local model).
4. **Shadow labelling.** `lab roll keep --label Roll/Updates --dry-run`: classify archived
   mail locally and write counts plus 20 random samples per class to Telegram, with no
   labels applied. PJ marks wrong samples; `lab roll keep-fixtures` rewrites them as
   synthetic fixture candidates (same loop as `lab rush mail-fixtures`).
5. **Apply labels.** With the weapon earned, or PJ's approval per label, Roll applies
   `Roll/Keep/*` and `Roll/Discard/*` across the `Roll/*` archive. Undo is recorded like
   cleanup rules.
6. **Deletion stays PJ's.** Roll offers a search, for example `label:Roll/Discard/job-alert
   older_than:1y -label:Roll/Keep`, and PJ deletes in Gmail. Roll gets no trash call.

## Decisions for PJ

- Teacher: allow `claude:sonnet` as a teacher on real archived mail during step 4, as Rush
  has for triage, or keep step 4 local-only and rely on PJ's sample marks.
- Whether `people` mail ever becomes discardable (old automated "via" messages from real
  names, such as LinkedIn).
- Age per discard class before Roll proposes deletion (default: 1 year for all).
