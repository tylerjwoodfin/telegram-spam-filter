from __future__ import annotations

from telegram_spam_filter.policy import IncomingMessage, is_trusted, should_consider, should_filter


def _message(**overrides: object) -> IncomingMessage:
    data: dict[str, object] = {
        "user_id": 42,
        "is_private": True,
        "is_outgoing": False,
        "is_group": False,
        "is_channel": False,
        "is_bot": False,
        "is_self": False,
        "is_service": False,
        "is_saved_messages": False,
    }
    data.update(overrides)
    return IncomingMessage(**data)  # type: ignore[arg-type]


def test_contact_detection_trusts_contact_ids() -> None:
    message = _message(user_id=7)
    assert is_trusted(7, {7, 8}, set())
    assert not should_filter(message, {7}, set())


def test_allowlist_overrides_non_contact_filter() -> None:
    message = _message(user_id=99)
    assert not is_trusted(99, set(), set())
    assert is_trusted(99, set(), {99})
    assert should_filter(message, set(), set())
    assert not should_filter(message, set(), {99})


def test_ignores_groups_bots_outgoing_and_self() -> None:
    assert not should_consider(_message(is_group=True, is_private=False))
    assert not should_consider(_message(is_channel=True, is_private=False))
    assert not should_consider(_message(is_bot=True))
    assert not should_consider(_message(is_outgoing=True))
    assert not should_consider(_message(is_self=True, is_saved_messages=True))
    assert not should_consider(_message(is_service=True))
    assert should_consider(_message())
