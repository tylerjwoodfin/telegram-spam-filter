"""Install, inspect, and remove the per-user LaunchAgent.

Credentials stay in `.env`, not the plist.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from telegram_spam_filter.config import LAUNCHD_LABEL, PROJECT_ROOT, Settings, launchd_plist_path
from telegram_spam_filter.exceptions import ConfigError, SpamFilterError
from telegram_spam_filter.security import chmod_private_dir, ensure_private_dir

TEMPLATE_PATH = PROJECT_ROOT / "launchd" / "com.tyler.telegram-spam-filter.plist.template"


@dataclass(frozen=True)
class LaunchdStatus:
    loaded: bool
    plist_path: Path
    detail: str


def _which_uv() -> Path:
    found = shutil.which("uv")
    if found:
        return Path(found).resolve()
    raise ConfigError(
        "Could not find `uv` on PATH. Install it (for example `brew install uv`) "
        "and re-run install-launchd."
    )


def render_plist(settings: Settings, *, uv_path: Path | None = None) -> str:
    uv = uv_path or _which_uv()
    uv_dir = str(uv.parent)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{UV_PATH}}", str(uv))
        .replace("{{PROJECT_DIR}}", str(settings.project_root))
        .replace("{{LOG_DIR}}", str(settings.log_dir))
        .replace("{{PATH_VALUE}}", f"{uv_dir}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    )


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def validate_plist(path: Path) -> None:
    result = _run(["plutil", "-lint", str(path)], check=False)
    if result.returncode != 0:
        raise SpamFilterError(result.stdout.strip() or result.stderr.strip() or "plutil failed")


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _service_target() -> str:
    return f"{_gui_domain()}/{LAUNCHD_LABEL}"


def install_launchd(settings: Settings) -> Path:
    ensure_private_dir(settings.log_dir)
    chmod_private_dir(settings.log_dir)
    dest = launchd_plist_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_plist(settings), encoding="utf-8")
    os.chmod(dest, 0o644)
    validate_plist(dest)
    _run(["launchctl", "bootout", _service_target()], check=False)
    result = _run(["launchctl", "bootstrap", _gui_domain(), str(dest)], check=False)
    if result.returncode != 0:
        raise SpamFilterError(
            "launchctl bootstrap failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    return dest


def uninstall_launchd() -> None:
    _run(["launchctl", "bootout", _service_target()], check=False)
    dest = launchd_plist_path()
    if dest.exists():
        dest.unlink()


def launchd_status() -> LaunchdStatus:
    dest = launchd_plist_path()
    result = _run(["launchctl", "print", _service_target()], check=False)
    loaded = result.returncode == 0
    detail = (result.stdout or result.stderr).strip()
    return LaunchdStatus(loaded=loaded, plist_path=dest, detail=detail)
