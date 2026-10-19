"""DLN-100 Rush: the lab's heartbeat and messenger."""

import os
import re
from pathlib import Path

from light_labs import config
from light_labs.core import skills

HERE = Path(__file__).resolve().parent
ENTRY = config.robot("Rush")

NAME = ENTRY["name"]
ACTOR = os.environ.get("RUSH_ACTOR", ENTRY["actor"])
MODEL = os.environ.get("RUSH_MODEL", ENTRY["model"].removeprefix("ollama:"))
SIGNOFF = f"— {NAME} ({ENTRY['dln']}, {ACTOR})"
# Low: every draft is judged on all samples of a fixture, and PJ wants the same answer twice.
TEMPERATURE = float(os.environ.get("RUSH_TEMPERATURE", ENTRY.get("temperature", 0.3)))

# Drafts sent without approval (see autosend.py); RUSH_AUTO_SEND=0 turns it off.
AUTO_SEND = ENTRY.get("auto_send", {})

# Board tasks Rush watches for new comments.
WATCH_TASKS = [t for t in os.environ.get("RUSH_WATCH_TASKS", "").split(",") if t]

# Anywhere else on the board, Rush answers tasks and comments that name it.
MENTION = re.compile(rf"\b({re.escape(NAME)}|{re.escape(ACTOR)}|{ENTRY['dln']})\b", re.IGNORECASE)

# Phone: texts to PJ's own number for drafts waiting on him, with links to the remote page,
# and a scheduled wake so the Mac sleeps between ticks. Unset: no texts, no wakes.
NOTIFY_TO = os.environ.get("RUSH_NOTIFY_TO", "")
REMOTE_URL = os.environ.get("RUSH_REMOTE_URL", "")
# No texts in these local hours ("start-end", 24h); drafts wait for the next tick after.
QUIET_HOURS = os.environ.get("RUSH_QUIET_HOURS", "0-8")
# Telegram (telegram.py): when set, texts go to this chat instead of iMessage.
TELEGRAM_CHAT = os.environ.get("RUSH_TELEGRAM_CHAT", "")
# GitHub watch (github.py): CI, Dependabot and PR comments, texted to PJ. RUSH_GITHUB=1 on;
# RUSH_GITHUB_REPOS limits it to these owner/name repos (default: PJ's active repos).
GITHUB = os.environ.get("RUSH_GITHUB") == "1"
GITHUB_REPOS = [r for r in os.environ.get("RUSH_GITHUB_REPOS", "").split(",") if r]
# Mail triage (mail.py): read-only, one Google sign-in per account; empty = off.
MAIL_ACCOUNTS = [a for a in os.environ.get("RUSH_MAIL_ACCOUNTS", "").split(",") if a]
# Teacher for mail triage (PJ allowed a cloud model until a local one earns the weapon):
# it labels alongside the local brain and its label is used. Off for good once Rush's
# dln.json entry holds the mail-triage weapon, whatever this says.
MAIL_TEACHER = os.environ.get("RUSH_MAIL_TEACHER", "")
# The local model for triage, separate from replies: the best local contender on the
# mail-triage stage (qwen2.5:14b scored 0.865 vs llama3.1:8b's 0.838).
MAIL_MODEL = os.environ.get("RUSH_MAIL_MODEL", MODEL)


def mail_weapon():
    return any(w.get("stage") == "mail-triage" for w in ENTRY.get("weapons", []))


# Testing the wake schedule: text PJ after every tick until this local time (ISO).
PING_UNTIL = os.environ.get("RUSH_PING_UNTIL", "")
WAKE_MINUTES = int(os.environ.get("RUSH_WAKE_MINUTES") or 0)

# Escalations: Auto writes the real draft with this brain (PJ approves it); empty = off.
AUTO_BRAIN = os.environ.get("RUSH_AUTO_BRAIN", "claude:sonnet")
AUTO_SIGNOFF = f"— Auto (Claude Code), for PJ via {ACTOR}"

HOME = config.VAR / "rush"

# memory.md is local and git-ignored: it describes the people and boards Rush works with.
# memory.example.md is the committed template.
MEMORY = HERE / "memory.md"


def system_prompt(text="", memory_text=None):
    """Persona + memory + skills; on-match skills load when `text` triggers them.

    `memory_text` replaces memory.md (evals use synthetic memory)."""
    if memory_text is None:
        memory_text = (MEMORY if MEMORY.exists() else HERE / "memory.example.md").read_text()
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part
        for part in (
            (HERE / "persona.md").read_text(),
            memory_text,
            skills.render(loaded, text),
        )
        if part
    )
