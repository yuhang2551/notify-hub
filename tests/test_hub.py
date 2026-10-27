import pytest

from notify_hub.channels import ChannelError
from notify_hub.config import Settings
from notify_hub.hub import BACKOFF, Hub, notify
from notify_hub.store import STALE_SENDING


def _row(hub, mid):
    return hub.outbox.get(mid)


def test_sends_right_away_and_records_it(hub, channel):
    result = hub.notify("TimeFence 跑完了", "IC 0.031", source="timefence")
    assert result.status == "sent"
    assert [m.title for m in channel.sent] == ["TimeFence 跑完了"]
    row = _row(hub, result.id)
    assert row["status"] == "sent" and row["attempts"] == 1 and row["sent_at"] is not None


def test_same_content_within_ten_minutes_is_sent_once(hub, channel, clock):
    assert hub.notify("磁盘快满了", source="backup").status == "sent"
    clock.advance(9 * 60)
    second = hub.notify("磁盘快满了", source="backup")
    assert second.status == "skipped" and "重复" in second.detail
    clock.advance(2 * 60)
    assert hub.notify("磁盘快满了", source="backup").status == "sent"
    assert len(channel.sent) == 2


def test_same_title_different_body_is_not_a_duplicate(hub, channel):
    hub.notify("实验跑完了", "第 1 组")
    assert hub.notify("实验跑完了", "第 2 组").status == "sent"
    assert len(channel.sent) == 2


def test_key_dedups_for_a_day_within_one_source(hub, channel, clock):
    assert hub.notify("面试邀请", key="msg-1", source="mail").status == "sent"
    clock.advance(3600)
    assert hub.notify("面试邀请（转发）", "内容变了也算同一件事", key="msg-1", source="mail").status == "skipped"
    assert hub.notify("别的程序用了同一个 key", key="msg-1", source="job").status == "sent"
    clock.advance(24 * 3600)
    assert hub.notify("面试邀请", key="msg-1", source="mail").status == "sent"
    assert len(channel.sent) == 3


def test_digest_level_is_kept_not_sent(hub, channel):
    result = hub.notify("订阅邮件 12 封", level="digest", source="mail")
    assert result.status == "digest"
    assert channel.sent == []
    assert _row(hub, result.id)["status"] == "digest"


def test_rate_limit_folds_the_rest_into_digest(settings, channel, clock):
    settings.rate_limit = 3
    with Hub(settings, channel=channel, clock=clock) as hub:
        results = [hub.notify(f"第 {i} 条", source="loop") for i in range(5)]
        assert [r.status for r in results] == ["sent", "sent", "sent", "digest", "digest"]
        assert "限流" in results[3].detail and "3 条" in results[3].detail
        assert hub.notify("别的来源不受影响", source="mail").status == "sent"
        clock.advance(3601)
        assert hub.notify("一小时后又能推了", source="loop").status == "sent"
    assert len(channel.sent) == 5


def test_failure_keeps_the_message_and_retries_later(hub, channel, clock):
    channel.fail_with = ChannelError("发送消息失败：HTTP 400 code=230001 invalid receive_id")
    result = hub.notify("要重发的消息")
    assert result.status == "queued" and "230001" in result.detail
    row = _row(hub, result.id)
    assert row["status"] == "pending" and row["attempts"] == 1
    assert row["next_attempt_at"] == clock() + BACKOFF[0]

    channel.fail_with = None
    assert hub.flush().sent == 0  # 还没到重试时间
    clock.advance(BACKOFF[0] + 1)
    report = hub.flush()
    assert report.sent == 1 and report.failed == 0
    assert [m.title for m in channel.sent] == ["要重发的消息"]
    assert _row(hub, result.id)["status"] == "sent"


def test_backoff_grows_with_each_failure(hub, channel, clock):
    channel.fail_with = ChannelError("boom")
    mid = hub.notify("一直失败").id
    delays = [_row(hub, mid)["next_attempt_at"] - clock()]
    for _ in range(3):
        clock.t = _row(hub, mid)["next_attempt_at"]
        hub.flush()
        delays.append(_row(hub, mid)["next_attempt_at"] - clock())
    assert delays == BACKOFF[:4]
    assert _row(hub, mid)["attempts"] == 4


def test_gives_up_after_a_day(hub, channel, clock):
    channel.fail_with = ChannelError("boom")
    mid = hub.notify("发不出去").id
    clock.advance(24 * 3600 + 1)
    report = hub.flush()
    assert report.gave_up == 1 and report.sent == 0
    assert _row(hub, mid)["status"] == "failed"


def test_network_error_stops_the_flush_early(hub, channel, clock):
    channel.fail_with = ChannelError("连不上 Lark", network=True)
    ids = [hub.notify(f"消息 {i}").id for i in range(3)]
    calls_before = channel.calls
    clock.advance(BACKOFF[0] + 1)
    report = hub.flush()
    assert report.failed == 1 and channel.calls == calls_before + 1  # 第一条连不上就停，不每条都等超时
    assert [_row(hub, i)["status"] for i in ids] == ["pending"] * 3


def test_a_successful_send_also_delivers_the_backlog(hub, channel, clock):
    channel.fail_with = ChannelError("boom")
    earlier = hub.notify("之前没发出去的").id
    clock.advance(BACKOFF[0] + 1)
    channel.fail_with = None
    assert hub.notify("新的一条").status == "sent"
    assert [m.title for m in channel.sent] == ["新的一条", "之前没发出去的"]
    assert _row(hub, earlier)["status"] == "sent"


def test_unexpected_errors_do_not_reach_the_caller(hub, channel):
    channel.fail_with = KeyError("oops")
    result = hub.notify("x")
    assert result.status == "queued" and result.detail.startswith("KeyError")


def test_missing_lark_config_queues_instead_of_failing(tmp_path, clock):
    settings = Settings(home=tmp_path / "hub", channel="lark")
    with Hub(settings, clock=clock) as hub:
        result = hub.notify("还没配置好")
    assert result.status == "queued"
    assert "LARK_APP_ID" in result.detail and "LARK_RECEIVE_ID" in result.detail


def test_two_processes_never_send_the_same_message(settings, channel, clock):
    with Hub(settings, channel=channel, clock=clock) as first, Hub(settings, channel=channel, clock=clock) as second:
        channel.fail_with = ChannelError("boom")
        mid = first.notify("只能发一次").id
        clock.advance(BACKOFF[0] + 1)
        assert first.outbox.claim(mid, clock())
        assert not second.outbox.claim(mid, clock())  # 第二个进程拿不到
        clock.advance(STALE_SENDING + 1)
        assert second.outbox.claim(mid, clock())  # 第一个进程像是崩了，过一会儿可以接手


def test_send_test_bypasses_the_outbox(hub, channel):
    msg = hub.send_test()
    assert channel.sent == [msg] and msg.source == "notify-hub"
    assert hub.outbox.counts() == {}
    channel.fail_with = ChannelError("bad")
    with pytest.raises(ChannelError):
        hub.send_test("x")


def test_bad_arguments_raise(hub):
    with pytest.raises(ValueError):
        hub.notify("x", level="loud")
    with pytest.raises(ValueError):
        hub.notify("x", link="javascript:alert(1)")


def test_module_level_notify(tmp_path, capsys):
    result = notify("从 Python 里调用", "正文", source="script", settings=Settings(home=tmp_path / "hub", channel="console"))
    assert result.status == "sent"
    assert "从 Python 里调用" in capsys.readouterr().out
