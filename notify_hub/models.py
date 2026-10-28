"""消息和级别。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

TITLE_MAX = 120
SOURCE_MAX = 40


class Level(str, Enum):
    """级别只决定卡片的样子；两种都是收到就发，什么时候发由调用方决定。"""

    URGENT = "urgent"  # 红色卡片
    NORMAL = "normal"  # 蓝色卡片

    @classmethod
    def parse(cls, value: str | Level) -> Level:
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"级别只能是 urgent 或 normal，不是 {value!r}") from None


@dataclass(frozen=True)
class Message:
    title: str
    body: str = ""
    level: Level = Level.NORMAL
    source: str = "default"
    link: str | None = None
    created_at: float = 0.0


def make_message(
    title: str,
    body: str = "",
    *,
    level: str | Level = Level.NORMAL,
    source: str = "default",
    link: str | None = None,
    created_at: float = 0.0,
) -> Message:
    """检查参数并整理成一条消息。参数不对抛 ValueError（这是调用方写错了，不是推送失败）。"""
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("标题不能为空")
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1] + "…"
    source = (source or "").strip() or "default"
    if len(source) > SOURCE_MAX or any(c.isspace() for c in source):
        raise ValueError(f"来源要短一点、不带空格，比如 mail、timefence：{source!r}")
    return Message(
        title=title,
        body=(body or "").strip(),
        level=Level.parse(level),
        source=source,
        link=check_link(link),
        created_at=created_at,
    )


def check_link(link: str | None) -> str | None:
    """只接受 http(s) 网址；卡片按钮上会写出它的域名，钓鱼链接没法伪装。"""
    if not link:
        return None
    parsed = urlparse(link.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"链接只能是 http:// 或 https:// 开头的网址：{link!r}")
    return link.strip()


def link_domain(link: str) -> str:
    host = urlparse(link).hostname or ""
    return host.removeprefix("www.")
