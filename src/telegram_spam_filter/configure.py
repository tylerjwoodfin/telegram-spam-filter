"""Enable Telegram's server-side archive_and_mute_new_noncontact_peers setting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from telethon import TelegramClient, functions, types
from telethon.errors import AutoarchiveNotAvailableError, PremiumAccountRequiredError, RPCError

from telegram_spam_filter.client import invoke_with_flood_wait
from telegram_spam_filter.exceptions import UnsupportedApiError
from telegram_spam_filter.privacy import (
    TARGET_FIELD,
    archive_flag,
    build_updated_settings,
    display_fields,
    require_target_field,
    snapshot_fields,
)

Outcome = Literal["verified", "rejected", "unsupported"]


@dataclass(frozen=True)
class ConfigureResult:
    outcome: Outcome
    message: str
    before: dict[str, Any]
    after: dict[str, Any]
    rpc_error: str | None = None


def format_settings(settings: object) -> list[str]:
    try:
        names = require_target_field(types.GlobalPrivacySettings)
    except UnsupportedApiError:
        names = tuple(name for name in getattr(settings, "to_dict", lambda: {})() if name != "_")
    lines = []
    for field in display_fields(settings, names):
        lines.append(f"  {field.name}: {field.value}")
    return lines


async def _get_settings(client: TelegramClient) -> object:
    return await invoke_with_flood_wait(
        lambda: client(functions.account.GetGlobalPrivacySettingsRequest()),
        action="get_global_privacy",
    )


async def _set_settings(client: TelegramClient, settings: object) -> object:
    return await invoke_with_flood_wait(
        lambda: client(functions.account.SetGlobalPrivacySettingsRequest(settings=settings)),
        action="set_global_privacy",
    )


async def configure_global_privacy(client: TelegramClient) -> ConfigureResult:
    try:
        require_target_field(types.GlobalPrivacySettings)
    except UnsupportedApiError as exc:
        return ConfigureResult(
            outcome="unsupported",
            message=str(exc),
            before={},
            after={},
        )

    current = await _get_settings(client)
    field_names = require_target_field(types.GlobalPrivacySettings)
    before = snapshot_fields(current, field_names)

    if archive_flag(current) is True:
        return ConfigureResult(
            outcome="verified",
            message=(
                "Successfully enabled and verified. "
                "archive_and_mute_new_noncontact_peers was already true. "
                "The continuous daemon may be unnecessary while Telegram honors this setting."
            ),
            before=before,
            after=before,
        )

    updated = build_updated_settings(current, types.GlobalPrivacySettings, archive_and_mute=True)
    try:
        await _set_settings(client, updated)
    except (AutoarchiveNotAvailableError, PremiumAccountRequiredError, RPCError) as exc:
        name = type(exc).__name__
        rpc_name = getattr(exc, "message", None) or name
        return ConfigureResult(
            outcome="rejected",
            message=(
                f"Telegram rejected the operation ({name}"
                + (f": {rpc_name}" if rpc_name != name else "")
                + "). The fallback daemon can still archive and mute new non-contact chats locally."
            ),
            before=before,
            after=before,
            rpc_error=name,
        )

    verified = await _get_settings(client)
    after = snapshot_fields(verified, field_names)
    if archive_flag(verified) is True:
        return ConfigureResult(
            outcome="verified",
            message=(
                "Successfully enabled and verified. "
                "The continuous daemon may be unnecessary while Telegram honors this setting."
            ),
            before=before,
            after=after,
        )
    return ConfigureResult(
        outcome="rejected",
        message=(
            "Telegram ignored the operation: "
            f"{TARGET_FIELD} is still {after.get(TARGET_FIELD)!r} after SetGlobalPrivacySettings. "
            "The fallback daemon can still archive and mute new non-contact chats locally."
        ),
        before=before,
        after=after,
        rpc_error="NOT_PERSISTED",
    )
