"""Paths and settings. Everything personal lives under RADAR_HOME, never in the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DRIVE_GLOB = "GoogleDrive-*/My Drive/Relationship Radar"


def radar_home() -> Path:
    return Path(os.environ.get("RADAR_HOME", Path.home() / ".relationship-radar"))


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "radar.duckdb"

    @property
    def inbox(self) -> Path:
        """Files that sources read: the helper's export, Contacts vCards, LinkedIn zips."""
        return self.home / "inbox"

    @property
    def messages_export(self) -> Path:
        return self.inbox / "messages.jsonl"

    @property
    def contacts_export(self) -> Path:
        return self.inbox / "contacts.jsonl"

    @property
    def contacts_dir(self) -> Path:
        return self.inbox / "contacts"

    @property
    def digests(self) -> Path:
        return self.home / "digests"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def bin(self) -> Path:
        return self.home / "bin"

    @property
    def config(self) -> Path:
        return self.home / "config.yaml"

    @property
    def circles(self) -> Path:
        return self.home / "circles.yaml"

    @property
    def circles_proposed(self) -> Path:
        return self.home / "circles.proposed.yaml"

    @property
    def overrides(self) -> Path:
        return self.home / "overrides.yaml"

    @property
    def review_matches(self) -> Path:
        return self.home / "review_matches.csv"

    def ensure(self) -> None:
        """Create the private directories (0700): they hold who PJ talks to."""
        for d in (self.home, self.inbox, self.contacts_dir, self.digests, self.logs, self.bin):
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o700)


@dataclass
class Settings:
    default_region: str = "US"
    # Off unless config.yaml says `share_digest: true`: the shared digest carries names,
    # circles and birthdays off the machine (Google Drive, the cloud Claude task).
    share_digest: bool = False
    output_dir: Path | None = None  # where `weekly` writes the shared copy; None when off
    shared_dir: Path | None = None  # where a shared copy would be, on or off (for purge)
    former_employers: list[str] = field(default_factory=list)
    fuzzy_auto_merge: float = 0.95
    fuzzy_review_floor: float = 0.85
    two_way_window_days: int = 3

    @classmethod
    def load(cls, paths: Paths) -> Settings:
        raw: dict[str, Any] = {}
        if paths.config.exists():
            raw = yaml.safe_load(paths.config.read_text()) or {}
        s = cls()
        s.default_region = raw.get("default_region", s.default_region)
        s.former_employers = list(raw.get("former_employers", []))
        s.fuzzy_auto_merge = float(raw.get("fuzzy_auto_merge", s.fuzzy_auto_merge))
        s.fuzzy_review_floor = float(raw.get("fuzzy_review_floor", s.fuzzy_review_floor))
        s.two_way_window_days = int(raw.get("two_way_window_days", s.two_way_window_days))
        out = raw.get("output_dir")
        s.share_digest = raw.get("share_digest") is True
        s.shared_dir = Path(out).expanduser() if out else default_output_dir()
        s.output_dir = s.shared_dir if s.share_digest else None
        return s


def default_output_dir() -> Path | None:
    """Google Drive for Desktop's folder, if installed; None means local copies only."""
    cloud = Path.home() / "Library" / "CloudStorage"
    matches = sorted(cloud.glob(DRIVE_GLOB.rsplit("/", 1)[0])) if cloud.exists() else []
    return matches[0] / "Relationship Radar" if matches else None
