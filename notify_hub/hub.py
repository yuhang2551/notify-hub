"""核心：收下一条通知，决定现在发、等免打扰结束、进汇总还是不发，先写发件箱再发送，失败的留着重发。"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from .channels import Channel, ChannelError, build_channel
from .config import Settings, load_settings
from .models import Level, Message, make_message
from .store import Outbox, row_to_message
from .timing import fmt_window, in_window, last_daily, window_end

# 第 n 次失败后隔多久再试（秒）；之后都是一小时一次，直到 give_up_hours 放弃
BACKOFF = [60, 300, 900, 1800, 3600]
RATE_WINDOW = 3600


@dataclass
class Result:
    id: int | None
    status: str  # sent | queued（没发出去，留在发件箱等重发）| held（等免打扰结束）| digest | skipped
    detail: str = ""
    network: bool = False  # 失败是因为连不上


@dataclass
class FlushReport:
    sent: int = 0
    failed: int = 0
    gave_up: int = 0
    last_error: str = ""
    held: int = 0  # 免打扰结束，合成一张卡的条数
    digest: int = 0  # 进了每日汇总卡片的条数

    def empty(self) -> bool:
        return not (self.sent or self.failed or self.gave_up or self.held or self.digest)


def held_title(count: int) -> str:
    return f"免打扰期间收到 {count} 条通知"


def digest_title(count: int) -> str:
    return f"每日汇总 · {count} 条"


def dedup_key(msg: Message) -> str:
    if msg.key:
        return f"key:{msg.source}:{msg.key}"
    digest = hashlib.sha256(f"{msg.source}\0{msg.title}\0{msg.body}".encode("utf-8")).hexdigest()[:32]
    return f"content:{digest}"


class Hub:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        channel: Channel | None = None,
        outbox: Outbox | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.settings = settings or load_settings()
        self.clock = clock
        self.outbox = outbox or Outbox(self.settings.db_path)
        self._channel = channel
        # 第一次用的时间：第一份每日汇总在这之后的第一个汇总时刻发
        self.outbox.meta_init("last_digest_at", repr(self.clock()))

    def __enter__(self) -> Hub:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        self.outbox.close()

    def channel(self) -> Channel:
        if self._channel is None:
            self._channel = build_channel(self.settings)
        return self._channel

    def is_quiet(self, now: float | None = None) -> bool:
        return in_window(self.clock() if now is None else now, self.settings.quiet_window)

    # ---- 收消息 ----

    def notify(
        self,
        title: str,
        body: str = "",
        *,
        level: str | Level = Level.NORMAL,
        source: str = "default",
        link: str | None = None,
        key: str | None = None,
    ) -> Result:
        """推送失败不抛异常：消息留在发件箱里，返回 status='queued'。只有参数写错才抛 ValueError。"""
        now = self.clock()
        msg = make_message(title, body, level=level, source=source, link=link, key=key, created_at=now)

        key_ = dedup_key(msg)
        window = self.settings.key_hours * 3600 if msg.key else self.settings.dedup_minutes * 60
        dup = self.outbox.recent_duplicate(key_, now - window)
        if dup is not None:
            mid = self.outbox.add(msg, dedup_key=key_, status="skipped", now=now, note=f"和 #{dup['id']} 重复")
            return Result(mid, "skipped", f"和 #{dup['id']} 重复，不再推送")

        if msg.level is Level.DIGEST:
            mid = self.outbox.add(msg, dedup_key=key_, status="digest", now=now)
            return Result(mid, "digest", "进汇总")

        pushed = self.outbox.pushed_count(msg.source, now - RATE_WINDOW)
        if pushed >= self.settings.rate_limit:
            note = f"限流：{msg.source} 这一小时已经推了 {pushed} 条"
            mid = self.outbox.add(msg, dedup_key=key_, status="digest", now=now, note=note)
            return Result(mid, "digest", f"{note}，这条进汇总")

        quiet = self.settings.quiet_window
        if msg.level is Level.NORMAL and quiet and in_window(now, quiet):
            mid = self.outbox.add(msg, dedup_key=key_, status="held", now=now)
            until = time.strftime("%H:%M", time.localtime(window_end(now, quiet)))
            return Result(mid, "held", f"免打扰时段（{fmt_window(quiet)}），{until} 以后和这段时间的其他通知合成一张卡发")

        mid = self.outbox.add(msg, dedup_key=key_, status="pending", now=now)
        result = self._deliver(mid)
        if result.status == "sent":
            self.flush(limit=10)  # 通道是好的，顺手把之前没发出去的补上
        return result

    # ---- 发送和重发 ----

    def _deliver(self, mid: int) -> Result:
        now = self.clock()
        if not self.outbox.claim(mid, now):
            return Result(mid, "queued", "别的进程正在发这一条")
        row = self.outbox.get(mid)
        items = tuple(row_to_message(r) for r in self.outbox.members(mid)) if row["kind"] == "bundle" else ()
        try:
            self.channel().send(row_to_message(row, items))
        except Exception as exc:  # noqa: BLE001 —— 任何失败都留在发件箱，不让调用方崩
            network = isinstance(exc, ChannelError) and exc.network
            error = str(exc) if isinstance(exc, ChannelError) else f"{exc.__class__.__name__}: {exc}"
            delay = BACKOFF[min(row["attempts"], len(BACKOFF) - 1)]
            self.outbox.mark_retry(mid, error=error, next_attempt_at=now + delay)
            return Result(mid, "queued", error, network=network)
        self.outbox.mark_sent(mid, self.clock())
        return Result(mid, "sent")

    def flush(self, limit: int = 50) -> FlushReport:
        """补上到时间该做的事：免打扰结束就把攒下的合成一张卡，到了汇总时间就发每日汇总，
        重发到时间的消息，放弃太久发不出去的。连不上 Lark 时停下，剩下的下次再说。"""
        now = self.clock()
        report = FlushReport(gave_up=self.outbox.give_up_older_than(now - self.settings.give_up_hours * 3600))
        report.held = self._release_held(now)
        report.digest = self._digest_if_due(now)
        for mid in self.outbox.due(now, limit):
            result = self._deliver(mid)
            if result.status == "sent":
                report.sent += 1
                continue
            report.failed += 1
            report.last_error = result.detail
            if result.network:
                break
        return report

    def _release_held(self, now: float) -> int:
        if self.is_quiet(now):
            return 0
        made = self.outbox.make_bundle(status="held", level=Level.NORMAL, title=held_title, now=now)
        return made[1] if made else 0

    def _digest_if_due(self, now: float) -> int:
        """每天到了汇总时间（并且不在免打扰时段）发一次。电脑睡着错过了，醒来后补发。"""
        at = self.settings.digest_at
        if at is None or self.is_quiet(now):
            return 0
        last = self.outbox.meta_get("last_digest_at")
        if last is not None and float(last) >= last_daily(now, at):
            return 0  # 这一次的汇总已经发过了
        if not self.outbox.meta_swap("last_digest_at", last, repr(now)):
            return 0  # 别的进程刚刚发了
        made = self.outbox.make_bundle(status="digest", level=Level.DIGEST, title=digest_title, now=now)
        return made[1] if made else 0

    def digest_now(self) -> Result | None:
        """不等到点，现在就把等着汇总的合成一张卡发出去。没有要汇总的返回 None。"""
        made = self.outbox.make_bundle(status="digest", level=Level.DIGEST, title=digest_title, now=self.clock())
        if made is None:
            return None
        result = self._deliver(made[0])
        return replace(result, detail=result.detail or f"{made[1]} 条合成一张汇总卡片")

    def preview(self, status: str) -> Message | None:
        """不改发件箱，看看现在合成卡片会是什么样（status 是 digest 或 held）。"""
        rows = self.outbox.with_status(status)
        if not rows:
            return None
        title, level = (digest_title, Level.DIGEST) if status == "digest" else (held_title, Level.NORMAL)
        return Message(
            title=title(len(rows)), level=level, source="notify-hub", created_at=self.clock(),
            items=tuple(row_to_message(r) for r in rows),
        )

    def send_test(self, text: str = "") -> Message:
        """不进发件箱，直接发一条，用来检查配置。失败抛 ChannelError。"""
        msg = make_message(
            "notify-hub 测试消息", text or "收到这条，说明推送通了 ✅",
            source="notify-hub", created_at=self.clock(),
        )
        self.channel().send(msg)
        return msg

    def status(self) -> dict[str, Any]:
        return {
            "counts": self.outbox.counts(),
            "oldest_waiting": self.outbox.oldest_waiting(),
            "problems": self.outbox.recent_problems(),
            "quiet_now": self.is_quiet(),
        }


def notify(
    title: str,
    body: str = "",
    *,
    level: str | Level = Level.NORMAL,
    source: str = "default",
    link: str | None = None,
    key: str | None = None,
    settings: Settings | None = None,
) -> Result:
    """Python 里直接用：from notify_hub import notify。推送失败不抛异常，消息留在发件箱等重发。"""
    with Hub(settings) as hub:
        return hub.notify(title, body, level=level, source=source, link=link, key=key)
