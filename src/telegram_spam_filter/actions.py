"""Archive and permanently mute private dialogs via raw MTProto methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from telethon import TelegramClient, functions, types
from telethon.errors import FloodPremiumWaitError, FloodWaitError, RPCError

from telegram_spam_filter.client import invoke_with_flood_wait
from telegram_spam_filter.config import ARCHIVE_FOLDER_ID, MUTE_UNTIL_UNIX
from telegram_spam_filter.logging_config import log
from telegram_spam_filter.state import DialogState, StateStore

logger = logging.getLogger("telegram_spam_filter.actions")

MUTE_UNTIL = datetime.fromtimestamp(MUTE_UNTIL_UNIX, tz=UTC)


class DialogActions(Protocol):
    async def archive(self, user_id: int) -> None: ...

    async def mute(self, user_id: int) -> None: ...


@dataclass(frozen=True)
class ActionResult:
    user_id: int
    archived: bool
    muted: bool
    skipped: bool
    archive_error: str | None = None
    mute_error: str | None = None

    @property
    def complete(self) -> bool:
        return self.archived and self.muted


def _error_name(exc: BaseException) -> str:
    return type(exc).__name__


class TelethonDialogActions:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def _input_peer(self, user_id: int) -> types.TypeInputPeer:
        return await self._client.get_input_entity(user_id)

    async def archive(self, user_id: int) -> None:
        peer = await self._input_peer(user_id)

        async def _call() -> object:
            return await self._client(
                functions.folders.EditPeerFoldersRequest(
                    folder_peers=[types.InputFolderPeer(peer=peer, folder_id=ARCHIVE_FOLDER_ID)]
                )
            )

        await invoke_with_flood_wait(_call, action="archive")

    async def mute(self, user_id: int) -> None:
        peer = await self._input_peer(user_id)

        async def _call() -> object:
            return await self._client(
                functions.account.UpdateNotifySettingsRequest(
                    peer=types.InputNotifyPeer(peer=peer),
                    settings=types.InputPeerNotifySettings(mute_until=MUTE_UNTIL),
                )
            )

        await invoke_with_flood_wait(_call, action="mute")


async def apply_archive_and_mute(
    actions: DialogActions,
    store: StateStore,
    user_id: int,
    *,
    force_archive: bool = False,
    force_mute: bool = False,
) -> ActionResult:
    """Archive and mute a dialog, skipping completed work unless forced.

    Partial failures retry only the failed action on later messages.
    """
    existing = store.get_dialog(user_id)
    need_archive = force_archive or existing is None or not existing.archived
    need_mute = force_mute or existing is None or not existing.muted
    if not need_archive and not need_mute:
        log(logger, logging.INFO, "filter_idempotent", user_id=user_id)
        return ActionResult(user_id=user_id, archived=True, muted=True, skipped=True)

    archived = not need_archive
    muted = not need_mute
    archive_error: str | None = None
    mute_error: str | None = None

    if need_archive:
        try:
            await actions.archive(user_id)
            archived = True
            log(logger, logging.INFO, "archived", user_id=user_id)
        except (FloodWaitError, FloodPremiumWaitError) as exc:
            archive_error = f"{_error_name(exc)}:{exc.seconds}"
            log(
                logger,
                logging.WARNING,
                "archive_flood_wait",
                user_id=user_id,
                seconds=exc.seconds,
            )
        except RPCError as exc:
            archive_error = _error_name(exc)
            log(logger, logging.ERROR, "archive_failed", user_id=user_id, error=archive_error)
        except Exception as exc:
            archive_error = _error_name(exc)
            log(logger, logging.ERROR, "archive_failed", user_id=user_id, error=archive_error)

    if need_mute:
        try:
            await actions.mute(user_id)
            muted = True
            log(logger, logging.INFO, "muted", user_id=user_id)
        except (FloodWaitError, FloodPremiumWaitError) as exc:
            mute_error = f"{_error_name(exc)}:{exc.seconds}"
            log(
                logger,
                logging.WARNING,
                "mute_flood_wait",
                user_id=user_id,
                seconds=exc.seconds,
            )
        except RPCError as exc:
            mute_error = _error_name(exc)
            log(logger, logging.ERROR, "mute_failed", user_id=user_id, error=mute_error)
        except Exception as exc:
            mute_error = _error_name(exc)
            log(logger, logging.ERROR, "mute_failed", user_id=user_id, error=mute_error)

    if archive_error and muted:
        log(logger, logging.WARNING, "partial_failure", user_id=user_id, failed="archive")
    if mute_error and archived:
        log(logger, logging.WARNING, "partial_failure", user_id=user_id, failed="mute")

    complete = archived and muted
    store.record_attempt(user_id, archived=archived, muted=muted, success=complete)
    return ActionResult(
        user_id=user_id,
        archived=archived,
        muted=muted,
        skipped=False,
        archive_error=archive_error,
        mute_error=mute_error,
    )


async def dialog_is_archived(client: TelegramClient, user_id: int) -> bool | None:
    """Return archive status when a matching dialog can be found."""
    async for dialog in client.iter_dialogs():
        entity = getattr(dialog, "entity", None)
        if getattr(entity, "id", None) == user_id:
            folder_id = getattr(dialog, "folder_id", None) or getattr(
                getattr(dialog, "dialog", None), "folder_id", None
            )
            return int(folder_id or 0) == ARCHIVE_FOLDER_ID
    return None


async def dialog_is_muted(client: TelegramClient, user_id: int) -> bool | None:
    peer = await client.get_input_entity(user_id)
    settings = await invoke_with_flood_wait(
        lambda: client(
            functions.account.GetNotifySettingsRequest(peer=types.InputNotifyPeer(peer=peer))
        ),
        action="get_notify_settings",
    )
    mute_until = getattr(settings, "mute_until", None)
    if mute_until is None:
        return False
    if isinstance(mute_until, datetime):
        return mute_until > datetime.now(UTC)
    if isinstance(mute_until, (int, float)):
        return int(mute_until) > int(datetime.now(UTC).timestamp())
    return False


def pending_revalidation(state: DialogState) -> tuple[bool, bool]:
    """Return (need_archive_check, need_mute_check) for stored filtered dialogs."""
    return (not state.archived, not state.muted)
