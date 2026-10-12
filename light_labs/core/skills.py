"""Skills in Claude Code's format, readable by the lab's robots too.

One directory, `.claude/skills/<name>/SKILL.md`, serves both audiences. Claude Code (Auto)
loads it natively; robots load the skills their `dln.json` entry lists. Frontmatter:

    name: escalate-to-auto
    description: one line, used in the index
    audience: [robots, auto]       # who the skill is written for
    load: always | on-match        # robots only: always in the prompt, or when triggered
    triggers: [build, code, ...]   # robots only: words that pull an on-match skill in

Small local models have small context windows, so robots get the full text of `always`
skills plus any `on-match` skill whose trigger appears in the work at hand; the rest are a
one-line index entry.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from light_labs import config

SKILLS_DIR = config.REPO / ".claude" / "skills"


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    audience: list = field(default_factory=list)
    load: str = "on-match"
    triggers: list = field(default_factory=list)

    def matches(self, text):
        return any(re.search(rf"\b{re.escape(t)}", text, re.IGNORECASE) for t in self.triggers)


def _value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
    return raw.strip("'\"")


def parse(path):
    """Read a SKILL.md: flat `key: value` frontmatter (lists as [a, b]) and a body."""
    text = Path(path).read_text()
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path}: missing --- frontmatter ---")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "#")):
            key, _, raw = line.partition(":")
            meta[key.strip()] = _value(raw)
    for required in ("name", "description"):
        if not meta.get(required):
            raise ValueError(f"{path}: frontmatter needs {required}")
    audience = meta.get("audience", [])
    triggers = meta.get("triggers", [])
    return Skill(
        name=meta["name"],
        description=meta["description"],
        body=match.group(2).strip(),
        path=Path(path),
        audience=[audience] if isinstance(audience, str) else audience,
        load=meta.get("load", "on-match"),
        triggers=[triggers] if isinstance(triggers, str) else triggers,
    )


def discover(root=SKILLS_DIR):
    return {s.name: s for s in (parse(p) for p in sorted(Path(root).glob("*/SKILL.md")))}


def for_robot(names, root=SKILLS_DIR):
    """The skills a robot carries, in registry order. Unknown names are an error."""
    found = discover(root)
    missing = [n for n in names if n not in found]
    if missing:
        raise KeyError(f"skills not found in {root}: {', '.join(missing)}")
    return [found[n] for n in names]


def render(skills, text=""):
    """System-prompt section: full text of always/matched skills, one line for the rest."""
    if not skills:
        return ""
    loaded = [s for s in skills if s.load == "always" or s.matches(text)]
    rest = [s for s in skills if s not in loaded]
    parts = ["# Skills"]
    for s in loaded:
        parts.append(f"## {s.name}\n\n{s.body}")
    if rest:
        parts.append(
            "Other skills you have (not loaded for this message):\n"
            + "\n".join(f"- {s.name}: {s.description}" for s in rest)
        )
    return "\n\n".join(parts)
