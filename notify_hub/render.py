"""把消息渲染成 Lark 卡片，或者终端里的一段文字。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .models import Level, Message, link_domain

BODY_MAX = 3000
ITEM_BODY_MAX = 200  # 合并卡片里每条正文最多这么长
BUNDLE_ITEMS_MAX = 20  # 免打扰卡片最多列这么多条
DIGEST_PER_SOURCE_MAX = 15  # 每日汇总里每个来源最多列这么多条标题
CARD_MAX_BYTES = 25_000  # Lark 卡片消息的请求体上限是 30 KB；超了就少列几条

COLOR = {Level.URGENT: "red", Level.NORMAL: "blue", Level.DIGEST: "grey"}
LABEL = {Level.URGENT: "紧急", Level.NORMAL: "普通", Level.DIGEST: "汇总"}
ICON = {Level.URGENT: "🔴", Level.NORMAL: "🔵", Level.DIGEST: "⚪"}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def footer(msg: Message) -> str:
    when = time.strftime("%m-%d %H:%M", time.localtime(msg.created_at or time.time()))
    return f"{msg.source} · {LABEL[msg.level]} · {when}"


def _when(item: Message, bundle: Message) -> str:
    """合并卡片里每条的时间：和卡片同一天只写几点，不同天带上日期。"""
    t, b = time.localtime(item.created_at), time.localtime(bundle.created_at or time.time())
    return time.strftime("%H:%M" if t[:3] == b[:3] else "%m-%d %H:%M", t)


def _plain(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "plain_text", "content": content}}


def _note(content: str) -> dict[str, Any]:
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": content}]}


def _button(msg: Message) -> dict[str, Any]:
    return {
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"打开 {link_domain(msg.link or '')}"},
            "type": "danger" if msg.level is Level.URGENT else "primary",
            "url": msg.link,
        }],
    }


def _shell(msg: Message, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": COLOR[msg.level], "title": {"tag": "plain_text", "content": msg.title}},
        "elements": [*elements, _note(footer(msg))],
    }


def card(msg: Message) -> dict[str, Any]:
    """Lark 消息卡片。正文按纯文本显示（不渲染 Markdown 链接），只有调用方明确传的 link 才变成按钮。"""
    if msg.items:
        return _fit(msg, _digest_elements if msg.level is Level.DIGEST else _held_elements)
    elements: list[dict[str, Any]] = []
    if msg.body:
        elements.append(_plain(_clip(msg.body, BODY_MAX)))
    if msg.link:
        elements.append(_button(msg))
    return _shell(msg, elements)


def by_source(items: tuple[Message, ...]) -> list[tuple[str, list[Message]]]:
    """按来源分组，来源按第一次出现的先后排。"""
    groups: dict[str, list[Message]] = {}
    for item in items:
        groups.setdefault(item.source, []).append(item)
    return list(groups.items())


def _held_elements(msg: Message, limit: int) -> list[dict[str, Any]]:
    """免打扰卡片：每条一段，标题、正文开头、来源和时间，有链接的带按钮。"""
    elements: list[dict[str, Any]] = []
    for item in msg.items[:limit]:
        if elements:
            elements.append({"tag": "hr"})
        elements.append(_plain(item.title + (f"\n{_clip(item.body, ITEM_BODY_MAX)}" if item.body else "")))
        elements.append(_note(f"{item.source} · {_when(item, msg)}"))
        if item.link:
            elements.append(_button(item))
    if len(msg.items) > limit:
        elements.append(_plain(f"…还有 {len(msg.items) - limit} 条没列出"))
    return elements


def _digest_lines(source: str, items: list[Message], bundle: Message, limit: int) -> list[str]:
    lines = [f"{source} · {len(items)} 条"]
    lines += [f"• {_when(item, bundle)} {item.title}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"…还有 {len(items) - limit} 条")
    return lines


def _digest_elements(msg: Message, limit: int) -> list[dict[str, Any]]:
    """每日汇总：按来源分段，每段列标题。"""
    elements: list[dict[str, Any]] = []
    for source, items in by_source(msg.items):
        if elements:
            elements.append({"tag": "hr"})
        elements.append(_plain("\n".join(_digest_lines(source, items, msg, min(limit, DIGEST_PER_SOURCE_MAX)))))
    return elements


def _fit(msg: Message, build: Callable[[Message, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """合并卡片太大时少列几条，保证 Lark 收得下。"""
    limit = BUNDLE_ITEMS_MAX if build is _held_elements else DIGEST_PER_SOURCE_MAX
    while True:
        result = _shell(msg, [*build(msg, limit), {"tag": "hr"}])  # 分隔线隔开最后一条和页脚
        if limit <= 1 or len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= CARD_MAX_BYTES:
            return result
        limit = max(1, limit * 2 // 3)


def text(msg: Message) -> str:
    """终端里看的样子（console 渠道和试用时用）。"""
    lines = [f"{ICON[msg.level]} {msg.title}"]
    if msg.items and msg.level is Level.DIGEST:
        for source, items in by_source(msg.items):
            lines += ["  " + line for line in _digest_lines(source, items, msg, DIGEST_PER_SOURCE_MAX)]
    elif msg.items:
        for item in msg.items[:BUNDLE_ITEMS_MAX]:
            lines.append(f"  {_when(item, msg)} · {item.source} · {item.title}")
            if item.body:
                lines.append(f"    {_clip(item.body, ITEM_BODY_MAX)}")
            if item.link:
                lines.append(f"    打开 {link_domain(item.link)}：{item.link}")
        if len(msg.items) > BUNDLE_ITEMS_MAX:
            lines.append(f"  …还有 {len(msg.items) - BUNDLE_ITEMS_MAX} 条没列出")
    else:
        if msg.body:
            lines.append(_clip(msg.body, BODY_MAX))
        if msg.link:
            lines.append(f"打开 {link_domain(msg.link)}：{msg.link}")
    lines.append(footer(msg))
    return "\n".join(lines)
