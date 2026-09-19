from __future__ import annotations

from pathlib import Path

import pytest

from telegram_spam_filter.allowlist import Allowlist
from telegram_spam_filter.state import StateStore


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    return StateStore(tmp_path / "filter.sqlite")


@pytest.fixture
def allowlist(store: StateStore) -> Allowlist:
    return Allowlist(store)
