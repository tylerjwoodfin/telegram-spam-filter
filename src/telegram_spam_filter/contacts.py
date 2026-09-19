"""Cached set of Telegram contact user IDs."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from telethon import TelegramClient, events, functions, types
from telethon.tl.types.contacts import Contacts, ContactsNotModified

from telegram_spam_filter.client import invoke_with_flood_wait
from telegram_spam_filter.logging_config import log

logger = logging.getLogger("telegram_spam_filter.contacts")

CONTACT_UPDATE_TYPES = (
    types.UpdateContactsReset,
    types.UpdatePeerSettings,
)


def extract_contact_ids(result: object) -> set[int] | None:
    """Return contact IDs from a GetContacts result, or None if unchanged."""
    if isinstance(result, ContactsNotModified):
        return None
    contacts = getattr(result, "contacts", None)
    if isinstance(result, Contacts) or contacts is not None:
        ids: set[int] = set()
        for contact in contacts or ():
            user_id = getattr(contact, "user_id", None)
            if isinstance(user_id, int) and user_id > 0:
                ids.add(user_id)
        users = getattr(result, "users", None) or ()
        for user in users:
            if getattr(user, "contact", False) and isinstance(getattr(user, "id", None), int):
                ids.add(int(user.id))
        return ids
    return set()


class ContactSource(Protocol):
    def ids(self) -> set[int]: ...

    def contains(self, user_id: int) -> bool: ...


class ContactCache:
    def __init__(self) -> None:
        self._ids: set[int] = set()

    def ids(self) -> set[int]:
        return set(self._ids)

    def contains(self, user_id: int) -> bool:
        return user_id in self._ids

    def replace(self, ids: set[int]) -> None:
        self._ids = set(ids)

    async def refresh(self, client: TelegramClient) -> None:
        result = await invoke_with_flood_wait(
            lambda: client(functions.contacts.GetContactsRequest(hash=0)),
            action="get_contacts",
        )
        extracted = extract_contact_ids(result)
        if extracted is None:
            log(logger, logging.DEBUG, "contacts_not_modified", count=len(self._ids))
            return
        self.replace(extracted)
        log(logger, logging.INFO, "contacts_refreshed", count=len(self._ids))

    def should_refresh_for_update(self, update: Any) -> bool:
        return isinstance(update, CONTACT_UPDATE_TYPES)

    def register(self, client: TelegramClient) -> None:
        @client.on(events.Raw)  # type: ignore[untyped-decorator]
        async def _on_raw(event: Any) -> None:
            if self.should_refresh_for_update(event):
                await self.refresh(client)
