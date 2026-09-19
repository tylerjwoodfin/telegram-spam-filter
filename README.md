# Telegram spam filter

A small user-account service for an Apple Silicon Mac. It first tries Telegram's
server-side `archive_and_mute_new_noncontact_peers` privacy setting. If Telegram
rejects or ignores that setting, a local daemon archives and permanently mutes
new private chats from people who are not in your Telegram contacts.

This is **not** OpenClaw. It uses your personal MTProto user session, never a
bot token, and it never deletes messages, blocks users, reports spam, replies,
or calls an LLM.

## Threat model and limitations

- The daemon only sees chats after Telegram has already accepted the message.
  A notification can theoretically appear before the archive/mute RPC completes.
- Server-side auto-archive is the stronger control, but Telegram may hide it
  behind `AUTOARCHIVE_NOT_AVAILABLE` / Premium checks. The daemon is the fallback.
- The Telethon **session file is equivalent to being logged in**. Anyone who can
  read it can act as you. Keep `.env` and `*.session` at mode `600`, owned by
  your user. This tool refuses to start if those files are group- or
  world-accessible.
- Contacts and the local allowlist are trusted. Anyone you add as a Telegram
  contact, or allowlist by numeric ID, is not filtered.
- Existing chats are left alone unless you run `sweep --apply`.
- The filter does not inspect message text or media. It only uses numeric user
  IDs, contact membership, and dialog metadata.

## Create Telegram API credentials

1. Open [https://my.telegram.org](https://my.telegram.org) and sign in with your
   personal account.
2. Open **API development tools**.
3. Create an application if you do not already have `api_id` / `api_hash`.
4. Copy those values into `.env`. Never commit them, and never put them in the
   LaunchAgent plist.

## Setup (Apple Silicon Mac)

```bash
brew install uv
cd ~/git/telegram-spam-filter
cp .env.example .env
chmod 600 .env
# edit .env and set TELEGRAM_API_ID and TELEGRAM_API_HASH
uv sync
```

### Interactive login

```bash
uv run telegram-spam-filter login
```

You will be asked for your phone number, the login code (hidden input), and a
2FA password if the account has one. Codes, passwords, API hashes, and session
bytes are never printed.

### Try the server-side setting

```bash
uv run telegram-spam-filter configure
```

This reads the current global privacy settings, sets only
`archive_and_mute_new_noncontact_peers=true`, carries every other supported field
forward, and re-fetches to verify persistence. If it succeeds, the continuous
daemon may be unnecessary.

### Run in the foreground

```bash
uv run telegram-spam-filter run
```

### LaunchAgent

Do not enable launchd until you want it to start at login.

```bash
uv run telegram-spam-filter install-launchd
uv run telegram-spam-filter status
launchctl print gui/$UID/com.tyler.telegram-spam-filter
# restart after a code change
launchctl kickstart -k gui/$UID/com.tyler.telegram-spam-filter
uv run telegram-spam-filter uninstall-launchd
```

Logs go to `~/Library/Logs/telegram-spam-filter/` (stdout/stderr from launchd)
and structured JSON on stderr when running in the foreground.

### Allowlist

```bash
uv run telegram-spam-filter allow 123456789
uv run telegram-spam-filter list-allow
uv run telegram-spam-filter unallow 123456789
```

Only numeric Telegram user IDs are accepted. Wildcards are rejected. Allowlisted
IDs skip the non-contact filter.

### Existing chats

```bash
uv run telegram-spam-filter sweep --dry-run
uv run telegram-spam-filter sweep --apply
```

Dry-run prints only numeric IDs and `archive` / `mute` actions.

## Rotate or revoke the Telegram session

1. Stop the daemon: `uv run telegram-spam-filter uninstall-launchd` (or Ctrl-C
   in the foreground).
2. Delete the local session file (`TELEGRAM_SESSION_PATH`, default
   `./state/user.session`).
3. At [https://my.telegram.org](https://my.telegram.org) or in Telegram
   Settings → Devices, terminate the session you no longer want.
4. Run `uv run telegram-spam-filter login` again.

## Uninstall this tool without touching other Telegram data

```bash
uv run telegram-spam-filter uninstall-launchd
rm -rf ~/git/telegram-spam-filter/state
rm -f ~/git/telegram-spam-filter/.env
rm -rf ~/Library/Logs/telegram-spam-filter
```

That does **not** log out Telegram Desktop, iOS, Android, or other sessions.
Revoke those separately if you want.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| 2FA prompt | `login` uses hidden input for the cloud password. If it fails, reset/check 2FA in Telegram and retry `login`. |
| Expired session | `AuthKeyUnregisteredError` / `SessionRevokedError` / `SessionExpiredError`. Delete the local `.session` file and run `login` again. |
| Flood wait | The client sleeps for short waits and retries. Long waits are logged and retried on the next message. Slow down `sweep --apply` if Telegram rate-limits you. |
| launchd not found / `uv` missing | `install-launchd` embeds the absolute `uv` path. Re-run it after Homebrew moves `uv`. Check `PATH` in the generated plist. |
| "readable by group or other users" | `chmod 600 .env ./state/user.session ./state/filter.sqlite` and `chmod 700 ./state ~/Library/Logs/telegram-spam-filter`. |
| `AUTOARCHIVE_NOT_AVAILABLE` | Telegram refused the server-side flag. Use `run` / LaunchAgent as the fallback. |

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
uv run mypy src tests
plutil -lint launchd/com.tyler.telegram-spam-filter.plist.template
```

Tests mock Telegram and never open a network connection.
