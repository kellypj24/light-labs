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


# Mail keep (keep.py): the brain that earned the mail-keep weapon, and the cloud teacher for
# shadow labelling. The teacher reads only the sanitized view and never personal mail
# (sanitize.py; PJ 2026-10-28). Off by default: ROLL_KEEP_TEACHER=claude:sonnet turns it on.
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
    return RollBot(
        keychain_token(TELEGRAM_KEYCHAIN), TELEGRAM_CHAT, HOME, Gmail("roll", INBOX_ACCOUNT)
    )


def system_prompt(text=""):
    """Persona + skills; on-match skills load when `text` triggers them."""
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part for part in ((HERE / "persona.md").read_text(), skills.render(loaded, text)) if part
    )
