"""Approve, build, install and trigger the Messages export helper (the only code with
Full Disk Access).

The binary is compiled only from the copy PJ approved (`lab radar helper approve`, which
needs an interactive terminal and shows the diff since the last approval), never straight
from the repo. A change merged to the repo reaches the binary only after PJ reads it.

The helper runs as its own LaunchAgent so macOS attributes its file access to the helper
binary, not to the terminal that started `lab radar sync`.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from light_labs.radar.config import Paths

LABEL = "com.pjkelly.relationship-radar.messages-export"
# Apple's tools by absolute path, with a minimal environment: a fake `codesign` early in
# PATH, or DEVELOPER_DIR / DYLD_* in the shell, would otherwise decide what binary PJ
# grants Full Disk Access to.
XCRUN = "/usr/bin/xcrun"
CODESIGN = "/usr/bin/codesign"
LAUNCHCTL = "/bin/launchctl"


def tool_env() -> dict[str, str]:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())}
    if "TMPDIR" in os.environ:
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


BINARY = "radar-messages-export"
SOURCE = Path(__file__).resolve().parent / "helper" / f"{BINARY}.swift"


def binary_path(paths: Paths) -> Path:
    return paths.bin / BINARY


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def approved_path(paths: Paths) -> Path:
    return paths.bin / "approved.swift"


def built_from_path(paths: Paths) -> Path:
    return paths.bin / f"{BINARY}.source-sha256"


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class NotApproved(RuntimeError):
    pass


def approve(
    paths: Paths,
    source: Path | None = None,
    ask: Callable[[str], str] = input,
    interactive: Callable[[], bool] = lambda: sys.stdin.isatty(),
) -> bool:
    """Show the repo source's diff against the approved copy; on `approve`, replace it.

    Needs a terminal: a robot or a script can't approve, only PJ at the keyboard."""
    source = source or SOURCE
    if not interactive():
        raise NotApproved("approving the helper needs an interactive terminal")
    paths.ensure()
    approved = approved_path(paths)
    old = approved.read_text().splitlines(keepends=True) if approved.exists() else []
    new = source.read_text().splitlines(keepends=True)
    if old == new:
        print(f"already approved: {sha256(approved)}")
        return True
    diff = difflib.unified_diff(old, new, "approved.swift", str(source))
    print("".join(diff) if old else source.read_text())
    print(f"\nsha256 {hashlib.sha256(''.join(new).encode()).hexdigest()}")
    print('Read all of it against docs/radar.md "Reviewing the helper".')
    if ask("type 'approve' to approve this source: ").strip() != "approve":
        print("not approved")
        return False
    approved.write_text("".join(new))
    approved.chmod(0o600)
    print(f"approved {approved}; now `lab radar helper build` and re-grant Full Disk Access")
    return True


def build(paths: Paths, snippets: bool = False) -> Path:
    """Compile the approved copy and ad-hoc sign it with the hardened runtime.

    A rebuild changes the binary's hash, which invalidates the FDA grant."""
    approved = approved_path(paths)
    if not approved.exists():
        raise NotApproved("no approved helper source: run `lab radar helper approve` first")
    paths.ensure()
    out = binary_path(paths)
    cmd = [XCRUN, "swiftc", "-O", "-o", str(out), str(approved), "-lsqlite3"]
    if snippets:
        cmd += ["-D", "RADAR_SNIPPETS"]
    subprocess.run(cmd, check=True, env=tool_env())
    subprocess.run(
        [
            CODESIGN,
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
        env=tool_env(),
    )
    built_from_path(paths).write_text(f"{sha256(approved)}\n")
    return out


def source_state(paths: Paths, source: Path | None = None) -> dict[str, str | None]:
    """Hashes of the repo source, the approved copy and the copy the binary was built from."""
    built = built_from_path(paths)
    return {
        "repo": sha256(source or SOURCE),
        "approved": sha256(approved_path(paths)),
        "built": built.read_text().strip() if built.exists() else None,
    }


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
    return Path(XCRUN).exists() and shutil.which("swiftc", path="/usr/bin") is not None


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [LAUNCHCTL, *args], capture_output=True, text=True, check=check, env=tool_env()
    )
