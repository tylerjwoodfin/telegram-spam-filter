from __future__ import annotations

from pathlib import Path

from telegram_spam_filter.config import PROJECT_ROOT, Settings
from telegram_spam_filter.launchd import render_plist


def test_rendered_plist_has_absolute_paths_and_no_secrets() -> None:
    settings = Settings(
        api_id=12345,
        api_hash="should-never-appear",
        session_path=PROJECT_ROOT / "state" / "user.session",
        state_path=PROJECT_ROOT / "state" / "filter.sqlite",
        lock_path=PROJECT_ROOT / "state" / "daemon.lock",
        env_path=PROJECT_ROOT / ".env",
        log_dir=Path("/tmp/telegram-spam-filter-logs"),
        project_root=PROJECT_ROOT,
        contacts_refresh_seconds=900,
        revalidate_seconds=21600,
    )
    plist = render_plist(settings, uv_path=Path("/opt/homebrew/bin/uv"))
    assert "{{" not in plist
    assert "/opt/homebrew/bin/uv" in plist
    assert str(PROJECT_ROOT) in plist
    assert "telegram-spam-filter" in plist
    assert "run" in plist
    assert "should-never-appear" not in plist
    assert "12345" not in plist
    assert "TELEGRAM_API_HASH" not in plist
    assert "TELEGRAM_API_ID" not in plist
    assert "user.session" not in plist
