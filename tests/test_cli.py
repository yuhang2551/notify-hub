import json
import os
import stat

import httpx
import pytest
from typer.testing import CliRunner

from notify_hub import cli
from notify_hub import hub as hub_module
from notify_hub.channels import ChannelError
from notify_hub.cli import app, fill_env

runner = CliRunner()


def _console(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_CHANNEL", "console")


class FlakyLark:
    """假的 Lark：先连不上 down 次，之后正常收。"""

    name = "lark"

    def __init__(self, down: int):
        self.down = down
        self.titles: list[str] = []

    def send(self, msg) -> None:
        self.titles.append(msg.title)
        if len(self.titles) <= self.down:
            raise ChannelError("发送消息：连不上 Lark（ConnectError）", network=True)

    def close(self) -> None:
        pass


def _flaky(monkeypatch, down: int) -> tuple[FlakyLark, list[float]]:
    lark, slept = FlakyLark(down), []
    monkeypatch.setattr(hub_module, "build_channel", lambda settings: lark)
    monkeypatch.setattr(hub_module.time, "sleep", slept.append)
    return lark, slept


def test_send_prints_the_card_and_says_it_was_sent(monkeypatch):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "TimeFence 跑完了", "--body", "IC 0.031", "--source", "timefence"])
    assert result.exit_code == 0, result.output
    assert "🔵 TimeFence 跑完了" in result.output and "IC 0.031" in result.output
    assert result.output.rstrip().endswith("✅ 已推送")


def test_send_reads_body_from_stdin(monkeypatch):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "备份失败", "--body", "-", "--level", "urgent"], input="磁盘满了\n")
    assert result.exit_code == 0
    assert "🔴 备份失败" in result.output and "磁盘满了" in result.output


def test_quiet(monkeypatch):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "安静", "-q"])
    assert result.exit_code == 0 and "安静" in result.output and "已推送" not in result.output


@pytest.mark.parametrize("args", [["--level", "loud"], ["--level", "digest"], ["--link", "javascript:alert(1)"], ["--source", "my mail"]])
def test_bad_arguments_exit_2(monkeypatch, args):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "x", *args])
    assert result.exit_code == 2 and "❌" in result.output


def test_the_old_key_option_is_still_accepted(monkeypatch):
    """0.2 版去重用的 --key 还能传，只是不起作用：旧的调用方不会因此报错。"""
    _console(monkeypatch)
    for _ in range(2):
        result = runner.invoke(app, ["send", "面试邀请", "--key", "msg-1"])
        assert result.exit_code == 0 and "✅ 已推送" in result.output
    assert "--key" not in runner.invoke(app, ["send", "--help"]).output


def test_send_without_config_exits_1():
    result = runner.invoke(app, ["send", "还没配好"])
    assert result.exit_code == 1
    assert "❌ 没发出去" in result.output and "LARK_APP_ID" in result.output


def test_send_retries_and_says_so(monkeypatch):
    lark, slept = _flaky(monkeypatch, down=1)
    result = runner.invoke(app, ["send", "网络抖了一下"])
    assert result.exit_code == 0 and "✅ 已推送（试了 2 次）" in result.output
    assert lark.titles == ["网络抖了一下"] * 2 and slept == [2]


def test_send_gives_up_with_exit_1(monkeypatch):
    lark, slept = _flaky(monkeypatch, down=99)
    result = runner.invoke(app, ["send", "断网了"])
    assert result.exit_code == 1 and "❌ 没发出去" in result.output and "连不上 Lark" in result.output
    assert lark.titles == ["断网了"] * 3 and slept == [2, 5]


def test_test_command(monkeypatch):
    failed = runner.invoke(app, ["test"])
    assert failed.exit_code == 1 and "LARK_APP_ID" in failed.output
    _console(monkeypatch)
    ok = runner.invoke(app, ["test", "你好"])
    assert ok.exit_code == 0 and "你好" in ok.output and "已通过 console" in ok.output


def test_bad_config_is_explained(tmp_path):
    env = tmp_path / "bad.env"
    env.write_text("NOTIFY_HUB_CHANNEL=email\n", encoding="utf-8")
    result = runner.invoke(app, ["--env", str(env), "send", "x"])
    assert result.exit_code == 1 and "NOTIFY_HUB_CHANNEL" in result.output


def test_an_old_env_file_still_works(tmp_path):
    """0.2 的免打扰、汇总、限流配置还留在 .env 里也没关系：不读，照常马上发。"""
    env = tmp_path / "old.env"
    env.write_text(
        "NOTIFY_HUB_CHANNEL=console\nNOTIFY_HUB_QUIET_HOURS=00:00-23:59\nNOTIFY_HUB_DIGEST_TIME=18:00\nNOTIFY_HUB_RATE_LIMIT=0\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["--env", str(env), "send", "照常发"])
    assert result.exit_code == 0 and "照常发" in result.output and "✅ 已推送" in result.output


@pytest.mark.parametrize("command", ["flush", "digest", "status", "schedule"])
def test_the_scheduling_commands_are_gone(command):
    assert runner.invoke(app, [command]).exit_code == 2


def test_init_copies_lark_settings_without_printing_secrets(tmp_path):
    source = tmp_path / "mail.env"
    source.write_text(
        "MAIL_MONITOR_LLM=claude\nLARK_APP_ID=cli_abc\nLARK_APP_SECRET=very-secret-value\nLARK_RECEIVE_ID=oc_123\n# LARK_RECEIVE_ID_TYPE=chat_id\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "--from", str(source)])
    assert result.exit_code == 0, result.output
    assert "very-secret-value" not in result.output and "LARK_APP_SECRET" in result.output

    target = tmp_path / "hub" / ".env"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    text = target.read_text(encoding="utf-8")
    assert "LARK_APP_ID=cli_abc\n" in text and "LARK_APP_SECRET=very-secret-value\n" in text and "LARK_RECEIVE_ID=oc_123\n" in text
    assert "# LARK_RECEIVE_ID_TYPE=\n" in text  # 源文件里注释掉的不复制
    assert "MAIL_MONITOR_LLM" not in text and "QUIET_HOURS" not in text

    again = runner.invoke(app, ["init"])
    assert again.exit_code == 0 and "已存在" in again.output
    assert target.read_text(encoding="utf-8") == text


def test_init_without_source(tmp_path):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0 and "notify-hub chats" in result.output
    assert (tmp_path / "hub" / ".env").exists()
    assert runner.invoke(app, ["init", "--from", str(tmp_path / "nope.env")]).exit_code == 0  # 已存在，先说这个


def test_fill_env_replaces_commented_lines_and_quotes():
    template = "A=1\n# KEY_B=\nKEY_C=old\n"
    out = fill_env(template, {"KEY_B": "has space", "KEY_C": "new", "KEY_D": "x'y"})
    assert out == "A=1\nKEY_B='has space'\nKEY_C=new\nKEY_D=\"x'y\"\n"


def test_chats_lists_groups(monkeypatch):
    monkeypatch.setenv("LARK_APP_ID", "cli_x")
    monkeypatch.setenv("LARK_APP_SECRET", "s")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_1", "name": "通知"}], "has_more": False}})

    real = cli.build_channel

    def fake_build(settings, **kwargs):
        return real(settings, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cli, "build_channel", fake_build)
    result = runner.invoke(app, ["chats"])
    assert result.exit_code == 0, result.output
    assert "群：通知  chat_id=oc_1" in result.output and "LARK_RECEIVE_ID" in result.output


def test_chats_without_credentials():
    result = runner.invoke(app, ["chats"])
    assert result.exit_code == 1 and "LARK_APP_ID" in result.output


def test_claude_hook_command(monkeypatch):
    _console(monkeypatch)
    payload = {
        "hook_event_name": "Notification",
        "cwd": "/w/notify-hub",
        "message": "Claude needs your permission to use Bash",
        "notification_type": "permission_prompt",
    }
    result = runner.invoke(app, ["claude-hook"], input=json.dumps(payload))
    assert result.exit_code == 0 and "🔵 notify-hub · Claude Code 等你确认" in result.output


def test_claude_hook_never_fails():
    assert runner.invoke(app, ["claude-hook"], input="not json").exit_code == 0
    assert runner.invoke(app, ["claude-hook"], input="").exit_code == 0
    stop = {"hook_event_name": "Stop", "last_assistant_message": "完成"}
    result = runner.invoke(app, ["claude-hook"], input=json.dumps(stop))  # 没配置 Lark：说一句，退出码还是 0
    assert result.exit_code == 0 and "LARK_APP_ID" in result.output


def test_claude_hook_does_not_wait_to_retry(monkeypatch):
    """hook 只试一次：连不上就算了，不让 Claude Code 等着重试。"""
    lark, slept = _flaky(monkeypatch, down=99)
    stop = {"hook_event_name": "Stop", "last_assistant_message": "完成"}
    result = runner.invoke(app, ["claude-hook"], input=json.dumps(stop))
    assert result.exit_code == 0 and "连不上 Lark" in result.output
    assert len(lark.titles) == 1 and slept == []
