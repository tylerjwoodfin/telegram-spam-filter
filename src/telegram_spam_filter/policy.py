"""Decide which incoming private messages should be archived and muted."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IncomingMessage:
    user_id: int
    is_private: bool
    is_outgoing: bool
    is_group: bool
    is_channel: bool
    is_bot: bool
    is_self: bool
    is_service: bool
    is_saved_messages: bool


def should_consider(message: IncomingMessage) -> bool:
    """Return True only for inbound one-to-one user messages that are not from self."""
    if not message.is_private:
        return False
    if message.is_outgoing or message.is_group or message.is_channel:
        return False
    if message.is_bot or message.is_self or message.is_service or message.is_saved_messages:
        return False
    if message.user_id <= 0:
        return False
    return True


def is_trusted(user_id: int, contact_ids: set[int], allowlist_ids: set[int]) -> bool:
    """Local allowlist overrides the non-contact filter."""
    return user_id in allowlist_ids or user_id in contact_ids


def should_filter(message: IncomingMessage, contact_ids: set[int], allowlist_ids: set[int]) -> bool:
    return should_consider(message) and not is_trusted(message.user_id, contact_ids, allowlist_ids)
