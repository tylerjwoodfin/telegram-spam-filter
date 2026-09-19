"""Load configuration from the environment / `.env` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from telegram_spam_filter.exceptions import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSION_PATH = PROJECT_ROOT / "state" / "user.session"
DEFAULT_STATE_PATH = PROJECT_ROOT / "state" / "filter.sqlite"
DEFAULT_LOCK_PATH = PROJECT_ROOT / "state" / "daemon.lock"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
LAUNCHD_LABEL = "com.tyler.telegram-spam-filter"
LAUNCHD_PLIST_NAME = f"{LAUNCHD_LABEL}.plist"
ARCHIVE_FOLDER_ID = 1
MUTE_UNTIL_UNIX = 2_147_483_647
DEFAULT_CONTACTS_REFRESH_SECONDS = 900
DEFAULT_REVALIDATE_SECONDS = 21_600
MAX_IMMEDIATE_FLOOD_WAIT = 120
MAX_ACTION_RETRIES = 5


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_path: Path
    state_path: Path
    lock_path: Path
    env_path: Path
    log_dir: Path
    project_root: Path
    contacts_refresh_seconds: int
    revalidate_seconds: int


def default_log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "telegram-spam-filter"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / LAUNCHD_PLIST_NAME


def _require_int(name: str, raw: str | None, default: int | None = None) -> int:
    if raw is None or raw.strip() == "":
        if default is None:
            raise ConfigError(
                f"Missing required setting {name}. Copy .env.example to .env and fill it in."
            )
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _optional_path(raw: str | None, default: Path) -> Path:
    if raw is None or raw.strip() == "":
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return (PROJECT_ROOT / path).resolve()
    return path.resolve()


def load_settings(env_file: Path | None = None, *, require_credentials: bool = True) -> Settings:
    """Load `.env` then process environment variables."""
    env_path = env_file.resolve() if env_file is not None else DEFAULT_ENV_PATH
    if env_path.is_file():
        load_dotenv(env_path, override=False)

    api_id_raw = os.environ.get("TELEGRAM_API_ID")
    api_hash = (os.environ.get("TELEGRAM_API_HASH") or "").strip()
    if require_credentials:
        api_id = _require_int("TELEGRAM_API_ID", api_id_raw)
        if not api_hash:
            raise ConfigError(
                "Missing TELEGRAM_API_HASH. Create API credentials at https://my.telegram.org "
                "and put them in .env."
            )
    else:
        api_id = _require_int("TELEGRAM_API_ID", api_id_raw, default=0)

    log_dir_raw = os.environ.get("TELEGRAM_LOG_DIR")
    log_dir = Path(log_dir_raw).expanduser() if log_dir_raw else default_log_dir()
    if not log_dir.is_absolute():
        log_dir = (PROJECT_ROOT / log_dir).resolve()

    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        session_path=_optional_path(os.environ.get("TELEGRAM_SESSION_PATH"), DEFAULT_SESSION_PATH),
        state_path=_optional_path(os.environ.get("TELEGRAM_STATE_PATH"), DEFAULT_STATE_PATH),
        lock_path=DEFAULT_LOCK_PATH,
        env_path=env_path,
        log_dir=log_dir,
        project_root=PROJECT_ROOT,
        contacts_refresh_seconds=_require_int(
            "TELEGRAM_CONTACTS_REFRESH_SECONDS",
            os.environ.get("TELEGRAM_CONTACTS_REFRESH_SECONDS"),
            default=DEFAULT_CONTACTS_REFRESH_SECONDS,
        ),
        revalidate_seconds=_require_int(
            "TELEGRAM_REVALIDATE_SECONDS",
            os.environ.get("TELEGRAM_REVALIDATE_SECONDS"),
            default=DEFAULT_REVALIDATE_SECONDS,
        ),
    )
