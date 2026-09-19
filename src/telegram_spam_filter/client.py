"""Telethon user-client helpers. Authenticates as a personal MTProto user, never as a bot."""

from __future__ import annotations

import asyncio
import getpass
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    FloodPremiumWaitError,
    FloodWaitError,
    RPCError,
    SessionExpiredError,
    SessionRevokedError,
)

from telegram_spam_filter.config import MAX_ACTION_RETRIES, MAX_IMMEDIATE_FLOOD_WAIT, Settings
from telegram_spam_filter.exceptions import AuthExpiredError, ConfigError
from telegram_spam_filter.logging_config import log
from telegram_spam_filter.security import (
    check_runtime_paths,
    chmod_private_file,
    ensure_private_dir,
)

AUTH_ERRORS = (
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    SessionExpiredError,
    SessionRevokedError,
)

AUTH_HELP = (
    "Telegram authentication is missing or expired. "
    "Run `uv run telegram-spam-filter login` interactively, then revoke unused sessions at "
    "https://my.telegram.org if you did not recognize the logout."
)

logger = logging.getLogger("telegram_spam_filter.client")


def _auth_error(exc: BaseException) -> AuthExpiredError:
    name = type(exc).__name__
    return AuthExpiredError(f"{AUTH_HELP} (Telegram error: {name})")


def create_client(settings: Settings) -> TelegramClient:
    if settings.api_id <= 0 or not settings.api_hash:
        raise ConfigError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required.")
    ensure_private_dir(settings.session_path.parent)
    check_runtime_paths(settings.env_path, settings.session_path, settings.state_path)
    # Handle FloodWaitError ourselves so retries stay explicit and testable.
    return TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
        flood_sleep_threshold=0,
        receive_updates=True,
        sequential_updates=True,
    )


def lock_down_session(settings: Settings) -> None:
    if settings.session_path.is_file():
        chmod_private_file(settings.session_path)
    journal = settings.session_path.with_name(settings.session_path.name + "-journal")
    if journal.is_file():
        chmod_private_file(journal)


async def require_authorized(client: TelegramClient) -> None:
    try:
        authorized = await client.is_user_authorized()
    except AUTH_ERRORS as exc:
        raise _auth_error(exc) from exc
    if not authorized:
        raise AuthExpiredError(AUTH_HELP)


@asynccontextmanager
async def connected_client(settings: Settings, *, require_auth: bool = True) -> Any:
    client = create_client(settings)
    try:
        await client.connect()
        if require_auth:
            await require_authorized(client)
        yield client
    except AUTH_ERRORS as exc:
        raise _auth_error(exc) from exc
    finally:
        await client.disconnect()
        lock_down_session(settings)


async def interactive_login(settings: Settings) -> None:
    """Prompt for phone, login code, and 2FA password. Never echo or log secrets."""
    check_runtime_paths(settings.env_path, settings.session_path, settings.state_path)
    ensure_private_dir(settings.session_path.parent)
    client = create_client(settings)
    try:
        await client.connect()
        if await client.is_user_authorized():
            print("Already logged in. Session file is ready.")
            return

        def phone() -> str:
            return input("Phone number (international format, e.g. +15555550100): ").strip()

        def code() -> str:
            return getpass.getpass("Telegram login code (input hidden): ")

        def password() -> str:
            return getpass.getpass("Two-factor authentication password (input hidden): ")

        await client.start(phone=phone, code_callback=code, password=password)
        await require_authorized(client)
        print("Login succeeded. Session stored locally with user-only permissions.")
    except AUTH_ERRORS as exc:
        raise _auth_error(exc) from exc
    finally:
        await client.disconnect()
        lock_down_session(settings)


async def invoke_with_flood_wait[T](
    operation: Callable[[], Awaitable[T]],
    *,
    action: str,
    max_immediate_wait: int = MAX_IMMEDIATE_FLOOD_WAIT,
    max_retries: int = MAX_ACTION_RETRIES,
) -> T:
    """Retry Telegram calls, sleeping for short flood-waits and raising longer ones."""
    last_error: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return await operation()
        except AUTH_ERRORS as exc:
            raise _auth_error(exc) from exc
        except (FloodWaitError, FloodPremiumWaitError) as exc:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            last_error = exc
            log(
                logger,
                logging.WARNING,
                "flood_wait",
                action=action,
                seconds=seconds,
                attempt=attempt + 1,
            )
            if seconds <= 0:
                seconds = 1
            if seconds > max_immediate_wait:
                raise
            await asyncio.sleep(seconds + 1)
        except RPCError:
            raise
    assert last_error is not None
    raise last_error
