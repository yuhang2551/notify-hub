"""接 Claude Code 的 hooks：把 hook 从标准输入传来的 JSON 变成一条通知。

- Notification：Claude 等你确认（permission_prompt）、回完话一分钟你没动（idle_prompt）等。
  这两种 Claude Code 只在你像是离开了终端时才发，正好用来推到手机。
- Stop：Claude 回完一轮。交互使用时每轮都有，比较吵，适合只给 claude -p 这类无人值守的长任务加
  （claude -p --settings '{"hooks": {"Stop": [...]}}'）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

SOURCE = "claude-code"
STOP_BODY_MAX = 300

WHAT = {
    "permission_prompt": "等你确认",
    "idle_prompt": "在等你回复",
    "elicitation_dialog": "等你填写",
    "elicitation_url_dialog": "等你打开网页",
    "agent_needs_input": "后台会话在等你",
    "agent_completed": "后台会话结束了",
}


@dataclass
class HookNotice:
    title: str
    body: str


def from_hook(data: dict[str, Any]) -> HookNotice | None:
    """不需要推送的事件返回 None。"""
    event = data.get("hook_event_name")
    project = PurePath(str(data.get("cwd") or "")).name
    where = f"{project} · " if project else ""
    if event == "Notification":
        what = WHAT.get(str(data.get("notification_type") or "")) or str(data.get("title") or "通知")
        return HookNotice(f"{where}Claude Code {what}", str(data.get("message") or ""))
    if event == "Stop":
        if data.get("stop_hook_active") or data.get("background_tasks"):
            return None  # 还会接着干（被 stop hook 拦下，或者在等后台任务），不算做完
        last = str(data.get("last_assistant_message") or "").strip()
        if len(last) > STOP_BODY_MAX:
            last = last[: STOP_BODY_MAX - 1] + "…"
        return HookNotice(f"{where}Claude Code 做完了", last)
    return None
