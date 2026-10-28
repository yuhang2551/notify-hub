"""发送：把参数整理成一条消息，马上发出去。

连不上 Lark 或者 Lark 一时出错（5xx、429），当场隔几秒重试；还发不出去，就抛 ChannelError 交给调用方。
notify-hub 不存消息、不定时、不汇总：什么时候发、夜里发不发、发不出去怎么办，都由调用它的程序决定。
"""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from .channels import Channel, ChannelError, build_channel
from .config import Settings, load_settings
from .models import Level, Message, make_message

# 暂时性的失败隔这么多秒再试：一共最多试 3 次，最坏多等 7 秒，再加上每次请求的超时
RETRY_DELAYS: tuple[float, ...] = (2, 5)


class Hub:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        channel: Channel | None = None,
        retry_delays: Sequence[float] | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.settings = settings or load_settings()
        self.retry_delays = RETRY_DELAYS if retry_delays is None else tuple(retry_delays)
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self._channel = channel

    def __enter__(self) -> Hub:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()

    def channel(self) -> Channel:
        if self._channel is None:
            self._channel = build_channel(self.settings)
        return self._channel

    def send(
        self,
        title: str,
        body: str = "",
        *,
        level: str | Level = Level.NORMAL,
        source: str = "default",
        link: str | None = None,
    ) -> int:
        """发一条，返回试了几次。参数写错抛 ValueError；重试完还发不出去抛 ChannelError。"""
        msg = make_message(title, body, level=level, source=source, link=link, created_at=self.clock())
        return self.deliver(msg)

    def deliver(self, msg: Message) -> int:
        """发出去，返回试了几次。只有连不上、Lark 一时出错才重试；配置不对、没权限这类错误重试也没用，直接抛出。"""
        attempt = 0
        while True:
            attempt += 1
            try:
                self.channel().send(msg)
                return attempt
            except ChannelError as exc:
                if not exc.network or attempt > len(self.retry_delays):
                    raise
                self.sleep(self.retry_delays[attempt - 1])

    def send_test(self, text: str = "") -> int:
        return self.send("notify-hub 测试消息", text or "收到这条，说明推送通了 ✅", source="notify-hub")


def notify(
    title: str,
    body: str = "",
    *,
    level: str | Level = Level.NORMAL,
    source: str = "default",
    link: str | None = None,
    settings: Settings | None = None,
) -> int:
    """Python 里直接用：from notify_hub import notify。返回试了几次；发不出去抛 ChannelError，参数写错抛 ValueError。"""
    with Hub(settings) as hub:
        return hub.send(title, body, level=level, source=source, link=link)
