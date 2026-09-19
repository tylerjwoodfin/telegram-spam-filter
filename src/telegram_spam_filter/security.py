"""Refuse to run if secrets or session files are readable by other users."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from telegram_spam_filter.exceptions import InsecurePermissionsError

_GROUP_OR_OTHER_READ = (
    stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH
)


def is_group_or_world_accessible(path: Path) -> bool:
    mode = path.stat().st_mode
    return bool(mode & _GROUP_OR_OTHER_READ)


def chmod_private_file(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def chmod_private_dir(path: Path) -> None:
    os.chmod(path, stat.S_IRWXU)


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    chmod_private_dir(path)
    if is_group_or_world_accessible(path):
        raise InsecurePermissionsError(_permission_message(path))


def check_secret_file(path: Path, *, must_exist: bool = False) -> None:
    if not path.exists():
        if must_exist:
            raise FileNotFoundError(path)
        return
    if path.is_dir():
        if is_group_or_world_accessible(path):
            raise InsecurePermissionsError(_permission_message(path))
        return
    if is_group_or_world_accessible(path):
        raise InsecurePermissionsError(_permission_message(path))


def _permission_message(path: Path) -> str:
    return (
        f"{path} is readable or writable by group or other users. "
        f"This file contains Telegram secrets or session material. "
        f"Fix with: chmod 600 {path}   (or chmod 700 if it is a directory)"
    )


def check_runtime_paths(env_path: Path, session_path: Path, state_path: Path) -> None:
    """Refuse to start if .env, session, or state files are too open."""
    for path in (env_path, session_path, state_path):
        check_secret_file(path)
    for sibling in _session_sidecars(session_path):
        check_secret_file(sibling)


def _session_sidecars(session_path: Path) -> list[Path]:
    return [
        Path(str(session_path) + "-journal"),
        session_path.with_suffix(session_path.suffix + "-journal"),
        session_path.with_name(session_path.name + "-journal"),
    ]
