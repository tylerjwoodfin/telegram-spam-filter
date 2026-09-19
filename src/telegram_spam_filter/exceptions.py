"""Application errors with actionable messages."""

from __future__ import annotations


class SpamFilterError(Exception):
    """Base error for user-facing failures."""


class InsecurePermissionsError(SpamFilterError):
    """A secrets or session file is readable by other users."""


class AuthExpiredError(SpamFilterError):
    """Telegram session is missing, revoked, or expired."""


class UnsupportedApiError(SpamFilterError):
    """Installed client library cannot represent a required API constructor."""


class ConfigError(SpamFilterError):
    """Missing or invalid configuration."""


class DaemonAlreadyRunningError(SpamFilterError):
    """Another daemon process holds the instance lock."""
