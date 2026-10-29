"""The sanitized view of an email: what may leave the laptop for the teacher.

docs/plans/roll-keep.md step 4b. Mail from a consumer mailbox (gmail.com and the like) is
personal and never leaves: Roll keeps it as `keep/people`. Everything else goes as its
sender domain, Gmail category, unsubscribe flag, and subject and snippet with amounts,
numbers, email addresses, URLs, phone numbers and the sender's own name replaced by
placeholders. No display name, no local part. Scrubbing is local and rule-based; names
other than the sender's are not caught yet (the weapon-brain pass comes later).
"""

import re
from email.utils import parseaddr

# Consumer mailbox providers: a sender here is a person, not an organization.
PERSONAL = re.compile(
    r"(gmail|googlemail|hotmail|outlook|live|msn|icloud|me|mac|aol|proton|protonmail|pm"
    r"|fastmail|gmx|yandex|zoho|hey|comcast|verizon|att|sbcglobal|ymail|yahoo)"
    r"\.(?:com|net|org|me|co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2})"
)

# Order matters: an email address holds digits and a URL holds an address-like part.
PATTERNS = (
    ("<email>", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("<url>", re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)),
    (
        "<amount>",
        re.compile(
            r"(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|dollars)\b)"
        ),
    ),
    ("<phone>", re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("<number>", re.compile(r"\d[\d\s-]{2,}\d")),  # any digit run of 4 or more, spaced or not
)


def sender(from_):
    """(display name, domain) of a From header; domain lowercased, "" if none."""
    name, addr = parseaddr(from_ or "")
    return name.strip().strip('"'), addr.rpartition("@")[2].lower()


def is_personal(item):
    _, domain = sender(item.get("from"))
    return bool(PERSONAL.fullmatch(domain))


def scrub(text, names=()):
    """`text` with PATTERNS and each of `names` (and their words of 3+ letters) replaced."""
    text = text or ""
    for placeholder, pattern in PATTERNS:
        text = pattern.sub(placeholder, text)
    words = {w for n in names if n for w in [n, *re.findall(r"[^\W\d_]{3,}", n)]}
    for w in sorted(words, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(w)}\b", "<name>", text, flags=re.IGNORECASE)
    return text


def view(item):
    """What the teacher may see of `item`. Raises ValueError for personal mail."""
    if is_personal(item):
        raise ValueError("personal mail stays local")
    name, domain = sender(item.get("from"))
    local = parseaddr(item.get("from") or "")[1].partition("@")[0]
    names = (name, local)
    return {
        "sender_domain": domain,
        "domain_kind": "unknown",  # bank, retailer, school: the matchers' domain table
        "category": item.get("category"),
        "unsubscribe": bool(item.get("unsubscribe")),
        "subject": scrub(item.get("subject"), names),
        "snippet": scrub(item.get("snippet"), names),
    }


def prompt(v):
    """A sanitized view as the teacher reads it."""
    return (
        f"Email from a sender at {v['sender_domain']} ({v['domain_kind']}), "
        f'"{v["subject"]}"\n'
        f"Gmail category: {v['category'] or 'primary'}. "
        f"Unsubscribe header: {'yes' if v['unsubscribe'] else 'no'}.\n"
        f"Text: {v['snippet']}"
    )
