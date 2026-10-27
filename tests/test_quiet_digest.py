"""免打扰时段和每日汇总。时钟从 2027-01-15 中午 12:00（UTC+4）开始，默认免打扰 23:00–08:00、汇总 18:00。"""
from notify_hub.channels import ChannelError
from notify_hub.hub import BACKOFF, Hub
from notify_hub.models import Level

HOUR = 3600


def _night(clock):
    clock.advance(11.5 * HOUR)  # 当晚 23:30


def test_normal_waits_at_night_but_urgent_goes_out(hub, channel, clock):
    _night(clock)
    held = hub.notify("实验跑完了", "IC 0.031", source="exp")
    assert held.status == "held" and "08:00" in held.detail
    assert hub.notify("服务挂了", level="urgent", source="ops").status == "sent"
    assert [m.title for m in channel.sent] == ["服务挂了"]
    assert hub.flush().held == 0  # 还在免打扰时段


def test_morning_flush_bundles_the_night_into_one_card(hub, channel, clock):
    _night(clock)
    hub.notify("实验跑完了", "IC 0.031", source="exp", link="https://example.com/r/1")
    clock.advance(2 * HOUR)
    hub.notify("导师回复", "周三组会改到下午", source="mail")
    clock.advance(7 * HOUR)  # 08:30
    report = hub.flush()
    assert report.held == 2 and report.sent == 1
    [card] = channel.sent
    assert card.title == "免打扰期间收到 2 条通知" and card.source == "notify-hub" and card.level is Level.NORMAL
    assert [m.title for m in card.items] == ["实验跑完了", "导师回复"]
    assert card.items[0].link == "https://example.com/r/1"
    assert hub.flush().sent == 0  # 只发一次
    assert hub.outbox.counts() == {"bundled": 2, "sent": 1}


def test_a_send_in_the_morning_also_releases_the_night(hub, channel, clock):
    _night(clock)
    hub.notify("夜里的", source="exp")
    clock.advance(9 * HOUR)  # 08:30
    assert hub.notify("早上的", source="exp").status == "sent"
    assert [m.title for m in channel.sent] == ["早上的", "免打扰期间收到 1 条通知"]


def test_quiet_hours_off(settings, channel, clock):
    settings.quiet_hours = "off"
    with Hub(settings, channel=channel, clock=clock) as hub:
        _night(clock)
        assert hub.notify("夜里也发").status == "sent"


def test_held_messages_count_for_rate_limit_and_dedup(settings, channel, clock):
    settings.rate_limit = 2
    with Hub(settings, channel=channel, clock=clock) as hub:
        _night(clock)
        assert [hub.notify(f"第 {i} 条", source="loop").status for i in range(3)] == ["held", "held", "digest"]
        assert hub.notify("第 0 条", source="loop").status == "skipped"


def test_digest_goes_out_once_a_day_after_six(hub, channel, clock):
    hub.notify("订阅邮件", level="digest", source="mail")
    hub.notify("日报", level="digest", source="stats")
    hub.notify("又一封订阅", level="digest", source="mail")
    assert hub.flush().digest == 0  # 中午，还没到 18:00
    clock.advance(6 * HOUR + 60)  # 18:01
    report = hub.flush()
    assert report.digest == 3 and report.sent == 1
    [card] = channel.sent
    assert card.title == "每日汇总 · 3 条" and card.level is Level.DIGEST
    assert [(m.source, m.title) for m in card.items] == [("mail", "订阅邮件"), ("stats", "日报"), ("mail", "又一封订阅")]
    hub.notify("晚上来的", level="digest", source="mail")
    clock.advance(HOUR)
    assert hub.flush().digest == 0  # 今天的发过了，晚来的等明天
    clock.advance(23 * HOUR)  # 第二天 18:01
    assert hub.flush().digest == 1


def test_digest_waits_for_quiet_hours_to_end(settings, channel, clock):
    settings.digest_time = "23:30"
    with Hub(settings, channel=channel, clock=clock) as hub:
        hub.notify("日报", level="digest", source="stats")
        clock.advance(11.6 * HOUR)  # 23:36，在免打扰时段里
        assert hub.flush().digest == 0
        clock.advance(8.5 * HOUR)  # 第二天 08:06
        assert hub.flush().digest == 1


def test_missed_digest_is_sent_when_the_computer_wakes_up(hub, channel, clock):
    hub.notify("日报", level="digest", source="stats")
    clock.advance(26 * HOUR)  # 睡过了 18:00，第二天 14:00 才醒
    assert hub.flush().digest == 1


def test_first_digest_comes_at_the_next_digest_time(settings, channel, clock):
    clock.advance(7 * HOUR)  # 19:00 第一次用
    with Hub(settings, channel=channel, clock=clock) as hub:
        hub.notify("日报", level="digest", source="stats")
        assert hub.flush().digest == 0  # 今天的 18:00 已经过了，等明天
        clock.advance(23 * HOUR + 60)
        assert hub.flush().digest == 1


def test_digest_off_and_manual_digest(settings, channel, clock):
    settings.digest_time = "off"
    with Hub(settings, channel=channel, clock=clock) as hub:
        hub.notify("日报", level="digest", source="stats")
        clock.advance(7 * HOUR)
        assert hub.flush().digest == 0
        result = hub.digest_now()
        assert result.status == "sent" and "1 条" in result.detail
        assert hub.digest_now() is None
    assert [m.title for m in channel.sent] == ["每日汇总 · 1 条"]


def test_rate_limited_messages_join_the_digest(settings, channel, clock):
    settings.rate_limit = 1
    with Hub(settings, channel=channel, clock=clock) as hub:
        hub.notify("第 1 条", source="loop")
        assert hub.notify("第 2 条", source="loop").status == "digest"
        clock.advance(6 * HOUR + 60)
        hub.flush()
    assert [m.title for m in channel.sent[-1].items] == ["第 2 条"]


def test_preview_changes_nothing(hub, channel):
    hub.notify("日报", level="digest", source="stats")
    preview = hub.preview("digest")
    assert preview.title == "每日汇总 · 1 条" and [m.title for m in preview.items] == ["日报"]
    assert hub.outbox.counts() == {"digest": 1} and channel.sent == []
    assert hub.preview("held") is None


def test_a_failed_card_is_retried_like_any_message(hub, channel, clock):
    _night(clock)
    hub.notify("夜里的", source="exp")
    clock.advance(9 * HOUR)
    channel.fail_with = ChannelError("boom")
    report = hub.flush()
    assert report.held == 1 and report.failed == 1
    channel.fail_with = None
    clock.advance(BACKOFF[0] + 1)
    assert hub.flush().sent == 1
    assert [m.items[0].title for m in channel.sent] == ["夜里的"]


def test_two_processes_send_only_one_digest(settings, channel, clock):
    with Hub(settings, channel=channel, clock=clock) as first, Hub(settings, channel=channel, clock=clock) as second:
        first.notify("日报", level="digest", source="stats")
        clock.advance(6 * HOUR + 60)
        assert first.flush().digest == 1
        assert second.flush().digest == 0
    assert len(channel.sent) == 1
