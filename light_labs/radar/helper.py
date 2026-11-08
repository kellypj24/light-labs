"""Build, install and trigger the Messages export helper (the only code with Full Disk Access).

The helper runs as its own LaunchAgent so macOS attributes its file access to the helper
binary, not to the terminal that started `lab radar sync`.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

from light_labs.radar.config import Paths

LABEL = "com.pjkelly.relationship-radar.messages-export"
BINARY = "radar-messages-export"
SOURCE = Path(__file__).resolve().parent / "helper" / f"{BINARY}.swift"


def binary_path(paths: Paths) -> Path:
    return paths.bin / BINARY


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build(paths: Paths, snippets: bool = False) -> Path:
    """Compile and ad-hoc sign with the hardened runtime. A rebuild invalidates the FDA grant."""
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    paths.ensure()
    out = binary_path(paths)
    cmd = ["swiftc", "-O", "-o", str(out), str(SOURCE), "-lsqlite3"]
    if snippets:
        cmd += ["-D", "RADAR_SNIPPETS"]
    subprocess.run(cmd, check=True)
    subprocess.run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            "--options",
            "runtime",
            "--identifier",
            LABEL,
            str(out),
        ],
        check=True,
    )
    return out


def plist(paths: Paths) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(binary_path(paths))],
        "RunAtLoad": False,
        # 06:20 daily, ahead of the 06:30 sync; `lab radar sync` also kicks it on demand.
        "StartCalendarInterval": {"Hour": 6, "Minute": 20},
        "StandardOutPath": str(paths.logs / "messages-export.log"),
        "StandardErrorPath": str(paths.logs / "messages-export.log"),
        "ProcessType": "Background",
    }


def install(paths: Paths) -> Path:
    if not binary_path(paths).exists():
        raise FileNotFoundError(f"{binary_path(paths)}: run `lab radar helper build` first")
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps(plist(paths)))
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    _launchctl("bootstrap", _domain(), str(p))
    return p


def uninstall() -> None:
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    plist_path().unlink(missing_ok=True)


def is_loaded() -> bool:
    return _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0


def kick(paths: Paths, timeout: float = 120) -> bool:
    """Start the helper now and wait for a fresh export. False if not installed or timed out."""
    if not is_loaded():
        return False
    out = paths.messages_export
    before = out.stat().st_mtime_ns if out.exists() else 0
    _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if out.exists() and out.stat().st_mtime_ns != before:
            return True
        time.sleep(1)
    return False


def last_log_line(paths: Paths) -> str | None:
    log = paths.logs / "messages-export.log"
    if not log.exists():
        return None
    lines = log.read_text(errors="replace").strip().splitlines()
    return lines[-1] if lines else None


def swiftc_available() -> bool:
    return shutil.which("swiftc") is not None


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)
