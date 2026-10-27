from datetime import time as dtime

import pytest

from notify_hub.timing import fmt_window, in_window, last_daily, parse_clock, parse_daily, parse_window, window_end

NOON = 1_800_000_000.0  # 2027-01-15 12:00（测试时区 UTC+4）
HOUR = 3600


def test_parse():
    assert parse_clock("8:05") == dtime(8, 5)
    assert parse_window("23:00-08:00") == (dtime(23), dtime(8))
    assert parse_window(" 22:30 – 7:00 ") == (dtime(22, 30), dtime(7))
    assert parse_window("off") is None and parse_daily("OFF") is None
    assert parse_daily("18:00") == dtime(18)


@pytest.mark.parametrize("bad", ["25:00-08:00", "8", "8:5-9:00", "23:00", "23:00-23:00", "a-b"])
def test_bad_windows(bad):
    with pytest.raises(ValueError):
        parse_window(bad)


def test_window_across_midnight():
    window = (dtime(23), dtime(8))
    assert not in_window(NOON, window)
    assert in_window(NOON + 11 * HOUR, window)  # 23:00
    assert in_window(NOON + 15 * HOUR, window)  # 03:00
    assert not in_window(NOON + 20 * HOUR, window)  # 08:00 正好结束
    assert not in_window(NOON + 15 * HOUR, None)


def test_window_within_a_day():
    window = (dtime(13), dtime(14))
    assert in_window(NOON + 1.5 * HOUR, window) and not in_window(NOON, window)


def test_window_end_and_last_daily():
    window = (dtime(23), dtime(8))
    assert window_end(NOON + 11.5 * HOUR, window) == NOON + 20 * HOUR  # 23:30 → 第二天 08:00
    assert window_end(NOON + 15 * HOUR, window) == NOON + 20 * HOUR  # 03:00 → 当天 08:00
    assert last_daily(NOON, dtime(18)) == NOON - 18 * HOUR  # 中午 → 前一天 18:00
    assert last_daily(NOON + 7 * HOUR, dtime(18)) == NOON + 6 * HOUR  # 19:00 → 当天 18:00
    assert last_daily(NOON + 6 * HOUR, dtime(18)) == NOON + 6 * HOUR  # 正好 18:00
    assert fmt_window(window) == "23:00–08:00"
