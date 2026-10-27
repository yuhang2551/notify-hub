"""免打扰时段和每日汇总的时间，都按本机时区算。"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

Window = tuple[time, time]

OFF = ("off", "no", "none", "关")


def parse_clock(text: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError(f"时间要写成 HH:MM，比如 08:00，不是 {text!r}")
    return time(int(m[1]), int(m[2]))


def parse_window(text: str) -> Window | None:
    """'23:00-08:00' → (23:00, 08:00)，可以跨过半夜；off 表示不设免打扰。"""
    if text.strip().lower() in OFF:
        return None
    parts = re.split(r"\s*[-–~]\s*", text.strip())
    if len(parts) != 2:
        raise ValueError(f"要写成 开始-结束，比如 23:00-08:00；不要免打扰就写 off，不是 {text!r}")
    start, end = parse_clock(parts[0]), parse_clock(parts[1])
    if start == end:
        raise ValueError("开始和结束不能是同一个时间")
    return start, end


def parse_daily(text: str) -> time | None:
    """'18:00' → 18:00；off 表示不自动发。"""
    if text.strip().lower() in OFF:
        return None
    return parse_clock(text)


def parse_times(text: str) -> list[time]:
    """'08:00,12:00,18:00' → [08:00, 12:00, 18:00]，排好序、去掉重复；逗号或空格隔开都行。"""
    parts = [part for part in re.split(r"[\s,，、]+", text.strip()) if part]
    if not parts:
        raise ValueError("至少写一个时间，比如 08:00,12:00,18:00")
    return sorted({parse_clock(part) for part in parts})


def in_window(ts: float, window: Window | None) -> bool:
    if window is None:
        return False
    now = datetime.fromtimestamp(ts).time()
    start, end = window
    if start < end:
        return start <= now < end
    return now >= start or now < end


def window_end(ts: float, window: Window) -> float:
    """ts 之后最近的一个结束时刻，比如 23:30 收到、免打扰到 08:00 → 第二天 08:00。"""
    dt = datetime.fromtimestamp(ts)
    end = datetime.combine(dt.date(), window[1])
    if end <= dt:
        end += timedelta(days=1)
    return end.timestamp()


def last_daily(ts: float, at: time) -> float:
    """ts 当时或之前最近的一个 at，比如 at=18:00：10-28 09:00 → 10-27 18:00，10-28 19:00 → 10-28 18:00。"""
    dt = datetime.fromtimestamp(ts)
    moment = datetime.combine(dt.date(), at)
    if moment > dt:
        moment -= timedelta(days=1)
    return moment.timestamp()


def fmt_window(window: Window) -> str:
    return f"{window[0]:%H:%M}–{window[1]:%H:%M}"


def fmt_times(times: list[time]) -> str:
    return "、".join(f"{t:%H:%M}" for t in times)
