"""Source registry. Add a source: implement `Source` in its own module, register it here."""

from __future__ import annotations

from light_labs.radar.sources.addressbook import AddressBookSource
from light_labs.radar.sources.base import Source
from light_labs.radar.sources.contacts import ContactsSource
from light_labs.radar.sources.imessage import IMessageSource


def registry() -> dict[str, Source]:
    # Contacts first: names and cards anchor people before handles arrive. The Mac's
    # Contacts databases (through the helper) need nothing from PJ; a vCard export from
    # a phone is optional.
    sources: list[Source] = [AddressBookSource(), ContactsSource(), IMessageSource()]
    return {s.name: s for s in sources}
