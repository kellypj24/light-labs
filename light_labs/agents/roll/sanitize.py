"""The sanitized view of an email: what may leave the laptop for the teacher.

docs/plans/roll-keep.md step 4b. Personal mail never leaves: a consumer mailbox
(gmail.com and the like), or a domain that carries the sender's own name (a family or
vanity domain). Roll keeps it as `keep/people`. Everything else goes as its sender
domain, Gmail category, unsubscribe flag, and subject and snippet with amounts, numbers,
ids, email addresses, URLs, phone numbers and the sender's own name replaced by
placeholders. No display name, no local part. Scrubbing is local and rule-based; names
other than the sender's are not caught yet (the weapon-brain pass comes later).
"""

import re
from email.utils import parseaddr

from light_labs.agents.rush.mail import SNIPPET_CHARS

# Consumer mailboxes and relays: a sender here is a person, not an organization.
PERSONAL = re.compile(
    r"(?:gmail|googlemail|hotmail|outlook|live|msn|icloud|me|mac|aol|aim|proton|protonmail"
    r"|pm|fastmail|gmx|yandex|zoho|hey|comcast|verizon|att|sbcglobal|bellsouth|cox|charter"
    r"|ymail|yahoo|rocketmail|mail|duck|qq|163|web|t-online|orange|free|btinternet|shaw"
    r"|rogers|sympatico|privaterelay\.appleid)"
    r"\.(?:com|net|org|me|de|fr|co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2})"
)

# Words a sender's name shares with what the mail is about: kept, so the teacher still
# sees "Security alert" from "Google Security" and "orders" from orders@.
SIGNAL = frozenset(
    {
        "account", "accounts", "alert", "alerts", "billing", "bank", "card", "customer", "deals",
        "delivery", "digest", "email", "info", "jobs", "mail", "marketing", "news", "newsletter",
        "no", "noreply", "no-reply", "notification", "notifications", "offers", "order", "orders",
        "payments", "receipts", "reply", "security", "service", "shipping", "shop", "store",
        "support", "team", "updates", "the", "and",
    }
)  # fmt: skip

# Order matters: an email address holds digits and a URL holds an address-like part.
PATTERNS = (
    ("<email>", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("<url>", re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)),
    ("<id>", re.compile(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,}\b", re.IGNORECASE)),
    (
        "<amount>",
        re.compile(
            r"[$€£¥]\s?\d+(?:,\d{3})*(?:\.\d+)?"
            r"|\b(?:USD|EUR|GBP)\s?\d+(?:,\d{3})*(?:\.\d+)?"
            r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b"
        ),
    ),
    ("<phone>", re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    ("<number>", re.compile(r"\d(?:[ -]?\d){3,}")),  # 4+ digits, single space or hyphen apart
)


def sender(from_):
    """(display name, local part, domain) of a From header, the last two lowercased."""
    name, addr = parseaddr(from_ or "")
    local, _, domain = addr.lower().rpartition("@")
    return name.strip().strip('"'), local, domain


def _name_words(name, local):
    words = re.findall(r"[^\W\d_]{3,}", f"{name} {local}".lower())
    return {w for w in words if w not in SIGNAL}


def is_personal(item):
    """A consumer mailbox, or a domain carrying a word of a person-shaped name (two or
    more words, as in "Dana Whitfield" at whitfield.net). A brand ("Google Security" at
    google.com) is one word once SIGNAL is dropped; a two-word brand at its own domain
    ("Home Depot") counts as personal, which keeps it local: the safe miss."""
    name, _, domain = sender(item.get("from"))
    if PERSONAL.fullmatch(domain):
        return True
    words = _name_words(name, "")
    labels = domain.split(".")[:-1]  # skip the TLD
    return len(words) >= 2 and any(w in label for w in words for label in labels)


def scrub(text, names=()):
    """`text` with PATTERNS and each word of `names` (3+ letters) replaced."""
    text = text or ""
    for placeholder, pattern in PATTERNS:
        text = pattern.sub(placeholder, text)
    for w in sorted(names, key=len, reverse=True):
        # never inside a placeholder like <phone>
        text = re.sub(rf"(?<![\w<]){re.escape(w)}(?![\w>])", "<name>", text, flags=re.IGNORECASE)
    return text


def view(item):
    """What the teacher may see of `item`. The caller has already skipped personal mail."""
    name, local, domain = sender(item.get("from"))
    names = _name_words(name, local)
    return {
        "sender_domain": domain,
        "domain_kind": "unknown",  # bank, retailer, school: the matchers' domain table
        "category": item.get("category"),
        "unsubscribe": bool(item.get("unsubscribe")),
        "subject": scrub(item.get("subject"), names),
        "snippet": scrub((item.get("snippet") or "")[:SNIPPET_CHARS], names),
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
