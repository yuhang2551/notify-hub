from notify_hub.claude_hook import STOP_BODY_MAX, from_hook


def test_permission_prompt():
    notice = from_hook({
        "hook_event_name": "Notification",
        "cwd": "/Users/me/notify-hub",
        "message": "Claude needs your permission to use Bash",
        "notification_type": "permission_prompt",
    })
    assert notice.title == "notify-hub · Claude Code 等你确认"
    assert notice.body == "Claude needs your permission to use Bash"


def test_idle_and_other_notifications():
    idle = from_hook({"hook_event_name": "Notification", "cwd": "/w/demo", "message": "Claude is waiting for your input", "notification_type": "idle_prompt"})
    assert idle.title == "demo · Claude Code 在等你回复"
    other = from_hook({"hook_event_name": "Notification", "message": "hi", "title": "插件提醒", "notification_type": "plugin_notification"})
    assert other.title == "Claude Code 插件提醒" and other.body == "hi"


def test_stop_sends_the_start_of_the_last_reply():
    notice = from_hook({
        "hook_event_name": "Stop",
        "cwd": "/w/demo",
        "stop_hook_active": False,
        "last_assistant_message": "改完了。" + "细节" * 300,
        "background_tasks": [],
    })
    assert notice.title == "demo · Claude Code 做完了"
    assert notice.body.startswith("改完了。") and len(notice.body) == STOP_BODY_MAX


def test_events_that_are_not_worth_a_push():
    assert from_hook({"hook_event_name": "Stop", "stop_hook_active": True}) is None  # 被 stop hook 拦下，还会接着干
    assert from_hook({"hook_event_name": "Stop", "background_tasks": [{"id": "t1"}]}) is None  # 在等后台任务
    assert from_hook({"hook_event_name": "PreToolUse"}) is None
