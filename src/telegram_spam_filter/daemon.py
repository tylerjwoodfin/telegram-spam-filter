"""Foreground daemon that archives and mutes new non-contact private chats."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

from telethon import TelegramClient, events, types
from telethon.errors import FloodPremiumWaitError, FloodWaitError

from telegram_spam_filter.actions import (
    DialogActions,
    TelethonDialogActions,
    apply_archive_and_mute,
    dialog_is_archived,
    dialog_is_muted,
)
from telegram_spam_filter.allowlist import Allowlist
from telegram_spam_filter.client import connected_client
from telegram_spam_filter.config import Settings
from telegram_spam_filter.contacts import ContactCache, ContactSource
from telegram_spam_filter.exceptions import DaemonAlreadyRunningError
from telegram_spam_filter.logging_config import log
from telegram_spam_filter.policy import IncomingMessage, should_filter
from telegram_spam_filter.security import chmod_private_file, ensure_private_dir
from telegram_spam_filter.state import StateStore

logger = logging.getLogger("telegram_spam_filter.daemon")


class SingletonLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        ensure_private_dir(self.path.parent)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise DaemonAlreadyRunningError(
                f"Another telegram-spam-filter daemon holds {self.path}. "
                "Stop it before starting a second instance."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        chmod_private_file(self.path)
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> SingletonLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


def read_daemon_pid(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


@dataclass
class FilterEngine:
    store: StateStore
    allowlist: Allowlist
    contacts: ContactSource
    actions: DialogActions
    me_id: int

    async def handle_message(self, message: IncomingMessage) -> str:
        if not should_filter(message, self.contacts.ids(), self.allowlist.ids()):
            return "ignored"
        result = await apply_archive_and_mute(self.actions, self.store, message.user_id)
        if result.skipped:
            return "idempotent"
        if result.complete:
            return "filtered"
        return "partial"

    async def revalidate(self, client: TelegramClient) -> None:
        for state in self.store.list_filtered():
            if self.allowlist.contains(state.user_id) or self.contacts.contains(state.user_id):
                continue
            need_archive = True
            need_mute = True
            try:
                archived = await dialog_is_archived(client, state.user_id)
                muted = await dialog_is_muted(client, state.user_id)
            except (FloodWaitError, FloodPremiumWaitError) as exc:
                log(
                    logger,
                    logging.WARNING,
                    "revalidate_flood_wait",
                    user_id=state.user_id,
                    seconds=exc.seconds,
                )
                continue
            if archived is False:
                need_archive = True
            elif archived is True:
                need_archive = False
            if muted is False:
                need_mute = True
            elif muted is True:
                need_mute = False
            if not need_archive and not need_mute:
                if not state.complete:
                    self.store.record_attempt(
                        state.user_id, archived=True, muted=True, success=True
                    )
                continue
            if need_archive or need_mute:
                await apply_archive_and_mute(
                    self.actions,
                    self.store,
                    state.user_id,
                    force_archive=need_archive,
                    force_mute=need_mute,
                )


def snapshot_event(event: Any, me_id: int, sender: Any) -> IncomingMessage | None:
    message = getattr(event, "message", None)
    if message is None:
        return None
    user_id = getattr(sender, "id", None)
    if not isinstance(user_id, int):
        sender_id = getattr(event, "sender_id", None)
        if not isinstance(sender_id, int):
            return None
        user_id = sender_id
    action = getattr(message, "action", None)
    is_service = action is not None or type(message).__name__ == "MessageService"
    is_self = bool(getattr(sender, "is_self", False)) or user_id == me_id
    return IncomingMessage(
        user_id=user_id,
        is_private=bool(getattr(event, "is_private", False)),
        is_outgoing=bool(getattr(message, "out", False)),
        is_group=bool(getattr(event, "is_group", False)),
        is_channel=bool(getattr(event, "is_channel", False)),
        is_bot=bool(getattr(sender, "bot", False)),
        is_self=is_self,
        is_service=is_service,
        is_saved_messages=is_self or getattr(event, "chat_id", None) == me_id,
    )


async def _periodic(stop: asyncio.Event, interval: float, callback: Any) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            await callback()


async def run_daemon(settings: Settings) -> None:
    with SingletonLock(settings.lock_path):
        store = StateStore(settings.state_path)
        allowlist = Allowlist(store)
        contacts = ContactCache()
        async with connected_client(settings) as client:
            me = await client.get_me()
            me_id = int(me.id)
            await contacts.refresh(client)
            contacts.register(client)
            engine = FilterEngine(
                store=store,
                allowlist=allowlist,
                contacts=contacts,
                actions=TelethonDialogActions(client),
                me_id=me_id,
            )

            @client.on(events.NewMessage(incoming=True))  # type: ignore[untyped-decorator]
            async def _on_message(event: Any) -> None:
                sender = await event.get_sender()
                if sender is None or not isinstance(sender, (types.User,)):
                    # Telethon may return a custom User; accept objects with an id.
                    if sender is None or not hasattr(sender, "id"):
                        return
                snapshot = snapshot_event(event, me_id, sender)
                if snapshot is None:
                    return
                await engine.handle_message(snapshot)

            stop = asyncio.Event()

            def _request_stop(signum: int, frame: FrameType | None) -> None:
                del signum, frame
                stop.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop.set)
                except NotImplementedError:
                    signal.signal(sig, _request_stop)

            log(logger, logging.INFO, "daemon_started", me_id=me_id)

            refresh_task = asyncio.create_task(
                _periodic(stop, settings.contacts_refresh_seconds, lambda: contacts.refresh(client))
            )
            revalidate_task = asyncio.create_task(
                _periodic(stop, settings.revalidate_seconds, lambda: engine.revalidate(client))
            )
            disconnected = asyncio.create_task(client.run_until_disconnected())
            stopper = asyncio.create_task(stop.wait())
            try:
                done, _pending = await asyncio.wait(
                    {disconnected, stopper},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stopper in done:
                    await client.disconnect()
            finally:
                stop.set()
                refresh_task.cancel()
                revalidate_task.cancel()
                disconnected.cancel()
                stopper.cancel()
                log(logger, logging.INFO, "daemon_stopped")
