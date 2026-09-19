"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from telegram_spam_filter.actions import TelethonDialogActions, apply_archive_and_mute
from telegram_spam_filter.allowlist import Allowlist, InvalidUserIdError, parse_user_id
from telegram_spam_filter.client import connected_client, interactive_login
from telegram_spam_filter.config import Settings, load_settings
from telegram_spam_filter.configure import configure_global_privacy, format_settings
from telegram_spam_filter.contacts import ContactCache
from telegram_spam_filter.daemon import read_daemon_pid, run_daemon
from telegram_spam_filter.exceptions import SpamFilterError
from telegram_spam_filter.launchd import install_launchd, launchd_status, uninstall_launchd
from telegram_spam_filter.logging_config import configure_logging
from telegram_spam_filter.privacy import archive_flag
from telegram_spam_filter.security import check_runtime_paths
from telegram_spam_filter.state import StateStore
from telegram_spam_filter.sweep import dialog_view_from_telethon, plan_sweep


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-spam-filter",
        description="Archive and mute unsolicited Telegram private messages without Premium.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to .env (default: project .env)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Interactive MTProto login for your personal Telegram account")
    sub.add_parser("configure", help="Try to enable server-side archive-and-mute for non-contacts")
    sub.add_parser("status", help="Show session, privacy, allowlist, and LaunchAgent status")
    sub.add_parser("run", help="Run the fallback daemon in the foreground")

    allow = sub.add_parser("allow", help="Add a numeric user ID to the local allowlist")
    allow.add_argument("user_id", help="Numeric Telegram user ID")

    unallow = sub.add_parser("unallow", help="Remove a numeric user ID from the local allowlist")
    unallow.add_argument("user_id", help="Numeric Telegram user ID")

    sub.add_parser("list-allow", help="List locally allowlisted numeric user IDs")

    sweep = sub.add_parser("sweep", help="Inspect or filter existing private dialogs")
    sweep_mode = sweep.add_mutually_exclusive_group(required=True)
    sweep_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print numeric IDs and actions only",
    )
    sweep_mode.add_argument(
        "--apply",
        action="store_true",
        help="Archive and mute matching existing dialogs",
    )

    sub.add_parser("install-launchd", help="Install and load the per-user LaunchAgent")
    sub.add_parser("uninstall-launchd", help="Unload and remove the LaunchAgent")
    return parser


def _settings(args: argparse.Namespace, *, require_credentials: bool = True) -> Settings:
    settings = load_settings(args.env_file, require_credentials=require_credentials)
    check_runtime_paths(settings.env_path, settings.session_path, settings.state_path)
    return settings


def _print_privacy(settings_obj: object) -> None:
    print("Current global privacy settings:")
    for line in format_settings(settings_obj):
        print(line)


async def _cmd_configure(settings: Settings) -> int:
    async with connected_client(settings) as client:
        from telethon import functions

        current = await client(functions.account.GetGlobalPrivacySettingsRequest())
        _print_privacy(current)
        result = await configure_global_privacy(client)
        if result.after and result.outcome != "rejected":
            print("Settings after update:")
            for key, value in result.after.items():
                print(f"  {key}: {value}")
        print(result.message)
        return 0 if result.outcome != "unsupported" else 2


async def _cmd_status(settings: Settings) -> int:
    print(f"project: {settings.project_root}")
    print(f"env: {settings.env_path} ({'present' if settings.env_path.is_file() else 'missing'})")
    print(
        f"session: {settings.session_path} "
        f"({'present' if settings.session_path.is_file() else 'missing'})"
    )
    print(f"state: {settings.state_path}")
    store = StateStore(settings.state_path)
    allowlist = Allowlist(store)
    print(f"allowlist_count: {len(allowlist.ids())}")
    pid = read_daemon_pid(settings.lock_path)
    print(f"daemon_pid: {pid if pid is not None else 'not running'}")
    agent = launchd_status()
    print(f"launchd_loaded: {agent.loaded}")
    print(f"launchd_plist: {agent.plist_path}")
    if not settings.session_path.is_file() or settings.api_id <= 0:
        print("telegram: not logged in")
        return 0
    async with connected_client(settings) as client:
        me = await client.get_me()
        print(f"telegram_user_id: {int(me.id)}")
        from telethon import functions

        privacy = await client(functions.account.GetGlobalPrivacySettingsRequest())
        print(f"archive_and_mute_new_noncontact_peers: {archive_flag(privacy)}")
        contacts = ContactCache()
        await contacts.refresh(client)
        print(f"contact_count: {len(contacts.ids())}")
    return 0


async def _cmd_sweep(settings: Settings, *, apply: bool) -> int:
    store = StateStore(settings.state_path)
    allowlist = Allowlist(store)
    contacts = ContactCache()
    async with connected_client(settings) as client:
        me = await client.get_me()
        me_id = int(me.id)
        await contacts.refresh(client)
        dialogs = []
        async for dialog in client.iter_dialogs():
            view = dialog_view_from_telethon(dialog, me_id)
            if view is not None:
                dialogs.append(view)
        plan = plan_sweep(dialogs, contacts.ids(), allowlist.ids())
        if not plan:
            print("No matching private dialogs.")
            return 0
        actions = TelethonDialogActions(client)
        for item in plan:
            print(f"{item.user_id} {' '.join(item.actions)}")
            if apply:
                force_archive = "archive" in item.actions
                force_mute = "mute" in item.actions
                await apply_archive_and_mute(
                    actions,
                    store,
                    item.user_id,
                    force_archive=force_archive,
                    force_mute=force_mute,
                )
    return 0


def _cmd_allow(settings: Settings, raw_id: str, *, add: bool) -> int:
    try:
        user_id = parse_user_id(raw_id)
    except InvalidUserIdError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    allowlist = Allowlist.from_path(settings.state_path)
    if add:
        inserted = allowlist.add(user_id)
        print(f"{user_id} {'added' if inserted else 'already allowlisted'}")
    else:
        removed = allowlist.remove(user_id)
        print(f"{user_id} {'removed' if removed else 'not in allowlist'}")
    return 0


def _cmd_list_allow(settings: Settings) -> int:
    allowlist = Allowlist.from_path(settings.state_path)
    for user_id in sorted(allowlist.ids()):
        print(user_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            settings = _settings(args)
            asyncio.run(interactive_login(settings))
            return 0
        if args.command == "configure":
            return asyncio.run(_cmd_configure(_settings(args)))
        if args.command == "status":
            return asyncio.run(_cmd_status(_settings(args, require_credentials=False)))
        if args.command == "run":
            asyncio.run(run_daemon(_settings(args)))
            return 0
        if args.command == "allow":
            return _cmd_allow(_settings(args, require_credentials=False), args.user_id, add=True)
        if args.command == "unallow":
            return _cmd_allow(_settings(args, require_credentials=False), args.user_id, add=False)
        if args.command == "list-allow":
            return _cmd_list_allow(_settings(args, require_credentials=False))
        if args.command == "sweep":
            return asyncio.run(_cmd_sweep(_settings(args), apply=bool(args.apply)))
        if args.command == "install-launchd":
            path = install_launchd(_settings(args, require_credentials=False))
            print(f"Installed and loaded {path}")
            return 0
        if args.command == "uninstall-launchd":
            uninstall_launchd()
            print("LaunchAgent unloaded and removed.")
            return 0
        parser.error(f"unknown command {args.command}")
    except SpamFilterError as exc:
        print(str(exc), file=sys.stderr)
        logging.getLogger("telegram_spam_filter").error("cli_error", extra={"event": "cli_error"})
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
