import pytest

from notify_hub.channels import ChannelError
from notify_hub.config import Settings
from notify_hub.hub import RETRY_DELAYS, Hub, notify
from notify_hub.models import Level


def test_sends_right_away(hub, channel):
    assert hub.send("TimeFence 跑完了", "IC 0.031", level="urgent", source="timefence") == 1
    [msg] = channel.sent
    assert (msg.title, msg.body, msg.level, msg.source) == ("TimeFence 跑完了", "IC 0.031", Level.URGENT, "timefence")
    assert msg.created_at == 1_800_000_000.0


def test_every_call_is_sent_even_when_it_repeats(hub, channel):
    """去重是调用方的事：同样的内容调两次，就发两次。"""
    hub.send("磁盘快满了", source="backup")
    hub.send("磁盘快满了", source="backup")
    assert len(channel.sent) == 2


def test_a_temporary_failure_is_retried(hub, channel, sleeps):
    channel.failures = [ChannelError("发送消息：连不上 Lark（ConnectError）", network=True)]
    assert hub.send("要重试的") == 2
    assert [m.title for m in channel.sent] == ["要重试的"]
    assert sleeps == [RETRY_DELAYS[0]]


def test_gives_up_after_three_tries(hub, channel, sleeps):
    channel.fail_with = ChannelError("发送消息：Lark 返回 HTTP 502", network=True)
    with pytest.raises(ChannelError, match="502"):
        hub.send("一直连不上")
    assert channel.calls == 3 and channel.sent == []
    assert sleeps == [2, 5]


def test_a_permanent_failure_is_not_retried(hub, channel, sleeps):
    channel.fail_with = ChannelError("发送消息失败：HTTP 400 code=230001 invalid receive_id")
    with pytest.raises(ChannelError, match="230001"):
        hub.send("收件方写错了")
    assert channel.calls == 1 and sleeps == []


def test_missing_lark_config_fails_without_retrying(tmp_path):
    slept = []
    with (
        Hub(Settings(home=tmp_path / "hub", channel="lark"), sleep=slept.append) as hub,
        pytest.raises(ChannelError, match="LARK_APP_ID, LARK_APP_SECRET, LARK_RECEIVE_ID"),
    ):
        hub.send("还没配置好")
    assert slept == []


def test_retries_can_be_turned_off(settings, channel, sleeps):
    channel.fail_with = ChannelError("连不上 Lark", network=True)
    with Hub(settings, channel=channel, retry_delays=(), sleep=sleeps.append) as hub, pytest.raises(ChannelError):
        hub.send("只试一次")
    assert channel.calls == 1 and sleeps == []


def test_send_test(hub, channel):
    assert hub.send_test() == 1
    assert channel.sent[0].source == "notify-hub" and "推送通了" in channel.sent[0].body
    hub.send_test("自己写的一句")
    assert channel.sent[1].body == "自己写的一句"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"level": "loud"}, "urgent 或 normal"),
        ({"level": "digest"}, "urgent 或 normal"),  # 0.2 的汇总级别没有了，汇总由调用方自己做
        ({"link": "javascript:alert(1)"}, "http"),
        ({"source": "my mail"}, "来源"),
    ],
)
def test_bad_arguments_fail_before_sending(hub, channel, kwargs, message):
    with pytest.raises(ValueError, match=message):
        hub.send("x", **kwargs)
    assert channel.calls == 0


def test_module_level_notify(tmp_path, capsys):
    settings = Settings(home=tmp_path / "hub", channel="console")
    assert notify("从 Python 里调用", "正文", source="script", settings=settings) == 1
    assert "从 Python 里调用" in capsys.readouterr().out


def test_closing_the_hub_closes_the_channel(settings, channel):
    with Hub(settings, channel=channel) as hub:
        hub.send("x")
    assert channel.closed


def test_nothing_is_written_to_disk(settings, tmp_path):
    """不存消息：发完就完，~/.notify-hub 里只有你自己写的 .env。"""
    with Hub(settings) as hub:
        hub.send("x")
    assert not (tmp_path / "hub").exists()
