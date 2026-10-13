"""Lab-wide settings, from LAB_* environment variables or a git-ignored .env file."""

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DLN = REPO / "dln.json"


def load_env(path=REPO / ".env"):
    """Read KEY=VALUE lines into os.environ without overriding values already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env()

# Agent Net edge base URL. Deployment-specific, so there is no default.
EDGE = os.environ.get("LAB_EDGE", "")
KEYCHAIN_SERVICE = os.environ.get("LAB_KEYCHAIN_SERVICE", "agentnet")
OLLAMA = os.environ.get("LAB_OLLAMA", "http://localhost:11434")

VAR = Path(os.environ.get("LAB_VAR", REPO / "var"))


def git_state():
    """(short commit, dirty) of the lab's checkout, or (None, None) outside git."""
    import subprocess

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
        )

    head = git("rev-parse", "--short", "HEAD")
    if head.returncode:
        return None, None
    return head.stdout.strip(), bool(git("status", "--porcelain").stdout.strip())


def robot(name):
    """Registry entry for a robot, by name (case-insensitive)."""
    for r in json.loads(DLN.read_text())["robots"]:
        if r["name"].lower() == name.lower():
            return r
    raise KeyError(f"no robot named {name} in {DLN.name}")


def roster():
    return json.loads(DLN.read_text())["robots"]
