"""lab roster | lab skills | lab rush {tick,queue,show,approve,reject,escalate}"""

import argparse
import json
import subprocess
import sys

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


def rush_tick(args, store, rush):
    from light_labs.agents.rush.heartbeat import Heartbeat

    hb = Heartbeat(
        Client(),
        Brain(rush.MODEL),
        store,
        rush.system_prompt,  # built per message so triggered skills load
        actor=rush.ACTOR,
        watch_tasks=rush.WATCH_TASKS,
        name=rush.NAME,
        signoff=rush.SIGNOFF,
    )
    for item in hb.tick(backfill=args.backfill):
        print(f"queued {item['id']} {item['kind']}" + (" [escalate]" if item["escalate"] else ""))


def rush_queue(args, store, rush):
    for i in store.pending():
        flag = " [escalate]" if i["escalate"] else ""
        print(f"{i['id']}  {i['kind']:7} {i['created']}{flag}  {i['context'][:70]!r}")


def rush_show(args, store, rush):
    print(json.dumps(store.get(args.id), indent=2))


def rush_approve(args, store, rush):
    item = store.get(args.id)
    client, t = Client(), item["target"]
    if item["kind"] == "reply":
        result = client.send(
            rush.ACTOR,
            t["to"],
            item["draft"],
            summary=t.get("summary") and f"re: {t['summary']}",
            in_reply_to=t.get("in_reply_to"),
        )
    else:
        result = client.comment(rush.ACTOR, t["task_id"], item["draft"])
    store.resolve(args.id, "sent", result_id=result.get("id"))
    store.journal(f"sent {args.id} ({item['kind']})")
    print(f"sent {args.id}")


def rush_reject(args, store, rush):
    store.resolve(args.id, "rejected")
    store.journal(f"rejected {args.id}")
    print(f"rejected {args.id}")


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


def main(argv=None):
    p = argparse.ArgumentParser(prog="lab")
    sub = p.add_subparsers(dest="robot", required=True)
    sub.add_parser("roster", help="list the DLN registry")
    sub.add_parser("skills", help="list skills, their audience and which robots carry them")
    rush_p = sub.add_parser("rush", help="DLN-100 Rush, the heartbeat")
    rcmd = rush_p.add_subparsers(dest="cmd", required=True)
    rcmd.add_parser("tick").add_argument(
        "--backfill", action="store_true", help="on first run, draft for the backlog"
    )
    rcmd.add_parser("queue")
    for name in ("show", "approve", "reject", "escalate"):
        rcmd.add_parser(name).add_argument("id")
    args = p.parse_args(argv)

    if args.robot in ("roster", "skills"):
        globals()[f"cmd_{args.robot}"](args)
        return
    from light_labs.agents import rush

    globals()[f"rush_{args.cmd}"](args, Store(rush.HOME), rush)


if __name__ == "__main__":
    main()
