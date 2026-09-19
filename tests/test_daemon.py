from __future__ import annotations

from pathlib import Path

import pytest
from telethon.errors import FloodWaitError

from telegram_spam_filter.actions import apply_archive_and_mute
from telegram_spam_filter.allowlist import Allowlist
from telegram_spam_filter.client import invoke_with_flood_wait
from telegram_spam_filter.contacts import extract_contact_ids
from telegram_spam_filter.daemon import FilterEngine
from telegram_spam_filter.policy import IncomingMessage
from telegram_spam_filter.state import StateStore


class FakeContacts:
    def __init__(self, contacts: list[object], users: list[object] | None = None) -> None:
        self.contacts = contacts
        self.users = users or []


class FakeContact:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id


class FakeActions:
    def __init__(self) -> None:
        self.archives: list[int] = []
        self.mutes: list[int] = []
        self.archive_errors: dict[int, Exception] = {}
        self.mute_errors: dict[int, Exception] = {}

    async def archive(self, user_id: int) -> None:
        error = self.archive_errors.get(user_id)
        if error is not None:
            raise error
        self.archives.append(user_id)

    async def mute(self, user_id: int) -> None:
        error = self.mute_errors.get(user_id)
        if error is not None:
            raise error
        self.mutes.append(user_id)


def _incoming(user_id: int) -> IncomingMessage:
    return IncomingMessage(
        user_id=user_id,
        is_private=True,
        is_outgoing=False,
        is_group=False,
        is_channel=False,
        is_bot=False,
        is_self=False,
        is_service=False,
        is_saved_messages=False,
    )


def test_extract_contact_ids() -> None:
    result = FakeContacts(contacts=[FakeContact(1), FakeContact(2)])
    assert extract_contact_ids(result) == {1, 2}


@pytest.mark.asyncio
async def test_new_non_contact_private_message_is_archived_and_muted(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    actions = FakeActions()
    engine = FilterEngine(
        store=store,
        allowlist=Allowlist(store),
        contacts=_Cache({10}),
        actions=actions,
        me_id=1,
    )
    status = await engine.handle_message(_incoming(99))
    assert status == "filtered"
    assert actions.archives == [99]
    assert actions.mutes == [99]
    state = store.get_dialog(99)
    assert state is not None
    assert state.complete


@pytest.mark.asyncio
async def test_idempotent_repeat_does_not_call_telegram_again(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    actions = FakeActions()
    engine = FilterEngine(
        store=store,
        allowlist=Allowlist(store),
        contacts=_Cache(set()),
        actions=actions,
        me_id=1,
    )
    await engine.handle_message(_incoming(55))
    await engine.handle_message(_incoming(55))
    assert actions.archives == [55]
    assert actions.mutes == [55]


@pytest.mark.asyncio
async def test_partial_archive_mute_failure_retries_only_failed_action(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite")
    actions = FakeActions()
    actions.mute_errors[77] = RuntimeError("mute boom")
    first = await apply_archive_and_mute(actions, store, 77)
    assert first.archived is True
    assert first.muted is False
    assert actions.archives == [77]
    assert actions.mutes == []

    actions.mute_errors.clear()
    second = await apply_archive_and_mute(actions, store, 77)
    assert second.complete
    assert actions.archives == [77]
    assert actions.mutes == [77]


@pytest.mark.asyncio
async def test_flood_wait_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("telegram_spam_filter.client.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FloodWaitError("test", capture=2)
        return "ok"

    result = await invoke_with_flood_wait(flaky, action="archive")
    assert result == "ok"
    assert sleeps == [3]


@pytest.mark.asyncio
async def test_long_flood_wait_is_surfaced_as_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never_sleep(seconds: float) -> None:
        raise AssertionError(f"should not sleep for {seconds}")

    monkeypatch.setattr("telegram_spam_filter.client.asyncio.sleep", never_sleep)
    store = StateStore(tmp_path / "state.sqlite")
    actions = FakeActions()
    actions.archive_errors[3] = FloodWaitError("archive", capture=500)
    result = await apply_archive_and_mute(actions, store, 3)
    assert result.archived is False
    assert result.muted is True
    assert result.archive_error is not None
    assert "500" in result.archive_error
    assert actions.mutes == [3]


class _Cache:
    def __init__(self, ids: set[int]) -> None:
        self._ids = ids

    def ids(self) -> set[int]:
        return set(self._ids)

    def contains(self, user_id: int) -> bool:
        return user_id in self._ids
