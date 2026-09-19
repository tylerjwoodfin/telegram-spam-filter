"""Plan archive/mute actions for existing private dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegram_spam_filter.config import ARCHIVE_FOLDER_ID
from telegram_spam_filter.policy import IncomingMessage, should_filter


@dataclass(frozen=True)
class SweepPlanItem:
    user_id: int
    actions: tuple[str, ...]


@dataclass(frozen=True)
class DialogView:
    user_id: int
    is_user: bool
    is_bot: bool
    is_self: bool
    is_group: bool
    is_channel: bool
    folder_id: int
    muted: bool


def _message_for_dialog(dialog: DialogView) -> IncomingMessage:
    return IncomingMessage(
        user_id=dialog.user_id,
        is_private=dialog.is_user and not dialog.is_group and not dialog.is_channel,
        is_outgoing=False,
        is_group=dialog.is_group,
        is_channel=dialog.is_channel,
        is_bot=dialog.is_bot,
        is_self=dialog.is_self,
        is_service=False,
        is_saved_messages=dialog.is_self,
    )


def plan_sweep(
    dialogs: list[DialogView],
    contact_ids: set[int],
    allowlist_ids: set[int],
) -> list[SweepPlanItem]:
    """Return numeric IDs and actions for untrusted existing private dialogs."""
    items: list[SweepPlanItem] = []
    for dialog in dialogs:
        if not should_filter(_message_for_dialog(dialog), contact_ids, allowlist_ids):
            continue
        actions: list[str] = []
        if dialog.folder_id != ARCHIVE_FOLDER_ID:
            actions.append("archive")
        if not dialog.muted:
            actions.append("mute")
        if actions:
            items.append(SweepPlanItem(user_id=dialog.user_id, actions=tuple(actions)))
    return items


def dialog_view_from_telethon(dialog: Any, me_id: int) -> DialogView | None:
    entity = getattr(dialog, "entity", None)
    if entity is None:
        return None
    user_id = getattr(entity, "id", None)
    if not isinstance(user_id, int):
        return None
    is_user = bool(getattr(dialog, "is_user", False))
    has_user_attrs = hasattr(entity, "bot") and hasattr(entity, "is_self")
    if not is_user and not has_user_attrs:
        return None
    folder_id = getattr(dialog, "folder_id", None)
    if folder_id is None:
        folder_id = getattr(getattr(dialog, "dialog", None), "folder_id", 0) or 0
    notify = getattr(dialog, "dialog", None)
    muted = False
    if notify is not None:
        settings = getattr(notify, "notify_settings", None)
        mute_until = getattr(settings, "mute_until", None) if settings is not None else None
        muted = mute_until is not None
    return DialogView(
        user_id=user_id,
        is_user=is_user or has_user_attrs,
        is_bot=bool(getattr(entity, "bot", False)),
        is_self=bool(getattr(entity, "is_self", False)) or user_id == me_id,
        is_group=bool(getattr(dialog, "is_group", False)),
        is_channel=bool(getattr(dialog, "is_channel", False)),
        folder_id=int(folder_id or 0),
        muted=bool(muted),
    )
