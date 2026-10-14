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


def system_prompt(text=""):
    """Persona + skills; on-match skills load when `text` triggers them."""
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part for part in ((HERE / "persona.md").read_text(), skills.render(loaded, text)) if part
    )
