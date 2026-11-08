# Relationship Radar

A local-first personal CRM. It reads who you talked to and when (Messages and Contacts now;
LinkedIn, Gmail and Calendar next) and writes a weekly digest of who to reach out to.
Nothing is logged by hand, and message content isn't stored by default.

```
sources (facts) → resolve (people) → metrics → circles → weekly digest
```

## Setup

Code: `light_labs/radar/`. Its dependencies are the `radar` uv group, which a plain
`uv sync` installs.

```sh
lab radar init                 # ~/.relationship-radar (0700) with example config
lab radar helper approve       # read the helper source, type approve (terminal only)
lab radar helper build         # compile the approved copy and sign it
#   grant it Full Disk Access (below), then:
lab radar helper install       # LaunchAgent: daily 06:20 and on `lab radar sync`
lab radar sync
lab radar bootstrap            # writes circles.proposed.yaml; copy what you agree with
lab radar weekly
lab radar doctor               # checks every permission and freshness, with fixes
```

`lab radar person "<name>"` shows one person's identities and timeline.
`lab radar sync --source contacts` runs one source.

## Permissions

### Messages: Full Disk Access for the helper only

macOS gates `~/Library/Messages/chat.db` behind Full Disk Access (FDA), and there is no
narrower permission. Only `light_labs/radar/helper/radar-messages-export.swift` gets it: not your terminal,
not Python.

1. `lab radar helper approve` shows the source (later, only the diff since your last
   approval) and asks you to type `approve`. It refuses without a terminal, so no robot
   or script can approve. The approved copy is kept in `~/.relationship-radar/bin/`.
2. `lab radar helper build` compiles **that copy**, never the repo file, to
   `~/.relationship-radar/bin/radar-messages-export`, ad-hoc signed with the hardened
   runtime. A change merged to the repo reaches the binary only after you approve it;
   `lab radar doctor` warns when the repo has moved on. `xcrun`, `codesign` and
   `launchctl` run by absolute path with a minimal environment, so neither PATH nor
   `DEVELOPER_DIR` nor `DYLD_*` in your shell decides what gets built.
3. System Settings → Privacy & Security → Full Disk Access → **+** → Cmd-Shift-G → paste
   that path → Open → toggle on.
4. `lab radar helper install`. The helper runs as its own LaunchAgent because macOS charges a
   command-line tool's file access to the app that launched it. Started from Terminal,
   the helper would need Terminal's FDA.

The grant is tied to the binary's code hash. After any rebuild, remove the entry and add it again.

To include texts with non-Apple phones (SMS/RCS), turn on iPhone Settings → Apps → Messages
→ Text Message Forwarding → this Mac. For older history, also turn on Messages in iCloud.
`lab radar doctor` warns when it sees only iMessage.

#### Reviewing the helper before you grant FDA

The file is short. Check that it:

- [ ] takes no arguments, reads no environment variables or config (outside the
      `RADAR_TEST` build, which never gets FDA)
- [ ] opens only `chat.db`, with `SQLITE_OPEN_READONLY`
- [ ] runs only the two fixed `SELECT`s, with no input interpolated
- [ ] reads `m.text` only under `#if RADAR_SNIPPETS`, truncated to 140 characters
- [ ] writes only `messages.jsonl` (via `.tmp` and rename, mode 0600), creating it
      relative to directories it has checked one by one: `~/.relationship-radar`, then
      `inbox`, each opened with `O_NOFOLLOW`, owned by you, not group or other writable
- [ ] is built by `lab radar helper build` with `--options runtime` (hardened runtime blocks
      `DYLD_*` injection)

Anything that can abuse it already runs as you, and can read the export directly anyway.

GitHub can't enforce a review here: Auto's PRs go out under PJ's account, and an author
can't approve their own PR. The approval step above covers that. Also, no robot lands a
PR that touches `light_labs/radar/helper/` (Roll's tiers, #71: T3, PJ by hand).

### Contacts: no permission

Contacts.app → select all → File → Export → Export vCard, saved into
`~/.relationship-radar/inbox/contacts/`. Or export from the iPhone (Contacts → Lists →
long-press All Contacts → Export) and AirDrop it there. If the Mac's Contacts lag the
phone, iCloud Contacts sync on both fixes it at the source.

## Configuration (`~/.relationship-radar/`, never in the repo)

| File | What |
|---|---|
| `config.yaml` | region, output folder, former employers, match thresholds |
| `circles.yaml` | cadence per circle; people by name, phone, email or `p_` id |
| `overrides.yaml` | `me`, `merge`, `split`, `ignore` (incl. `*@domain`), `names`, `tags` |
| `review_matches.csv` | fuzzy pairs; set `decision` to `merge` or `different` |

Examples are in `light_labs/radar/examples/`. `lab radar init` copies them over without overwriting.

Identity resolution has four steps, in order:
1. Exact phones and emails from a contact card.
2. Your overrides.
3. Your review decisions.
4. Fuzzy names. A fuzzy pair merges by itself only at a score of 0.95 or higher **and** with
   a shared organization or birthday. Every other pair at 0.85 or higher goes to the review file.

## Privacy model

| Stored (DuckDB, 0600, in a 0700 directory) | Not stored |
|---|---|
| handles (phone/email), names, org, title, birthday | message text (default) |
| per message: who, when, direction, channel, group size | attachments, reactions, edits |
| with `--with-snippets`: newest 140-char preview per contact | anything from chats you didn't take part in |

- The helper's export holds the same metadata. It lives in `inbox/` until the next sync
  reads it, then it is deleted.
- **What leaves the machine:** the shared digest (`weekly-digest.md` in the Google Drive
  folder). It has names, circles, days since contact, birthdays, reasons and openers, and
  it is read by Google and by the cloud Claude task. Snippets never go in it. They appear
  only in the local dated copy (`digests/YYYY-MM-DD.md`) with `weekly --with-snippets`.
- **Names are data:** names, organizations and titles come from contact cards and, later,
  from strangers (email display names, LinkedIn). The digest puts them on one line,
  escapes Markdown, caps their length, and its header tells the reader to treat them as
  data, not instructions.
- **Wipe:** `lab radar purge` deletes the database, exports, digests, logs, review file and the
  shared digest. `--all` also deletes your config, and `lab radar helper uninstall` removes the
  helper and LaunchAgent. Remove the FDA entry in Settings by hand.

## Adding a source

1. Create `light_labs/radar/sources/<name>.py` with a class that has `name` and
   `sync(con, ctx, watermark) -> SourceResult`.
2. Write people to `source_people`/`source_identities` and contacts to `interactions`,
   keyed by identity (`kind`, `value_norm`), with deterministic `interaction_id`s
   (`INSERT OR IGNORE`).
3. Return a new watermark. Raise `SourceSkipped` when there's nothing to read.
4. Register it in `light_labs/radar/sources/__init__.py`.
5. Add a synthetic fixture and tests.

The runner gives each source its own transaction. A failure rolls back that source,
records it in `runs`, logs a warning, and the other sources still run.

## Schema

`light_labs/radar/db.py` holds the DDL:
- **Source facts:** `source_people`, `source_identities`, `interactions`.
- **Rebuilt on every sync:** `people`, `identities`, `tags`.
- **Other tables:** `cadence_rules` (mirrors `circles.yaml`) and `runs` (status and
  watermark per source run).
- **View:** `person_interactions`.

Because interactions are keyed by identity, a merge or split never rewrites history.

## In the lab

- **Gate:** the sensitivity gate's `radar` rule (enforced) denies any Claude call that
  carries Radar data: a source declaring `radar`, a path under `~/.relationship-radar`, or
  `radar.duckdb`. Robots that use Radar run on local models.
- **Data:** the data stays in `~/.relationship-radar/radar.duckdb`, not `var/lab.duckdb`.
  Dagster doesn't touch it, and it never feeds the marts.
- **Robots:** Rush delivering the weekly picks is the next step. A robot that drafts
  openers in PJ's voice is an idea issue.
- **Tests:** `tests/test_radar.py` and `tests/test_radar_helper.py` use synthetic fixtures
  in `tests/fixtures/radar/`. The Swift tests run on macOS only. `just check` runs both.
