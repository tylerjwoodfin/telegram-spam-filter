from __future__ import annotations

from telegram_spam_filter.exceptions import UnsupportedApiError
from telegram_spam_filter.privacy import (
    TARGET_FIELD,
    build_updated_settings,
    require_target_field,
    snapshot_fields,
)


class FakeGlobalPrivacy:
    def __init__(
        self,
        archive_and_mute_new_noncontact_peers: bool | None = None,
        keep_archived_unmuted: bool | None = None,
        keep_archived_folders: bool | None = None,
        hide_read_marks: bool | None = None,
        new_noncontact_peers_require_premium: bool | None = None,
        display_gifts_button: bool | None = None,
        noncontact_peers_paid_stars: int | None = None,
        disallowed_gifts: object | None = None,
    ) -> None:
        self.archive_and_mute_new_noncontact_peers = archive_and_mute_new_noncontact_peers
        self.keep_archived_unmuted = keep_archived_unmuted
        self.keep_archived_folders = keep_archived_folders
        self.hide_read_marks = hide_read_marks
        self.new_noncontact_peers_require_premium = new_noncontact_peers_require_premium
        self.display_gifts_button = display_gifts_button
        self.noncontact_peers_paid_stars = noncontact_peers_paid_stars
        self.disallowed_gifts = disallowed_gifts


class IncompletePrivacy:
    def __init__(self, hide_read_marks: bool | None = None) -> None:
        self.hide_read_marks = hide_read_marks


def test_preserves_unrelated_global_privacy_settings() -> None:
    current = FakeGlobalPrivacy(
        archive_and_mute_new_noncontact_peers=False,
        keep_archived_unmuted=True,
        keep_archived_folders=True,
        hide_read_marks=True,
        new_noncontact_peers_require_premium=False,
        display_gifts_button=True,
        noncontact_peers_paid_stars=50,
        disallowed_gifts={"keep": True},
    )
    updated = build_updated_settings(current, FakeGlobalPrivacy, archive_and_mute=True)
    assert isinstance(updated, FakeGlobalPrivacy)
    assert updated.archive_and_mute_new_noncontact_peers is True
    assert updated.keep_archived_unmuted is True
    assert updated.keep_archived_folders is True
    assert updated.hide_read_marks is True
    assert updated.new_noncontact_peers_require_premium is False
    assert updated.display_gifts_button is True
    assert updated.noncontact_peers_paid_stars == 50
    assert updated.disallowed_gifts == {"keep": True}


def test_does_not_enable_premium_or_paid_flags() -> None:
    current = FakeGlobalPrivacy(
        new_noncontact_peers_require_premium=None,
        noncontact_peers_paid_stars=None,
    )
    updated = build_updated_settings(current, FakeGlobalPrivacy)
    assert isinstance(updated, FakeGlobalPrivacy)
    assert updated.new_noncontact_peers_require_premium is None
    assert updated.noncontact_peers_paid_stars is None


def test_unsupported_constructor_without_target_field() -> None:
    try:
        require_target_field(IncompletePrivacy)
    except UnsupportedApiError as exc:
        assert TARGET_FIELD in str(exc)
    else:
        raise AssertionError("expected UnsupportedApiError")


def test_snapshot_includes_every_supported_field() -> None:
    current = FakeGlobalPrivacy(keep_archived_unmuted=True)
    names = require_target_field(FakeGlobalPrivacy)
    snapshot = snapshot_fields(current, names)
    assert set(snapshot) == set(names)
    assert snapshot["keep_archived_unmuted"] is True
