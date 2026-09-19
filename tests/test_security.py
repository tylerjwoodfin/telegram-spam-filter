from __future__ import annotations

import os
from pathlib import Path

import pytest

from telegram_spam_filter.exceptions import InsecurePermissionsError
from telegram_spam_filter.security import check_runtime_paths, chmod_private_file


def test_refuses_world_readable_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_API_HASH=secret\n", encoding="utf-8")
    os.chmod(env, 0o644)
    with pytest.raises(InsecurePermissionsError, match="chmod 600"):
        check_runtime_paths(env, tmp_path / "missing.session", tmp_path / "missing.sqlite")


def test_accepts_user_only_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_API_HASH=secret\n", encoding="utf-8")
    chmod_private_file(env)
    check_runtime_paths(env, tmp_path / "missing.session", tmp_path / "missing.sqlite")
