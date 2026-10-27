"""把消息渲染成 Lark 卡片，或者终端里的一段文字。"""
from __future__ import annotations

import time
from typing import Any

from .models import Level, Message, link_domain

BODY_MAX = 3000

COLOR = {Level.URGENT: "red", Level.NORMAL: "blue", Level.DIGEST: "grey"}
LABEL = {Level.URGENT: "紧急", Level.NORMAL: "普通", Level.DIGEST: "汇总"}
ICON = {Level.URGENT: "🔴", Level.NORMAL: "🔵", Level.DIGEST: "⚪"}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def footer(msg: Message) -> str:
    when = time.strftime("%m-%d %H:%M", time.localtime(msg.created_at or time.time()))
    return f"{msg.source} · {LABEL[msg.level]} · {when}"


def card(msg: Message) -> dict[str, Any]:
    """Lark 消息卡片。正文按纯文本显示（不渲染 Markdown 链接），只有调用方明确传的 link 才变成按钮。"""
    elements: list[dict[str, Any]] = []
    if msg.body:
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": _clip(msg.body, BODY_MAX)}})
    if msg.link:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"打开 {link_domain(msg.link)}"},
                "type": "danger" if msg.level is Level.URGENT else "primary",
                "url": msg.link,
            }],
        })
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": footer(msg)}]})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": COLOR[msg.level], "title": {"tag": "plain_text", "content": msg.title}},
        "elements": elements,
    }


def text(msg: Message) -> str:
    """终端里看的样子（console 渠道和试用时用）。"""
    lines = [f"{ICON[msg.level]} {msg.title}"]
    if msg.body:
        lines.append(_clip(msg.body, BODY_MAX))
    if msg.link:
        lines.append(f"打开 {link_domain(msg.link)}：{msg.link}")
    lines.append(footer(msg))
    return "\n".join(lines)
