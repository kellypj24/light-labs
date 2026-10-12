"""DLN-101 Guts Man: builds dbt models over the lab's eval data. In training."""

import os
from pathlib import Path

from light_labs import config
from light_labs.core import skills

HERE = Path(__file__).resolve().parent
ENTRY = config.robot("Guts Man")

NAME = ENTRY["name"]
# No model until the dbt-model fight picks one; set GUTS_MAN_MODEL to try one by hand.
MODEL = os.environ.get("GUTS_MAN_MODEL", "")


def system_prompt(text=""):
    """Persona + skills; on-match skills load when `text` triggers them."""
    loaded = skills.for_robot(ENTRY.get("skills", []))
    return "\n\n".join(
        part for part in ((HERE / "persona.md").read_text(), skills.render(loaded, text)) if part
    )
