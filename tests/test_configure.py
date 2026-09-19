from __future__ import annotations

from telethon import functions, types
from telethon.errors import AutoarchiveNotAvailableError

from telegram_spam_filter.configure import configure_global_privacy


class FakeTelegram:
    def __init__(
        self,
        settings: types.GlobalPrivacySettings,
        *,
        error: Exception | None = None,
    ) -> None:
        self.settings = settings
        self.error = error
        self.set_payloads: list[types.GlobalPrivacySettings] = []

    async def __call__(self, request: object) -> object:
        if isinstance(request, functions.account.GetGlobalPrivacySettingsRequest):
            return self.settings
        if isinstance(request, functions.account.SetGlobalPrivacySettingsRequest):
            if self.error is not None:
                raise self.error
            self.set_payloads.append(request.settings)
            self.settings = request.settings
            return request.settings
        raise AssertionError(f"unexpected request {request!r}")


async def test_configure_preserves_unrelated_fields_on_real_constructor() -> None:
    current = types.GlobalPrivacySettings(
        archive_and_mute_new_noncontact_peers=False,
        keep_archived_unmuted=True,
        keep_archived_folders=True,
        hide_read_marks=True,
        new_noncontact_peers_require_premium=True,
        display_gifts_button=False,
        noncontact_peers_paid_stars=25,
    )
    client = FakeTelegram(current)
    result = await configure_global_privacy(client)
    assert result.outcome == "verified"
    assert len(client.set_payloads) == 1
    payload = client.set_payloads[0]
    assert payload.archive_and_mute_new_noncontact_peers is True
    assert payload.keep_archived_unmuted is True
    assert payload.keep_archived_folders is True
    assert payload.hide_read_marks is True
    assert payload.new_noncontact_peers_require_premium is True
    assert payload.display_gifts_button is False
    assert payload.noncontact_peers_paid_stars == 25


async def test_configure_reports_telegram_rejection() -> None:
    current = types.GlobalPrivacySettings(archive_and_mute_new_noncontact_peers=False)
    client = FakeTelegram(current, error=AutoarchiveNotAvailableError(request="set"))
    result = await configure_global_privacy(client)
    assert result.outcome == "rejected"
    assert result.rpc_error == "AutoarchiveNotAvailableError"
    assert "AutoarchiveNotAvailableError" in result.message
