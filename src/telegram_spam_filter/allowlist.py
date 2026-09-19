"""Local numeric-ID allowlist. Allowlisted senders skip the non-contact filter."""

from __future__ import annotations

from pathlib import Path

from telegram_spam_filter.state import StateStore


class InvalidUserIdError(ValueError):
    """Raised when a user ID is not a positive integer."""


def parse_user_id(raw: str) -> int:
    text = raw.strip()
    if not text or any(ch in text for ch in "*?[]"):
        raise InvalidUserIdError("Allowlist entries must be a single numeric Telegram user ID.")
    if not text.isdigit() and not (text.startswith("-") and text[1:].isdigit()):
        raise InvalidUserIdError(
            "Allowlist entries must be a numeric Telegram user ID, not a username."
        )
    user_id = int(text)
    if user_id <= 0:
        raise InvalidUserIdError("Telegram user IDs must be positive integers.")
    return user_id


class Allowlist:
    def __init__(self, store: StateStore) -> None:
        self._store = store

    @classmethod
    def from_path(cls, path: Path) -> Allowlist:
        return cls(StateStore(path))

    def ids(self) -> set[int]:
        return self._store.allowlist_ids()

    def contains(self, user_id: int) -> bool:
        return user_id in self.ids()

    def add(self, user_id: int) -> bool:
        if user_id <= 0:
            raise InvalidUserIdError("Telegram user IDs must be positive integers.")
        return self._store.add_allow(user_id)

    def remove(self, user_id: int) -> bool:
        if user_id <= 0:
            raise InvalidUserIdError("Telegram user IDs must be positive integers.")
        return self._store.remove_allow(user_id)
