"""DLN-100 Rush: the lab's heartbeat and messenger."""

import os
from pathlib import Path

from light_labs import config
from light_labs.core import skills

HERE = Path(__file__).resolve().parent
ENTRY = config.robot("Rush")

NAME = ENTRY["name"]
ACTOR = os.environ.get("RUSH_ACTOR", ENTRY["actor"])
MODEL = os.environ.get("RUSH_MODEL", ENTRY["model"].removeprefix("ollama:"))
SIGNOFF = f"— {NAME} ({ENTRY['dln']}, {ACTOR})"

# Board tasks Rush watches for new comments.
WATCH_TASKS = [t for t in os.environ.get("RUSH_WATCH_TASKS", "").split(",") if t]

HOME = config.VAR / "rush"

# memory.md is local and git-ignored: it describes the people and boards Rush works with.
# memory.example.md is the committed template.
MEMORY = HERE / "memory.md"


def system_prompt(text=""):
    """Persona + memory + skills; on-match skills load when `text` triggers them."""
    memory = MEMORY if MEMORY.exists() else HERE / "memory.example.md"
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part
        for part in (
            (HERE / "persona.md").read_text(),
            memory.read_text(),
            skills.render(loaded, text),
        )
        if part
    )
