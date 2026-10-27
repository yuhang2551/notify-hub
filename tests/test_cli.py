import os
import stat

import httpx
from typer.testing import CliRunner

from notify_hub import cli
from notify_hub.cli import app, fill_env

runner = CliRunner()


def _console(monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_CHANNEL", "console")


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
    assert flush.exit_code == 0 and "补发 0 条" in flush.output  # 还没到重试时间


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
