"""Identity normalization: phones to E.164, emails lowercased, names folded."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import phonenumbers

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def phone(raw: str, region: str = "US") -> str | None:
    try:
        n = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(n):
        return None
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)


def email(raw: str) -> str | None:
    v = raw.strip().lower().removeprefix("mailto:")
    return v if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) else None


def handle(raw: str, region: str = "US") -> tuple[str, str] | None:
    """A Messages handle is a phone or an email. Short codes and business ids return None."""
    if "@" in raw:
        e = email(raw)
        return ("email", e) if e else None
    p = phone(raw, region)
    return ("phone", p) if p else None


def identity_ref(raw: str, region: str = "US") -> tuple[str, str] | None:
    """Parse a reference typed by PJ in overrides/circles: email, phone or LinkedIn URL."""
    raw = raw.strip()
    url = linkedin_url(raw)
    if url:
        return ("linkedin_url", url)
    if "@" in raw:
        e = email(raw)
        return ("email", e) if e else None
    if re.fullmatch(r"[+\d\s().-]{7,}", raw):
        p = phone(raw, region)
        return ("phone", p) if p else None
    return None


def linkedin_url(raw: str) -> str | None:
    """Canonical profile URL, or None unless the host is linkedin.com or a subdomain."""
    v = raw.strip().lower()
    parts = urlsplit(v if "://" in v else f"https://{v}")
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not (
        host == "linkedin.com" or host.endswith(".linkedin.com")
    ):
        return None
    path = parts.path.rstrip("/")
    return f"https://www.linkedin.com{path}" if path else None


def name(raw: str) -> str:
    """Fold for matching: no accents, no punctuation, lowercase, single spaces."""
    v = unicodedata.normalize("NFKD", raw)
    v = "".join(c for c in v if not unicodedata.combining(c))
    v = re.sub(r"[^\w\s]", " ", v.lower())
    return " ".join(v.split())


def apple_time(value: int) -> datetime:
    """chat.db dates: nanoseconds since 2001-01-01 since macOS 10.13, seconds before."""
    seconds = value / 1e9 if abs(value) > 10**11 else float(value)
    return APPLE_EPOCH + timedelta(seconds=seconds)


def stable_id(*parts: str, prefix: str = "", length: int = 16) -> str:
    return prefix + hashlib.sha256("|".join(parts).encode()).hexdigest()[:length]
