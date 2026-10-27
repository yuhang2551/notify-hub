import json
import os
import plistlib
import stat
import subprocess
import sys
import time

import httpx
import pytest
from typer.testing import CliRunner

from notify_hub import cli, launchd
from notify_hub.cli import app, fill_env

runner = CliRunner()


@pytest.fixture(autouse=True)
def real_clock_is_not_quiet(monkeypatch):
    """命令行用的是真时间：关掉免打扰和定时汇总，测试在夜里跑结果也一样。要测它们的自己再打开。"""
    monkeypatch.setenv("NOTIFY_HUB_QUIET_HOURS", "off")
    monkeypatch.setenv("NOTIFY_HUB_DIGEST_TIME", "off")


def _console(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_CHANNEL", "console")


def _window_around_now() -> str:
    hour = time.localtime().tm_hour
    return f"{(hour - 1) % 24:02d}:00-{(hour + 1) % 24:02d}:00"


def test_send_prints_and_records(monkeypatch):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "TimeFence 跑完了", "--body", "IC 0.031", "--source", "timefence"])
    assert result.exit_code == 0, result.output
    assert "TimeFence 跑完了" in result.output and "✅ 已推送（#1）" in result.output
    again = runner.invoke(app, ["send", "TimeFence 跑完了", "--body", "IC 0.031", "--source", "timefence"])
    assert again.exit_code == 0 and "重复" in again.output


def test_send_reads_body_from_stdin(monkeypatch):
    _console(monkeypatch)
    result = runner.invoke(app, ["send", "备份失败", "--body", "-", "--level", "urgent"], input="磁盘满了\n")
    assert result.exit_code == 0
    assert "🔴 备份失败" in result.output and "磁盘满了" in result.output


def test_quiet_and_digest(monkeypatch):
    _console(monkeypatch)
    quiet = runner.invoke(app, ["send", "安静", "-q"])
    assert quiet.exit_code == 0 and "安静" in quiet.output and "已推送" not in quiet.output
    digest = runner.invoke(app, ["send", "订阅 12 封", "--level", "digest"])
    assert digest.exit_code == 0 and "进汇总" in digest.output


def test_bad_arguments_exit_2(monkeypatch):
    _console(monkeypatch)
    assert runner.invoke(app, ["send", "x", "--level", "loud"]).exit_code == 2
    result = runner.invoke(app, ["send", "x", "--link", "javascript:alert(1)"])
    assert result.exit_code == 2 and "http" in result.output


def test_send_without_config_is_queued_not_an_error():
    result = runner.invoke(app, ["send", "还没配好"])
    assert result.exit_code == 0
    assert "留在发件箱" in result.output and "LARK_APP_ID" in result.output


def test_test_command(monkeypatch):
    failed = runner.invoke(app, ["test"])
    assert failed.exit_code == 1 and "LARK_APP_ID" in failed.output
    _console(monkeypatch)
    ok = runner.invoke(app, ["test", "你好"])
    assert ok.exit_code == 0 and "你好" in ok.output and "已通过 console" in ok.output


def test_status_and_flush(monkeypatch):
    runner.invoke(app, ["send", "发不出去的"])  # 没配置：留在发件箱
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "还缺 LARK_APP_ID" in status.output and "等重发 1" in status.output and "发不出去的" in status.output
    _console(monkeypatch)
    status = runner.invoke(app, ["status"])
    assert "console" in status.output
    flush = runner.invoke(app, ["flush"])
    assert flush.exit_code == 0 and "发出 0 条" in flush.output  # 还没到重试时间


def test_bad_config_is_explained(tmp_path, monkeypatch):
    env = tmp_path / "bad.env"
    env.write_text("NOTIFY_HUB_RATE_LIMIT=many\n", encoding="utf-8")
    result = runner.invoke(app, ["--env", str(env), "send", "x"])
    assert result.exit_code == 1 and "NOTIFY_HUB_RATE_LIMIT" in result.output


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
    assert "MAIL_MONITOR_LLM" not in text

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


def test_send_in_quiet_hours_waits(monkeypatch):
    _console(monkeypatch)
    monkeypatch.setenv("NOTIFY_HUB_QUIET_HOURS", _window_around_now())
    result = runner.invoke(app, ["send", "夜里的"])
    assert result.exit_code == 0 and result.output.startswith("🌙 免打扰时段")
    assert runner.invoke(app, ["send", "急事", "--level", "urgent"]).output.startswith("────")
    status = runner.invoke(app, ["status"]).output
    assert "（现在是免打扰时段）" in status and "等免打扰结束 1" in status


def test_digest_command(monkeypatch):
    _console(monkeypatch)
    assert "没有等着汇总" in runner.invoke(app, ["digest"]).output
    runner.invoke(app, ["send", "订阅 12 封", "--level", "digest", "--source", "mail"])
    preview = runner.invoke(app, ["digest", "--preview"])
    assert "⚪ 每日汇总 · 1 条" in preview.output and "订阅 12 封" in preview.output and "已推送" not in preview.output
    sent = runner.invoke(app, ["digest"])
    assert sent.exit_code == 0 and "⚪ 每日汇总 · 1 条" in sent.output and "✅ 1 条合成一张汇总卡片" in sent.output
    assert "没有等着汇总" in runner.invoke(app, ["digest"]).output
    assert "每日汇总：不自动发" in runner.invoke(app, ["status"]).output


def test_flush_quiet_prints_only_when_something_happened(monkeypatch):
    _console(monkeypatch)
    assert runner.invoke(app, ["flush", "-q"]).output == ""


def test_schedule_on_other_systems_prints_cron_lines(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    result = runner.invoke(app, ["schedule", "install"])
    assert result.exit_code == 0 and "0 8,12,18 * * *" in result.output and "flush --quiet" in result.output
    assert "每天 08:00、12:00、18:00" in result.output


def test_schedule_on_a_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(launchd.time, "sleep", lambda seconds: None)
    calls = []

    def fake_launchctl(args, **kwargs):
        calls.append(args[1])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(launchd.subprocess, "run", fake_launchctl)
    assert "还没装" in runner.invoke(app, ["schedule"]).output
    installed = runner.invoke(app, ["schedule", "install"])
    assert installed.exit_code == 0 and "每天 08:00、12:00、18:00 运行" in installed.output, installed.output
    assert "⚠️" not in installed.output
    plist = tmp_path / "Library" / "LaunchAgents" / "com.notify-hub.flush.plist"
    assert plist.exists()
    status = runner.invoke(app, ["schedule", "status"]).output
    assert "已装：每天 08:00、12:00、18:00（launchd 已加载）" in status and "不一样" not in status
    assert "卸掉了" in runner.invoke(app, ["schedule", "uninstall"]).output
    assert calls == ["bootout", "bootstrap", "print", "bootout"]
    assert runner.invoke(app, ["schedule", "restart"]).exit_code == 2


def test_schedule_status_spots_an_old_install(monkeypatch, tmp_path):
    """0.2.0 装的是每 10 分钟一次：升级后看状态会提示重装。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(launchd.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    plist = launchd.plist_path()
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({"Label": launchd.LABEL, "StartInterval": 600}))
    status = runner.invoke(app, ["schedule"]).output
    assert "已装：每 10 分钟" in status and "现在的配置是每天 08:00、12:00、18:00" in status
    assert "再运行一次 notify-hub schedule install" in status


def test_schedule_install_warns_when_the_digest_would_be_late(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NOTIFY_HUB_DIGEST_TIME", "21:00")
    monkeypatch.setattr(launchd.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    installed = runner.invoke(app, ["schedule", "install"])
    assert installed.exit_code == 0 and "每日汇总是 21:00" in installed.output and "NOTIFY_HUB_SCHEDULE_TIMES" in installed.output


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
    assert runner.invoke(app, ["claude-hook"], input=json.dumps(stop)).exit_code == 0  # 没配置 Lark：留在发件箱，也是 0
