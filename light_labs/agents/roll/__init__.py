"""DLN-102 Roll: the lab's housekeeper. Drafts commit messages from a diff. In training."""

import os
from pathlib import Path

from light_labs import config
from light_labs.core import skills

HERE = Path(__file__).resolve().parent
ENTRY = config.robot("Roll")

NAME = ENTRY["name"]
# No model until the commit-message fight picks one; set ROLL_MODEL to try one by hand.
MODEL = os.environ.get("ROLL_MODEL", "")
TEMPERATURE = 0.2
# Diffs are long; Ollama truncates silently past its default window.
NUM_CTX = 8192


# Inbox cleanup (inbox.py): the mailbox Roll cleans and its Telegram chat.
INBOX_ACCOUNT = os.environ.get("ROLL_INBOX_ACCOUNT", "kellypj24@gmail.com")
TELEGRAM_CHAT = os.environ.get("ROLL_TELEGRAM_CHAT", "")
TELEGRAM_KEYCHAIN = "light-labs-roll-telegram"
HOME = config.VAR / "roll"

# Repo chores (chores.py): the local brain whose answers are recorded while big brother
# decides. Mega Man's brain until a dependabot-merge fight picks one.
CHORES_BRAIN = os.environ.get("ROLL_CHORES_BRAIN", "ollama:llama3.1:8b")
# The checkouts `/chores` and `lab roll chores --all` cover: comma-separated, `:admin` on a
# repo whose merges go past a required review. Empty: chores run only with -C.
CHORES_REPOS = os.environ.get("ROLL_CHORES_REPOS", "")
# Claude models big brother climbs, cheapest first.
CHORES_LADDER = tuple(
    m.strip()
    for m in os.environ.get("ROLL_CHORES_LADDER", "haiku,sonnet,opus").split(",")
    if m.strip()
)
# Held PRs (holds.py): the models a fix climbs, cheapest first, and the one offered only
# on PJ's tap once those are spent.
FIX_LADDER = tuple(
    m.strip() for m in os.environ.get("ROLL_FIX_LADDER", "sonnet,opus").split(",") if m.strip()
)
FIX_TOP = os.environ.get("ROLL_FIX_TOP", "claude-fable-5-2")


# Mail keep (keep.py): the brain that earned the mail-keep weapon, and the cloud teacher for
# shadow labelling. The teacher reads only the sanitized view and never personal mail
# (core/sanitize.py; PJ 2026-10-28). Off by default: ROLL_KEEP_TEACHER=claude:sonnet turns it on.
def weapon_brain(stage):
    return next((w["brain"] for w in ENTRY["weapons"] if w["stage"] == stage), None)


KEEP_BRAIN = os.environ.get("ROLL_KEEP_BRAIN") or weapon_brain("mail-keep") or ""
KEEP_TEACHER = os.environ.get("ROLL_KEEP_TEACHER", "")


def bot():
    """Roll's Telegram bot on its mailbox."""
    from light_labs.agents.roll.inbox import RollBot
    from light_labs.core.agentnet import keychain_token
    from light_labs.core.google import Gmail

    HOME.mkdir(parents=True, exist_ok=True)
    roll = RollBot(
        keychain_token(TELEGRAM_KEYCHAIN), TELEGRAM_CHAT, HOME, Gmail("roll", INBOX_ACCOUNT),
        chores=chores_all if CHORES_REPOS else None,
    )  # fmt: skip
    if CHORES_REPOS:
        from light_labs.agents.roll.holds import Holds
        from light_labs.core.store import Store

        roll.holds = Holds(Store(HOME), roll.buttons, CHORES_REPOS, ladder=FIX_LADDER, top=FIX_TOP)
    return roll


def chores_all(apply):
    """Dependabot chores over CHORES_REPOS; the summary Roll texts."""
    from light_labs.agents.roll import chores
    from light_labs.core.store import Store

    HOME.mkdir(parents=True, exist_ok=True)
    results = chores.run_all(
        Store(HOME), CHORES_REPOS, CHORES_BRAIN, apply=apply, ladder=CHORES_LADDER
    )
    if results is None:
        return "Roll: chores are already running."
    return chores.summary(results, apply)


def system_prompt(text=""):
    """Persona + skills; on-match skills load when `text` triggers them."""
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part for part in ((HERE / "persona.md").read_text(), skills.render(loaded, text)) if part
    )
