"""Inspect and merge Telegram globalPrivacySettings without clobbering unrelated flags."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from telegram_spam_filter.exceptions import UnsupportedApiError

TARGET_FIELD = "archive_and_mute_new_noncontact_peers"
# Display these first; remaining constructor fields are still preserved and shown.
PRIMARY_FIELDS = (
    TARGET_FIELD,
    "keep_archived_unmuted",
    "keep_archived_folders",
    "hide_read_marks",
    "new_noncontact_peers_require_premium",
    "display_gifts_button",
    "noncontact_peers_paid_stars",
    "disallowed_gifts",
)


@dataclass(frozen=True)
class PrivacyField:
    name: str
    value: Any


def constructor_field_names(constructor: type[Any]) -> tuple[str, ...]:
    """Return GlobalPrivacySettings field names supported by the installed layer."""
    try:
        signature = inspect.signature(constructor)
    except (TypeError, ValueError) as exc:
        raise UnsupportedApiError(
            "The installed client library cannot represent the current API constructor "
            f"({constructor!r} has no usable signature)."
        ) from exc
    names = tuple(name for name in signature.parameters if name != "self")
    if not names:
        raise UnsupportedApiError(
            "The installed client library cannot represent the current API constructor "
            "(GlobalPrivacySettings has no fields)."
        )
    return names


def require_target_field(constructor: type[Any]) -> tuple[str, ...]:
    names = constructor_field_names(constructor)
    if TARGET_FIELD not in names:
        raise UnsupportedApiError(
            "The installed client library cannot represent the current API constructor "
            f"(missing {TARGET_FIELD})."
        )
    return names


def snapshot_fields(settings: object, field_names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(settings, name, None) for name in field_names}


def build_updated_settings(
    current: object,
    constructor: type[Any],
    *,
    archive_and_mute: bool = True,
) -> object:
    """Copy every supported field from `current`, changing only the auto-archive flag."""
    names = require_target_field(constructor)
    kwargs: dict[str, Any] = {}
    for name in names:
        if name == TARGET_FIELD:
            kwargs[name] = archive_and_mute
        else:
            kwargs[name] = getattr(current, name, None)
    return constructor(**kwargs)


def display_fields(settings: object, field_names: tuple[str, ...]) -> list[PrivacyField]:
    ordered = [name for name in PRIMARY_FIELDS if name in field_names]
    ordered.extend(name for name in field_names if name not in ordered)
    return [PrivacyField(name=name, value=getattr(settings, name, None)) for name in ordered]


def archive_flag(settings: object) -> bool | None:
    value = getattr(settings, TARGET_FIELD, None)
    if value is None:
        return None
    return bool(value)
