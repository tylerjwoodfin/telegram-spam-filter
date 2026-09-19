"""SQLite persistence for filtered dialogs and the local allowlist."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from telegram_spam_filter.security import chmod_private_file, ensure_private_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS filtered_dialogs (
    user_id INTEGER PRIMARY KEY,
    archived INTEGER NOT NULL DEFAULT 0,
    muted INTEGER NOT NULL DEFAULT 0,
    last_attempt_unix INTEGER,
    last_success_unix INTEGER
);

CREATE TABLE IF NOT EXISTS allowlist (
    user_id INTEGER PRIMARY KEY,
    added_unix INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class DialogState:
    user_id: int
    archived: bool
    muted: bool
    last_attempt_unix: int | None
    last_success_unix: int | None

    @property
    def complete(self) -> bool:
        return self.archived and self.muted


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        ensure_private_dir(path.parent)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        chmod_private_file(self.path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_dialog(self, user_id: int) -> DialogState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, archived, muted, last_attempt_unix, last_success_unix "
                "FROM filtered_dialogs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return DialogState(
            user_id=int(row["user_id"]),
            archived=bool(row["archived"]),
            muted=bool(row["muted"]),
            last_attempt_unix=row["last_attempt_unix"],
            last_success_unix=row["last_success_unix"],
        )

    def list_filtered(self) -> list[DialogState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, archived, muted, last_attempt_unix, last_success_unix "
                "FROM filtered_dialogs"
            ).fetchall()
        return [
            DialogState(
                user_id=int(row["user_id"]),
                archived=bool(row["archived"]),
                muted=bool(row["muted"]),
                last_attempt_unix=row["last_attempt_unix"],
                last_success_unix=row["last_success_unix"],
            )
            for row in rows
        ]

    def record_attempt(
        self,
        user_id: int,
        *,
        archived: bool,
        muted: bool,
        success: bool,
    ) -> DialogState:
        now = int(time.time())
        existing = self.get_dialog(user_id)
        archived_flag = 1 if archived else 0
        muted_flag = 1 if muted else 0
        last_success = now if success else (existing.last_success_unix if existing else None)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO filtered_dialogs (
                    user_id, archived, muted, last_attempt_unix, last_success_unix
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    archived = excluded.archived,
                    muted = excluded.muted,
                    last_attempt_unix = excluded.last_attempt_unix,
                    last_success_unix = excluded.last_success_unix
                """,
                (user_id, archived_flag, muted_flag, now, last_success),
            )
        result = self.get_dialog(user_id)
        assert result is not None
        return result

    def allowlist_ids(self) -> set[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_id FROM allowlist").fetchall()
        return {int(row["user_id"]) for row in rows}

    def add_allow(self, user_id: int) -> bool:
        """Return True if the ID was newly inserted."""
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO allowlist (user_id, added_unix) VALUES (?, ?)",
                (user_id, now),
            )
            return cursor.rowcount > 0

    def remove_allow(self, user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM allowlist WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
