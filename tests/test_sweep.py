from __future__ import annotations

from telegram_spam_filter.sweep import DialogView, plan_sweep


def test_dry_run_sweep_lists_numeric_ids_and_actions_only() -> None:
    dialogs = [
        DialogView(
            user_id=101,
            is_user=True,
            is_bot=False,
            is_self=False,
            is_group=False,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=102,
            is_user=True,
            is_bot=False,
            is_self=False,
            is_group=False,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=201,
            is_user=True,
            is_bot=False,
            is_self=False,
            is_group=False,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=301,
            is_user=False,
            is_bot=False,
            is_self=False,
            is_group=True,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=401,
            is_user=True,
            is_bot=True,
            is_self=False,
            is_group=False,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=501,
            is_user=True,
            is_bot=False,
            is_self=True,
            is_group=False,
            is_channel=False,
            folder_id=0,
            muted=False,
        ),
        DialogView(
            user_id=601,
            is_user=True,
            is_bot=False,
            is_self=False,
            is_group=False,
            is_channel=False,
            folder_id=1,
            muted=True,
        ),
    ]
    plan = plan_sweep(dialogs, contact_ids={201}, allowlist_ids={102})
    assert [(item.user_id, item.actions) for item in plan] == [
        (101, ("archive", "mute")),
    ]
    rendered = [f"{item.user_id} {' '.join(item.actions)}" for item in plan]
    assert rendered == ["101 archive mute"]
    joined = "\n".join(rendered)
    assert "spam" not in joined
    assert "@" not in joined
