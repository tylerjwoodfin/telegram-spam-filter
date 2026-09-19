from __future__ import annotations

from pathlib import Path

import pytest

from telegram_spam_filter.allowlist import Allowlist, InvalidUserIdError, parse_user_id
from telegram_spam_filter.state import StateStore


def test_parse_user_id_accepts_positive_integers() -> None:
    assert parse_user_id("12345") == 12345
    assert parse_user_id("  9  ") == 9


def test_parse_user_id_rejects_wildcards_and_names() -> None:
    with pytest.raises(InvalidUserIdError):
        parse_user_id("*")
    with pytest.raises(InvalidUserIdError):
        parse_user_id("all")
    with pytest.raises(InvalidUserIdError):
        parse_user_id("@someone")
    with pytest.raises(InvalidUserIdError):
        parse_user_id("0")
    with pytest.raises(InvalidUserIdError):
        parse_user_id("-1")


def test_allowlist_add_remove_and_precedence(tmp_path: Path) -> None:
    allowlist = Allowlist(StateStore(tmp_path / "state.sqlite"))
    assert allowlist.add(111)
    assert not allowlist.add(111)
    assert allowlist.contains(111)
    assert allowlist.ids() == {111}
    assert allowlist.remove(111)
    assert not allowlist.contains(111)
    assert not allowlist.remove(111)
