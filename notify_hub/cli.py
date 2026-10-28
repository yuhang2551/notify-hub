"""命令行入口：notify-hub send | test | chats | init | claude-hook | version"""
from __future__ import annotations

import json
import os
import re
import sys
from importlib import resources
from pathlib import Path

import typer
from dotenv import dotenv_values

from . import __version__, claude_hook
from .channels import ChannelError, LarkChannel, build_channel
from .config import LARK_KEYS, Settings, env_file_path, load_settings
from .hub import Hub

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="notify-hub：把通知推到手机上的 Lark。调用一次发一次，连不上就当场重试几次，还发不出去就报错退出；什么时候发、发不出去怎么办，由调用它的程序决定。",
)


@app.callback()
def main(env: Path | None = typer.Option(None, "--env", help="配置文件，默认 ~/.notify-hub/.env")) -> None:
    if env:
        os.environ["NOTIFY_HUB_ENV"] = str(env.expanduser())


def _settings() -> Settings:
    try:
        return load_settings()
    except ValueError as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def send(
    title: str = typer.Argument(..., help="标题，一行"),
    body: str = typer.Option("", "--body", "-b", help="正文；写 - 就从标准输入读"),
    level: str = typer.Option("normal", "--level", "-l", help="urgent（红色卡片）| normal（蓝色卡片）；两种都是马上发"),
    source: str = typer.Option("default", "--source", "-s", help="哪个程序发的，比如 mail、timefence，写在卡片底部"),
    link: str | None = typer.Option(None, "--link", help="卡片上加一个「打开」按钮，只接受 http(s) 网址"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="推送成功时不打印"),
    key: str | None = typer.Option(None, "--key", hidden=True),  # 0.2 版去重用的；0.3 不去重，留着只是让旧的调用不报错
) -> None:
    """马上推一条通知。连不上 Lark 或 Lark 一时出错，隔 2 秒、5 秒各重试一次。
    退出码：0 发出去了；1 没发出去（配置不对、连不上、Lark 拒收）；2 参数写错了。"""
    if body == "-":
        body = sys.stdin.read()
    with Hub(_settings()) as hub:
        try:
            attempts = hub.send(title, body, level=level, source=source, link=link)
        except ValueError as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(2) from None
        except ChannelError as exc:
            typer.echo(f"❌ 没发出去：{exc}", err=True)
            raise typer.Exit(1) from None
    if not quiet:
        typer.echo("✅ 已推送" + (f"（试了 {attempts} 次）" if attempts > 1 else ""))


@app.command()
def test(text: str = typer.Argument("", help="正文，不填用默认的一句")) -> None:
    """发一条测试消息，检查配置通不通。"""
    with Hub(_settings()) as hub:
        try:
            hub.send_test(text)
        except ChannelError as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"✅ 已通过 {hub.settings.channel} 发出测试消息")


@app.command()
def chats() -> None:
    """列出 Lark 机器人所在的群，拿到 chat_id 填进 LARK_RECEIVE_ID。"""
    settings = _settings()
    if settings.channel != "lark":
        settings.channel = "lark"
    try:
        channel = build_channel(settings, need_receiver=False)
        assert isinstance(channel, LarkChannel)
        try:
            found = channel.list_chats()
        finally:
            channel.close()
    except ChannelError as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(1) from None
    if not found:
        typer.echo("机器人还没有加入任何群。在 Lark 里建一个群，把这个应用的机器人加进去，再运行一次。")
        return
    for chat in found:
        typer.echo(f"群：{chat['name'] or '（未命名）'}  chat_id={chat['chat_id']}")
    typer.echo(f"\n把要推送的群的 chat_id 写进 {env_file_path()} 的 LARK_RECEIVE_ID（oc_ 开头会自动按群发）。")


def _env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_\-.:/@+=]*", value):
        return value
    if "'" not in value:
        return f"'{value}'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fill_env(template: str, values: dict[str, str]) -> str:
    """把 values 填进模板：有对应的行（包括注释掉的）就替换，没有就追加在末尾。"""
    lines = template.splitlines()
    for key, value in values.items():
        pattern = re.compile(rf"^#?\s*{re.escape(key)}=")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={_env_value(value)}"
                break
        else:
            lines.append(f"{key}={_env_value(value)}")
    return "\n".join(lines) + "\n"


@app.command()
def init(
    from_env: Path | None = typer.Option(None, "--from", help="从这个 .env 复制 Lark 的几项，比如 ~/.mail-monitor/.env"),
) -> None:
    """生成 ~/.notify-hub/.env。已经有了就不动。"""
    target = env_file_path()
    if target.exists():
        typer.echo(f"⏭  已存在，没动：{target}（要重新生成就先删掉它）")
        return
    template = resources.files("notify_hub").joinpath("env.example").read_text(encoding="utf-8")
    copied: dict[str, str] = {}
    if from_env is not None:
        source = from_env.expanduser()
        if not source.exists():
            typer.echo(f"❌ 找不到 {source}", err=True)
            raise typer.Exit(1)
        found = dotenv_values(source)
        copied = {k: found[k].strip() for k in LARK_KEYS if found.get(k) and found[k].strip()}
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(fill_env(template, copied))
    typer.echo(f"✅ 生成 {target}（只有你能读）")
    if copied:
        typer.echo(f"从 {from_env} 复制了：{'、'.join(copied)}")
        typer.echo("下一步：notify-hub test")
    else:
        typer.echo("下一步：填上 LARK_APP_ID、LARK_APP_SECRET，用 notify-hub chats 查群 id 填进 LARK_RECEIVE_ID，再运行 notify-hub test")


@app.command("claude-hook")
def claude_hook_command() -> None:
    """给 Claude Code 的 hooks 用：从标准输入读 hook 的 JSON，推一条通知。
    只试一次、不重试，退出码永远是 0，不会拖慢或打断 Claude Code。"""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        notice = claude_hook.from_hook(data) if isinstance(data, dict) else None
        if notice is None:
            return
        with Hub(load_settings(), retry_delays=()) as hub:
            hub.send(notice.title, notice.body, source=claude_hook.SOURCE)
    except Exception as exc:  # noqa: BLE001 —— hook 出错只记一句，不影响 Claude Code
        typer.echo(f"notify-hub claude-hook：{exc}", err=True)


@app.command()
def version() -> None:
    typer.echo(f"notify-hub {__version__}")


__all__ = ["app", "fill_env"]
