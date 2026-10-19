"""Roll's inbox cleanup: a read-only report, then rules PJ approves one tap at a time.

`lab roll report` counts what sits in the inbox and proposes cleanup rules, each a Gmail
search plus an action, and sends each to PJ on Telegram with Approve and Skip buttons.
Nothing changes until he taps Approve. Approving re-runs the search at that moment and
archives the matches (removes INBOX: mail stays in All Mail and search). The ids are
recorded, so `lab roll undo <rule>` (or /undo in the chat) puts them back.

No model: rules are Gmail searches. Never touched by any rule: starred mail, and mail
newer than the rule's age. Nothing is deleted, trashed or sent (google.py has no call
for it).
"""

import contextlib
import json
import urllib.error
from collections import Counter
from datetime import UTC, datetime

from light_labs.agents.rush.telegram import Telegram

CAP = 200_000  # page through every match; the inbox holds ~55k
SAMPLE = 200  # messages read per rule to name the top senders
TOP_SENDERS = 6
GUARD = "-is:starred"

# id -> (what PJ reads, Gmail search). Each archives its matches.
# Each rule's archived mail also gets a label, so PJ can find it and delete it in bulk
# himself (Gmail: open the label, select all, Delete; Trash keeps it 30 days).
LABELS = {
    "promotions-30d": "Roll/Promotions",
    "social-30d": "Roll/Social",
    "forums-30d": "Roll/Forums",
    "updates-90d": "Roll/Updates",
    "bulk-primary-60d": "Roll/Bulk",
}
RULES = {
    "promotions-30d": (
        "Archive Promotions older than 30 days",
        "in:inbox category:promotions older_than:30d",
    ),
    "social-30d": (
        "Archive Social notifications older than 30 days",
        "in:inbox category:social older_than:30d",
    ),
    "forums-30d": (
        "Archive Forums and mailing lists older than 30 days",
        "in:inbox category:forums older_than:30d",
    ),
    "updates-90d": (
        "Archive Updates (receipts, notices, alerts) older than 90 days",
        "in:inbox category:updates older_than:90d",
    ),
    "bulk-primary-60d": (
        "Archive bulk mail in Primary older than 60 days (unsubscribe link, not important)",
        "in:inbox category:primary unsubscribe -is:important older_than:60d",
    ),
}


def search(rule_id):
    return f"{RULES[rule_id][1]} {GUARD}"


def _sender(m):
    for h in m.get("payload", {}).get("headers", []):
        if h["name"].lower() == "from":
            return h["value"].split("<")[0].strip().strip('"') or h["value"]
    return "?"


def survey(gmail):
    """The report: inbox size, and per rule its count and top senders. Reads only."""
    label = gmail.call("labels/INBOX")  # exact; search estimates are not
    report = {"inbox": label["messagesTotal"], "unread": label["messagesUnread"], "rules": []}
    for rule_id, (title, _) in RULES.items():
        ids = gmail.ids(search(rule_id), cap=CAP)
        senders = Counter(_sender(gmail.message(i, headers=("From",))) for i in ids[:SAMPLE])
        report["rules"].append(
            {"id": rule_id, "title": title, "count": len(ids),
             "top": senders.most_common(TOP_SENDERS), "sampled": min(len(ids), SAMPLE)}
        )  # fmt: skip
    return report


def rule_text(r):
    top = "\n".join(f"  {n}  {name}" for name, n in r["top"])
    sample = f" (top senders from {r['sampled']} read)" if r["count"] > r["sampled"] else ""
    return (
        f"Roll: {r['title']}: {r['count']:,} emails.\n"
        f"Top senders{sample}:\n{top}\n\n"
        "Archive only: they leave the inbox, get a Roll/ label, and stay in All Mail and "
        "search. Starred mail is never touched. Undo any time."
    )


class RollBot(Telegram):
    """Roll's chat: Approve/Skip on rules, /undo <rule>, /report."""

    def __init__(self, token, chat_id, root, gmail, opener=None):
        kw = {"opener": opener} if opener else {}
        super().__init__(token, chat_id, root / "telegram.json", **kw)
        self.root, self.gmail = root, gmail
        (root / "applied").mkdir(parents=True, exist_ok=True)

    def journal(self, line):
        with (self.root / "journal.md").open("a") as f:
            f.write(f"- {datetime.now(UTC).isoformat(timespec='seconds')} {line}\n")

    def send_report(self, report):
        self.text(
            None,
            f"Roll: inbox report for {self.gmail.account}. {report['inbox']:,} emails in the "
            f"inbox, {report['unread']:,} unread. {len(RULES)} rules to approve or skip below.",
        )
        for r in report["rules"]:
            if r["count"]:
                self.call(
                    "sendMessage",
                    chat_id=self.chat_id,
                    text=rule_text(r),
                    reply_markup={"inline_keyboard": [[
                        {"text": f"Approve: archive {r['count']:,}", "callback_data": f"apply:{r['id']}"},
                        {"text": "Skip", "callback_data": f"skip:{r['id']}"},
                    ]]},
                )  # fmt: skip
        (self.root / "report.json").write_text(json.dumps(report, indent=2))

    def apply(self, rule_id):
        """Label and archive what the rule matches now; record the ids for undo."""
        ids = self.gmail.ids(search(rule_id), cap=CAP)
        label = self.gmail.label_id(LABELS[rule_id])
        self.gmail.relabel(ids, add=[label], remove=["INBOX"])
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (self.root / "applied" / f"{rule_id}-{stamp}.json").write_text(json.dumps(ids))
        self.journal(f"applied {rule_id}: archived {len(ids)}")
        return len(ids)

    def undo(self, rule_id):
        """Put the most recent application of a rule back in the inbox."""
        runs = sorted((self.root / "applied").glob(f"{rule_id}-*.json"))
        if not runs:
            return None
        ids = json.loads(runs[-1].read_text())
        self.gmail.relabel(ids, add=["INBOX"], remove=[self.gmail.label_id(LABELS[rule_id])])
        runs[-1].rename(runs[-1].with_suffix(".undone"))
        self.journal(f"undid {rule_id}: {len(ids)} back in the inbox")
        return len(ids)

    def label_archived(self, rule_id):
        """Label mail of a rule's kind that is already out of the inbox (archived earlier,
        by PJ or by a run that did not finish), so the label holds all of it."""
        query = search(rule_id).replace("in:inbox", "-in:inbox -in:trash -in:spam")
        ids = self.gmail.ids(query, cap=CAP)
        self.gmail.relabel(ids, add=[self.gmail.label_id(LABELS[rule_id])])
        self.journal(f"labelled {len(ids)} archived {rule_id} as {LABELS[rule_id]}")
        return len(ids)

    def report_failure(self, e):
        self.journal(f"poll failed: {e}")
        with contextlib.suppress(Exception):  # offline: the journal has it
            self.text(None, f"Roll: something failed: {e}. Still running; Auto will look.")

    def poll_forever(self, remote=None, sleep=None):
        import time

        while True:
            try:
                self.poll_once(remote)
            except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
                # The long poll drops while the Mac sleeps or the network blips; Rush's
                # poller retries these quietly too. Failures handling PJ's taps are
                # reported by handle().
                print(f"roll poll: {e}")
                (sleep or time.sleep)(15)
            except Exception as e:  # noqa: BLE001 - one bad update must not stop Roll
                self.report_failure(e)
                (sleep or time.sleep)(15)

    def handle(self, update, remote=None):
        try:
            return self._handle(update, remote)
        except Exception as e:  # noqa: BLE001 - a failed tap is reported, Roll keeps polling
            self.report_failure(e)
            return None

    def _handle(self, update, remote=None):
        if "callback_query" in update:
            q = update["callback_query"]
            if not self._from_pj(q.get("message", {}).get("chat", {})):
                return None
            action, _, rule_id = (q.get("data") or "").partition(":")
            if rule_id not in RULES:
                return None
            self.call("answerCallbackQuery", callback_query_id=q["id"], text="On it")
            msg = q.get("message", {})
            if action == "apply":
                n = self.apply(rule_id)
                note = f"Archived {n:,} and labelled them {LABELS[rule_id]}. Undo: /undo {rule_id}"
            else:
                note = "Skipped."
                self.journal(f"skipped {rule_id}")
            self.call("editMessageText", chat_id=self.chat_id, message_id=msg["message_id"],
                      text=f"{msg.get('text', '')}\n\n{note}")  # fmt: skip
            return note
        msg = update.get("message") or {}
        if not self._from_pj(msg.get("chat", {})):
            return None
        text = (msg.get("text") or "").strip()
        if text.startswith("/undo"):
            rule_id = text.partition(" ")[2].strip()
            if rule_id not in RULES:
                return self.text(None, "Which rule? " + ", ".join(RULES))
            n = self.undo(rule_id)
            return self.text(
                None, f"Put {n:,} back in the inbox." if n is not None else "Nothing to undo."
            )
        if text in ("/report", "report"):
            self.text(None, "Counting your inbox; the report follows in a few minutes.")
            return self.send_report(survey(self.gmail))
        return self.text(
            None,
            "I'm Roll. I clean your inbox with rules you approve: /report for a fresh count, "
            "/undo <rule> to put a rule's mail back.",
        )
