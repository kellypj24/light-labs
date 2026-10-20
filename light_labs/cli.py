"""lab roster | lab skills | lab evals {...} | lab queue {...} | lab claude {...} | lab git {...} | lab rush {...}"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from light_labs import config
from light_labs.core.agentnet import Client
from light_labs.core.brain import Brain
from light_labs.core.store import Store


def cmd_roster(args):
    for r in config.roster():
        print(f"{r['dln']}  {r['name']:8} {r['status']:9} {r['model']:22} {r['job'][:60]}")


def cmd_skills(args):
    from light_labs.core import skills

    carriers = {}
    for r in config.roster():
        for name in r.get("skills", []):
            carriers.setdefault(name, []).append(r["name"])
    for s in skills.discover().values():
        who = ",".join(s.audience) or "-"
        used = ",".join(carriers.get(s.name, [])) or "-"
        print(f"{s.name:22} {who:12} load={s.load:9} robots={used:10} {s.description[:50]}")


def evals_ingest(args):
    from light_labs.evals import results

    for run_id, n in results.ingest(args.paths).items():
        print(f"loaded {run_id} ({n} samples)")
    health_dir = Path(args.paths[0]).parent if args.paths else None
    runs, readings = results.ingest_health(health_dir)
    print(f"loaded {runs} run records, {readings} telemetry readings")
    print(f"db: {results.DB}")


def evals_watch(args):
    from light_labs.evals import watch

    watch.watch(args.run_id)


def evals_cancel(args):
    """Give a stopped (or killed) fight its reason. A record still marked running is
    closed as cancelled now."""
    from light_labs.evals import results

    path = results.RESULTS / f"{args.run_id}.run.json"
    if not path.exists():
        sys.exit(f"no run record {path}")
    record = json.loads(path.read_text())
    if record["status"] == "running":
        from datetime import UTC, datetime

        record.update(status="cancelled", ended_at=datetime.now(UTC).isoformat())
    record["reason"] = args.reason
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"{args.run_id}: {record['status']} ({args.reason})")


def evals_runs(args):
    from light_labs.evals import results

    try:
        cols, rows = results.runs(args.stage, args.contestant, args.limit)
    except LookupError as e:
        sys.exit(str(e))
    _table(cols, rows)


def _table(cols, rows):
    widths = [max(len(str(v)) for v in [c, *(r[i] for r in rows)]) for i, c in enumerate(cols)]
    for row in [cols, *rows]:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths, strict=True)).rstrip())


def _draft_meta(brain):
    commit, dirty = config.git_state()
    return {"brain": brain, "commit": commit, "dirty": dirty}


def queue_ingest(args):
    from light_labs.core import queue_results
    from light_labs.evals import results

    for robot, n in queue_results.ingest(args.root).items():
        print(f"loaded {robot} ({n} queue items)")
    print(f"db: {results.DB}")


def claude_ingest(args):
    from light_labs.core import claude_results
    from light_labs.evals import results

    new, total = claude_results.ingest(args.projects or None)
    print(f"loaded {new} new transcript records ({total} in all)")
    print(f"db: {results.DB}")


def queue_status(args):
    from light_labs.evals import results

    sql = (
        "SELECT robot_kind_key, decision_count, window_size, unedited_sent_count, "
        "edited_sent_count, unknown_edit_count, rejected_count, "
        "round(unedited_rate, 2) AS unedited_rate, is_ready_to_skip_approval "
        "FROM marts.mart_autonomy_status ORDER BY robot_kind_key"
    )
    try:
        with results.connect() as con:
            cur = con.execute(sql)
            cols, rows = [d[0] for d in cur.description], cur.fetchall()
    except Exception:  # noqa: BLE001 - any failure here means the marts are not built
        sys.exit("marts.mart_autonomy_status is missing; run `just analytics`")
    _table(cols, rows)


def rush_tick(args, store, rush):
    from light_labs.agents.rush import phone

    if rush.WAKE_MINUTES:  # first, so a failed tick still wakes the Mac for the next one
        ok, detail = phone.schedule_wake(rush.WAKE_MINUTES)
        if not ok:
            store.journal(f"could not schedule the next wake: {detail}")
    client = Client()
    if not phone.wait_for_edge(lambda: client.inbox(rush.ACTOR)):
        store.journal("edge unreachable after waiting; tick skipped")
        sys.exit("edge unreachable")
    ok = False
    try:
        _tick(args, store, rush, client)
        ok = True
    finally:
        _text_pj(store, rush, ok)
        if rush.MAIL_ACCOUNTS and (rush.TELEGRAM_CHAT or rush.NOTIFY_TO):
            _mail(store, rush)


def _mail(store, rush):
    """Triage new mail with Rush's local brain; texts PJ about what needs a reply."""
    from light_labs.agents.rush import mail
    from light_labs.core.google import Gmail

    try:
        to, send, _ = _phone(store, rush)
    except (OSError, subprocess.CalledProcessError) as e:
        store.journal(f"mail skipped, no phone channel: {e}")
        return
    teacher = None
    if rush.MAIL_TEACHER and not rush.mail_weapon():
        from light_labs.core.brain import brain_for

        teacher = brain_for(rush.MAIL_TEACHER)
    mail.check(
        store,
        rush.MAIL_ACCOUNTS,
        Brain(rush.MAIL_MODEL),
        lambda account: Gmail("rush", account),
        send,
        to,
        rush.REMOTE_URL,
        rush.QUIET_HOURS,
        teacher=teacher,
    )


def _phone(store, rush):
    """(to, send, send_item) for PJ's phone: Telegram when it is set up, else iMessage."""
    from light_labs.agents.rush import phone

    if rush.TELEGRAM_CHAT:
        from light_labs.agents.rush.telegram import Telegram

        tg = Telegram.from_keychain(rush.TELEGRAM_CHAT, store.root / "telegram.json")
        return rush.TELEGRAM_CHAT, tg.text, tg.draft
    return rush.NOTIFY_TO, phone.imessage, None


def _text_pj(store, rush, ok):
    """Drafts waiting, test pings, then GitHub news, over PJ's phone channel."""
    from light_labs.agents.rush import phone

    if not (rush.TELEGRAM_CHAT or rush.NOTIFY_TO):
        return
    try:
        to, send, send_item = _phone(store, rush)
        phone.notify_pending(
            store, to, rush.REMOTE_URL, send, rush.QUIET_HOURS, send_item=send_item
        )
        phone.ping(store, to, rush.PING_UNTIL, ok, send, rush.QUIET_HOURS)
        phone.ask_digest(store, to, rush.REMOTE_URL, send, rush.QUIET_HOURS)
    except (OSError, subprocess.CalledProcessError) as e:
        store.journal(f"could not text PJ: {getattr(e, 'stderr', '') or e}")
        return
    if rush.GITHUB:
        from light_labs.agents.rush import github

        github.notify(store, to, send, rush.GITHUB_REPOS, rush.QUIET_HOURS)


def _tick(args, store, rush, client):
    from light_labs.agents.rush.autosend import Policy
    from light_labs.agents.rush.heartbeat import Heartbeat

    hb = Heartbeat(
        client,
        Brain(rush.MODEL),
        store,
        rush.system_prompt,  # built per message so triggered skills load
        actor=rush.ACTOR,
        watch_tasks=rush.WATCH_TASKS,
        name=rush.NAME,
        signoff=rush.SIGNOFF,
        temperature=rush.TEMPERATURE,
        meta=_draft_meta(f"ollama:{rush.MODEL}"),
        autosend=Policy(rush.AUTO_SEND, store),
        mention=rush.MENTION,
        auto=_auto(rush),
    )
    for item in hb.tick(backfill=args.backfill):
        print(f"queued {item['id']} {item['kind']}" + (" [escalate]" if item["escalate"] else ""))


def _auto(rush):
    """Auto's side of escalations: the brain, its system prompt with Rush's notes."""
    if not rush.AUTO_BRAIN:
        return None
    from light_labs.agents.rush.heartbeat import AUTO_SYSTEM
    from light_labs.core.brain import brain_for

    notes = (rush.MEMORY if rush.MEMORY.exists() else rush.HERE / "memory.example.md").read_text()
    # Claude reads the repo to answer; nothing it can run or write.
    repo = {"tools": "Read,Grep,Glob", "cwd": str(config.REPO), "timeout": 600}
    return {
        "brain": brain_for(
            rush.AUTO_BRAIN, **(repo if rush.AUTO_BRAIN.startswith("claude:") else {})
        ),
        "system": AUTO_SYSTEM + notes,
        "signoff": rush.AUTO_SIGNOFF,
        "meta": {"brain": rush.AUTO_BRAIN},
    }


def rush_queue(args, store, rush):
    for i in store.pending():
        flag = " [escalate]" if i["escalate"] else ""
        print(f"{i['id']}  {i['kind']:7} {i['created']}{flag}  {i['context'][:70]!r}")


def rush_show(args, store, rush):
    print(json.dumps(store.get(args.id), indent=2))


def rush_approve(args, store, rush):
    from light_labs.agents.rush.heartbeat import post

    item = store.get(args.id)
    result = post(Client(), rush.ACTOR, item)
    store.resolve(args.id, "sent", result_id=result.get("id"))
    store.journal(f"sent {args.id} ({item['kind']})")
    print(f"sent {args.id}")


def rush_reject(args, store, rush):
    store.resolve(args.id, "rejected", reason=args.reason)
    store.journal(f"rejected {args.id}" + (f": {args.reason}" if args.reason else ""))
    print(f"rejected {args.id}")


def rush_flag(args, store, rush):
    """An auto-sent draft that should not have gone out: auto-send off for its kind."""
    path = store.root / "queue" / "sent" / f"{args.id}.json"
    if not path.exists():
        sys.exit(f"no sent item {args.id}")
    item = json.loads(path.read_text())
    item.update(flagged=True, flag_reason=args.reason)
    path.write_text(json.dumps(item, indent=2) + "\n")
    state = store.load()
    state["auto_send_off"] = sorted(set(state.get("auto_send_off", [])) | {item["kind"]})
    store.save(state)
    store.journal(f"flagged {args.id}; auto-send off for {item['kind']}: {args.reason or ''}")
    print(
        f"flagged {args.id}; auto-send off for {item['kind']} (lab rush autosend on {item['kind']})"
    )


def rush_autosend(args, store, rush):
    """Show auto-send, or turn a kind back on after a flag (on) / off by hand (off)."""
    state = store.load()
    off = set(state.get("auto_send_off", []))
    if args.action == "on":
        off.discard(args.kind)
    elif args.action == "off":
        off.add(args.kind)
    if args.action in ("on", "off"):
        state["auto_send_off"] = sorted(off)
        store.save(state)
        store.journal(f"auto-send {args.action} for {args.kind} by hand")
    s = rush.AUTO_SEND
    env_off = os.environ.get("RUSH_AUTO_SEND") == "0"
    print(
        f"enabled: {s.get('enabled', False) and not env_off}  kinds: {s.get('kinds', [])}  "
        f"daily cap: {s.get('daily_cap')}  per thread: {s.get('per_thread')}  "
        f"escalations' holding replies: {s.get('escalations', False)}  "
        f"off after a flag: {sorted(off) or 'none'}"
    )


def rush_mute(args, store, rush):
    """Stop (or with --off, resume) drafting on a board task: a log or status thread
    that names Rush without talking to him."""
    state = store.load()
    muted = set(state.get("muted", []))
    if args.task:
        if args.off:
            muted.discard(args.task)
        else:
            muted.add(args.task)
        state["muted"] = sorted(muted)
        store.save(state)
        store.journal(f"{'unmuted' if args.off else 'muted'} {args.task}")
        if not args.off:
            for item in store.pending():
                if item["target"].get("task_id") == args.task:
                    store.resolve(
                        item["id"], "rejected", reason=f"superseded by mute of {args.task}"
                    )
    print("muted: " + (", ".join(sorted(muted)) or "none"))


def _rebuild_prompt(client, item, rush):
    """The prompt a queued draft was written from, rebuilt from the board: the comment its
    context quotes, with the thread before it. None when the comment is gone."""
    from light_labs.agents.rush import heartbeat as hb

    context, target = item["context"], item["target"]
    if item["kind"] == "reply":
        msg = client.message(hb.short_id(target["in_reply_to"]))
        content = (msg.get("content") or "")[: hb.MAX_CONTEXT_CHARS]
        author = context.split(":", 1)[0]
        return hb.reply_prompt(rush.NAME, author, msg.get("summary"), content), content
    task = client.task(target["task_id"])
    comments = task.get("comments") or []
    for idx in range(len(comments) - 1, -1, -1):
        c = comments[idx]
        body = (c.get("text") or "")[: hb.MAX_CONTEXT_CHARS]
        if body and body[:150] in context and context.startswith(f"{c.get('author')} "):
            earlier = [
                (e.get("author"), e.get("text") or "")
                for e in comments[max(0, idx - hb.THREAD_COMMENTS) : idx]
            ]
            prompt = hb.comment_prompt(rush.NAME, task.get("title"), earlier, c.get("author"), body)
            return prompt, body
    body = (task.get("description") or "")[: hb.MAX_CONTEXT_CHARS]
    if body and body[:150] in context:
        return hb.task_prompt(rush.NAME, task.get("title"), task.get("createdBy"), body), body
    return None


def rush_triage(args, store, rush):
    """Dry run: what Auto would do with the queued escalations (note, answer, or leave for
    PJ), written to var/rush/triage-dryrun.jsonl. Posts and resolves nothing."""
    from light_labs.agents.rush.heartbeat import AUTO_TASK, verdict

    auto = _auto(rush)
    if auto is None:
        sys.exit("RUSH_AUTO_BRAIN is empty")
    client = Client()
    items = [i for i in store.pending() if i["escalate"] and (not args.ids or i["id"] in args.ids)]
    out = store.root / "triage-dryrun.jsonl"
    with out.open("a") as f:
        for item in items:
            rebuilt = _rebuild_prompt(client, item, rush)
            if rebuilt is None:
                print(f"{item['id']}  skipped: comment not found on the board")
                continue
            prompt, _ = rebuilt
            try:
                raw = auto["brain"].think(
                    auto["system"], prompt + AUTO_TASK.format(work=item["escalate"])
                )
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
                print(f"{item['id']}  Auto failed: {e}")
                continue
            kind, question, reply = verdict(raw, item["escalate"])
            cost = auto["brain"].last.get("cost_usd")
            f.write(json.dumps({"id": item["id"], "verdict": kind, "question": question,
                                "reply": reply, "context": item["context"][:300],
                                "cost_usd": cost}) + "\n")  # fmt: skip
            f.flush()
            print(f"\n{item['id']}  {kind}" + (f": {question}" if kind == "PJ" else ""))
            print(f"  {item['context'][:120]!r}")
            if reply:
                print("  " + reply.replace("\n", "\n  "))
    print(f"\nwritten to {out}")


def rush_escalate(args, store, rush):
    """Hand an escalation to Auto (Claude Code). The result stays local for review."""
    path = store.root / "escalations" / f"{args.id}.md"
    if not path.exists():
        sys.exit(f"no escalation file for {args.id}")
    out = store.root / "escalations" / f"{args.id}.result.md"
    prompt = (
        f"You are Auto, the mechanic in PJ's light-labs. Rush ({rush.ENTRY['dln']}) "
        f"escalated the work in {path}. Do a first pass and write the result to {out}. "
        "Do not post anything to Agent Net; PJ reviews first."
    )
    subprocess.run(["claude", "-p", prompt], check=True)


def rush_remote(args, store, rush):
    """The phone page: queue, board, inbox. Publish with `tailscale serve`."""
    from light_labs.agents.rush import remote

    remote.serve(
        store,
        rush,
        port=args.port,
        allowed=args.allow or None,
        tick=remote.cli_tick(store, rush),
    )


def rush_mail_fixtures(args, store, rush):
    """Teacher/local disagreements on real mail, rewritten as synthetic fixture candidates."""
    from light_labs.agents.rush import mail
    from light_labs.core.brain import brain_for

    if not rush.MAIL_TEACHER:
        sys.exit("RUSH_MAIL_TEACHER is not set")
    made = mail.fixture_candidates(store, brain_for(rush.MAIL_TEACHER), args.limit)
    for fx in made:
        print(f"{fx['id']}: {fx['label']} (local said {fx['student_label']})")
    print(f"{len(made)} candidate(s) in {store.root / 'mail' / 'fixture-candidates.jsonl'}")


def rush_telegram_link(args, store, rush):
    """After PJ sends the bot /start: the chat ids that wrote to it, for RUSH_TELEGRAM_CHAT."""
    from light_labs.agents.rush import telegram

    chats = telegram.link(telegram.keychain_token(telegram.KEYCHAIN))
    for chat_id, name in chats:
        print(f"{chat_id}  {name}")
    if not chats:
        print("no messages yet: send the bot /start, then run this again")


def cmd_google(args):
    """Robots' Google sign-ins: `auth <robot>` stores its token, `check <robot>` reads its
    mailbox profile to prove the token works."""
    from light_labs.core import google

    if args.cmd == "auth":
        account, scopes = google.authorize(args.who, login_hint=args.account)
        print(f"{args.who}: signed in to {account} with {', '.join(scopes)}")
    elif args.cmd == "check":
        p = google.Gmail(args.who, args.account).profile()
        print(f"{args.who}: {p['emailAddress']}, {p['messagesTotal']} messages")


def cmd_roll(args):
    """DLN-102 Roll: inbox report (read-only) and undo of an approved rule."""
    from light_labs.agents import roll
    from light_labs.agents.roll import inbox

    if not roll.TELEGRAM_CHAT:
        sys.exit("ROLL_TELEGRAM_CHAT is not set")
    bot = roll.bot()
    if args.cmd == "report":
        report = inbox.survey(bot.gmail)
        bot.send_report(report)
        for r in report["rules"]:
            print(f"{r['id']:18} {r['count']:>7,}")
        print(f"inbox {report['inbox']:,}, unread {report['unread']:,}; rules sent to Telegram")
    elif args.cmd == "apply":
        print(f"{args.rule}: archived {bot.apply(args.rule):,}")
        if args.label_archived:
            print(f"{args.rule}: labelled {bot.label_archived(args.rule):,} already archived")
    elif args.cmd == "undo":
        n = bot.undo(args.rule)
        print(f"{n} back in the inbox" if n is not None else "nothing to undo")


def cmd_git(args):
    from light_labs import gitops

    repo = gitops.Repo(args.repo)
    try:
        if args.cmd == "status":
            gitops.status(repo, pr=args.pr, fetch=not args.no_fetch)
        elif args.cmd == "ship":
            message = Path(args.file).read_text() if args.file else args.message
            body = Path(args.body_file).read_text() if args.body_file else None
            check = args.check.split() if args.check else None
            gitops.ship(repo, message, title=args.title, body=body, check=check)
        elif args.cmd == "land":
            files = gitops.land(repo, args.pr, wait=not args.no_wait)
            if any(f.startswith("light_labs/orchestration/") for f in files):
                print("orchestration changed: `just dagster-restart` to load it")
        elif args.cmd == "tidy":
            gitops.tidy(repo, apply=args.apply, stale_days=args.stale_days)
        elif args.cmd == "labels":
            gitops.sync_labels(repo, apply=args.apply, prune=args.prune)
        elif args.cmd == "label":
            if gitops.load_labels(repo) is None:
                sys.exit(f"lab git label: no {gitops.LABELS_FILE} here")
            gitops.label_prs(repo, args.prs or None)
    except gitops.GitError as e:
        sys.exit(f"lab git {args.cmd}: {e}")


def cmd_mcp(args):
    from light_labs.core import mcp_server

    mcp_server.serve()


def main(argv=None):
    p = argparse.ArgumentParser(prog="lab")
    sub = p.add_subparsers(dest="robot", required=True)
    sub.add_parser("roster", help="list the DLN registry")
    sub.add_parser("mcp", help="serve the lab over MCP on stdio (read-only; for Hermes)")
    sub.add_parser("skills", help="list skills, their audience and which robots carry them")
    evals_p = sub.add_parser("evals", help="eval results in DuckDB (var/lab.duckdb)")
    ecmd = evals_p.add_subparsers(dest="cmd", required=True)
    ecmd.add_parser("ingest", help="load var/evals/*.jsonl (idempotent)").add_argument(
        "paths", nargs="*", help="specific JSONL files (default: all)"
    )
    ecmd.add_parser(
        "watch", help="follow fights live; no run_id: the latest, then each next one"
    ).add_argument("run_id", nargs="?")
    cancel_p = ecmd.add_parser("cancel", help="record why a fight was stopped")
    cancel_p.add_argument("run_id")
    cancel_p.add_argument("--reason", required=True)
    runs_p = ecmd.add_parser("runs", help="recent runs from marts.fct_eval_runs, newest first")
    runs_p.add_argument("--stage")
    runs_p.add_argument("--contestant")
    runs_p.add_argument("--limit", type=int, default=20)
    queue_p = sub.add_parser("queue", help="robots' approval queues in DuckDB")
    qcmd = queue_p.add_subparsers(dest="cmd", required=True)
    qcmd.add_parser("ingest", help="reload var/<robot>/queue into raw.queue_items").add_argument(
        "--root", help="directory holding <robot>/queue (default: var/)"
    )
    qcmd.add_parser("status", help="per robot and draft kind: ready to skip approval?")
    claude_p = sub.add_parser("claude", help="Claude Code's own usage in DuckDB")
    ccmd = claude_p.add_subparsers(dest="cmd", required=True)
    cingest = ccmd.add_parser(
        "ingest", help="append transcript records not loaded before (idempotent)"
    )
    cingest.add_argument(
        "--projects",
        nargs="*",
        help="transcript roots holding <project>/<session>.jsonl "
        "(default: ~/.claude/projects and var/claude/projects)",
    )
    git_p = sub.add_parser("git", help="git and GitHub chores, compact output (any repo)")
    git_p.add_argument("-C", dest="repo", default=".", help="repository (default: cwd)")
    gcmd = git_p.add_subparsers(dest="cmd", required=True)
    status_p = gcmd.add_parser(
        "status",
        help="this checkout, every worktree with its PR, open PRs with failing checks; "
        "--pr N for one PR's checks, mergeability and merge commit",
    )
    status_p.add_argument("--pr", type=int, help="one PR in detail")
    status_p.add_argument(
        "--no-fetch", action="store_true", help="skip `git fetch` (offline, or just fetched)"
    )
    ship_p = gcmd.add_parser("ship", help="check, commit, push, open or find the PR")
    msg = ship_p.add_mutually_exclusive_group()
    msg.add_argument("-m", "--message", help="commit message")
    msg.add_argument("-F", "--file", help="commit message from a file")
    ship_p.add_argument("--title", help="PR title (default: the commit subject)")
    ship_p.add_argument("--body-file", help="PR body (default: commit body + test plan)")
    ship_p.add_argument("--check", help="check command (default: `just check`)")
    land_p = gcmd.add_parser("land", help="wait for CI, squash-merge, update main, clean up")
    land_p.add_argument("pr", type=int)
    land_p.add_argument("--no-wait", action="store_true", help="merge without waiting on CI")
    tidy_p = gcmd.add_parser("tidy", help="merged or abandoned branches and worktrees")
    tidy_p.add_argument("--apply", action="store_true", help="delete (default: list only)")
    tidy_p.add_argument("--stale-days", type=int, default=30)
    labels_p = gcmd.add_parser("labels", help="sync the label set from .github/labels.toml")
    labels_p.add_argument("--apply", action="store_true", help="write (default: list only)")
    labels_p.add_argument("--prune", action="store_true", help="also delete labels not in it")
    label_p = gcmd.add_parser("label", help="add type/area labels to PRs (default: all open)")
    label_p.add_argument("prs", nargs="*", type=int)
    roll_p = sub.add_parser("roll", help="DLN-102 Roll: inbox cleanup by approved rules")
    rocmd = roll_p.add_subparsers(dest="cmd", required=True)
    rocmd.add_parser("report", help="count the inbox, send proposed rules to Telegram")
    ap = rocmd.add_parser("apply", help="label and archive a rule's matches (PJ approved it)")
    ap.add_argument("rule")
    ap.add_argument("--label-archived", action="store_true", help="also label its archived mail")
    rocmd.add_parser("undo", help="put a rule's last archive back").add_argument("rule")
    google_p = sub.add_parser("google", help="robots' Google sign-ins (Gmail)")
    gocmd = google_p.add_subparsers(dest="cmd", required=True)
    for name, text in (
        ("auth", "sign a robot in with its scopes"),
        ("check", "prove a token works"),
    ):
        gp = gocmd.add_parser(name, help=text)
        gp.add_argument("who", choices=["rush", "roll"])
        gp.add_argument(
            "--account",
            required=name == "check",
            help="mailbox: for auth a hint (the token is stored under whoever signs in)",
        )
    rush_p = sub.add_parser("rush", help="DLN-100 Rush, the heartbeat")
    rcmd = rush_p.add_subparsers(dest="cmd", required=True)
    rcmd.add_parser("tick").add_argument(
        "--backfill", action="store_true", help="on first run, draft for the backlog"
    )
    rcmd.add_parser("queue")
    for name in ("show", "approve", "escalate"):
        rcmd.add_parser(name).add_argument("id")
    flag_p = rcmd.add_parser("flag", help="an auto-sent draft that should not have gone out")
    flag_p.add_argument("id")
    flag_p.add_argument("--reason")
    auto_p = rcmd.add_parser("autosend", help="show auto-send; turn a kind on or off")
    auto_p.add_argument("action", nargs="?", choices=["on", "off"])
    auto_p.add_argument("kind", nargs="?", choices=["reply", "comment"])
    rcmd.add_parser(
        "triage", help="dry run: what Auto would do with the queued escalations"
    ).add_argument("ids", nargs="*")
    mute_p = rcmd.add_parser(
        "mute", help="stop drafting on a board task (a log thread); no task: list"
    )
    mute_p.add_argument("task", nargs="?")
    mute_p.add_argument("--off", action="store_true", help="resume drafting on it")
    rcmd.add_parser(
        "mail-fixtures", help="teacher/local disagreements -> synthetic fixture candidates"
    ).add_argument("--limit", type=int, default=20)
    rcmd.add_parser("telegram-link", help="chat ids that messaged the bot (RUSH_TELEGRAM_CHAT)")
    remote_p = rcmd.add_parser("remote", help="phone page for the queue and board (tailnet only)")
    remote_p.add_argument("--port", type=int, default=8787)
    remote_p.add_argument(
        "--allow", action="append", help="Tailscale login allowed in (default: this machine's)"
    )
    reject_p = rcmd.add_parser("reject")
    reject_p.add_argument("id")
    reject_p.add_argument("--reason", help="why, for the queue analytics")
    args = p.parse_args(argv)

    if args.robot in ("roster", "skills", "git", "google", "roll", "mcp"):
        globals()[f"cmd_{args.robot}"](args)
        return
    if args.robot in ("evals", "queue", "claude"):
        globals()[f"{args.robot}_{args.cmd}"](args)
        return
    from light_labs.agents import rush

    globals()[f"rush_{args.cmd.replace('-', '_')}"](args, Store(rush.HOME), rush)


if __name__ == "__main__":
    main()
