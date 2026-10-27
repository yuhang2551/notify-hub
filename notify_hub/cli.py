"""命令行入口：notify-hub send | test | chats | flush | digest | status | schedule | claude-hook | init | version"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from importlib import resources
from pathlib import Path

import typer
from dotenv import dotenv_values

from . import __version__, claude_hook, launchd, render
from .channels import ChannelError, LarkChannel, build_channel
from .config import LARK_KEYS, Settings, env_file_path, load_settings
from .hub import Hub
from .models import Level
from .timing import fmt_window

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="notify-hub：本机通知网关。各个程序调用同一个命令，按级别、去重、限流、失败重发的规则推到手机上的 Lark。",
)

STATUS_LABEL = {
    "sent": "已发",
    "pending": "等重发",
    "sending": "正在发",
    "held": "等免打扰结束",
    "digest": "等汇总",
    "bundled": "已合进卡片",
    "skipped": "重复没发",
    "failed": "放弃",
}


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


def _hub() -> Hub:
    return Hub(_settings())


@app.command()
def send(
    title: str = typer.Argument(..., help="标题，一行"),
    body: str = typer.Option("", "--body", "-b", help="正文；写 - 就从标准输入读"),
    level: str = typer.Option("normal", "--level", "-l", help="urgent（马上发，夜里也发）| normal（免打扰时段先存着）| digest（进每日汇总）"),
    source: str = typer.Option("default", "--source", "-s", help="哪个程序发的，比如 mail、timefence；用来分组和限流"),
    link: str | None = typer.Option(None, "--link", help="卡片上加一个「打开」按钮，只接受 http(s) 网址"),
    key: str | None = typer.Option(None, "--key", help="去重用：同一个 key 24 小时内只推一次"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="推送成功时不打印"),
) -> None:
    """推一条通知。发不出去不算出错：消息留在发件箱里，之后自动重发，退出码仍然是 0。"""
    if body == "-":
        body = sys.stdin.read()
    with _hub() as hub:
        try:
            result = hub.notify(title, body, level=level, source=source, link=link, key=key)
        except ValueError as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(2) from None
    if result.status == "sent":
        if not quiet:
            typer.echo(f"✅ 已推送（#{result.id}）")
    elif result.status == "queued":
        typer.echo(f"⏳ 没发出去，留在发件箱里，之后自动重发（#{result.id}）：{result.detail}", err=True)
    elif result.status == "held":
        typer.echo(f"🌙 {result.detail}（#{result.id}）")
    elif result.status == "digest":
        typer.echo(f"🗂  {result.detail}（#{result.id}）")
    else:
        typer.echo(f"↩️  {result.detail}（#{result.id}）")


@app.command()
def test(text: str = typer.Argument("", help="正文，不填用默认的一句")) -> None:
    """不经过发件箱，直接发一条测试消息，检查配置通不通。"""
    with _hub() as hub:
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


@app.command()
def flush(quiet: bool = typer.Option(False, "--quiet", "-q", help="没有事可做时不打印（定时任务用）")) -> None:
    """补上到时间该做的事：免打扰结束后把攒下的合成一张卡，到点发每日汇总，重发失败的，放弃重试太久的。
    适合放进定时任务（notify-hub schedule install）。"""
    with _hub() as hub:
        report = hub.flush()
    if quiet and report.empty():
        return
    parts = []
    if report.held:
        parts.append(f"免打扰期间的 {report.held} 条合成一张卡")
    if report.digest:
        parts.append(f"{report.digest} 条合成每日汇总")
    parts.append(f"发出 {report.sent} 条")
    if report.failed:
        parts.append(f"还没发出去 {report.failed} 条（{report.last_error}）")
    if report.gave_up:
        parts.append(f"放弃 {report.gave_up} 条")
    typer.echo((time.strftime("%m-%d %H:%M ") if quiet else "") + "，".join(parts))


@app.command()
def digest(preview: bool = typer.Option(False, "--preview", help="只在终端看看，不发也不改发件箱")) -> None:
    """现在就发每日汇总，不等到点。"""
    with _hub() as hub:
        if preview:
            msg = hub.preview("digest")
            typer.echo(render.text(msg) if msg else "没有等着汇总的消息")
            return
        result = hub.digest_now()
    if result is None:
        typer.echo("没有等着汇总的消息")
    elif result.status == "sent":
        typer.echo(f"✅ {result.detail}")
    else:
        typer.echo(f"⏳ 没发出去，留在发件箱里，之后自动重发（#{result.id}）：{result.detail}", err=True)


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)} 秒前"
    if seconds < 5400:
        return f"{int(seconds // 60)} 分钟前"
    return f"{seconds / 3600:.1f} 小时前"


@app.command()
def status() -> None:
    """看配置和发件箱：发了多少、有没有卡住的、最近的错误。"""
    with _hub() as hub:
        s = hub.settings
        typer.echo(f"配置：{env_file_path()}")
        if s.channel == "console":
            typer.echo("渠道：console（只在终端打印，不发出去）")
        else:
            missing = s.missing_lark()
            if missing:
                typer.echo(f"渠道：lark ⚠️ 还缺 {', '.join(missing)}")
            else:
                channel = build_channel(s)
                assert isinstance(channel, LarkChannel)
                typer.echo(f"渠道：lark（{s.lark_domain}，收件方 {channel.receive_id_type} {s.lark_receive_id[:8]}…）")
                channel.close()
        info = hub.status()
        counts = info["counts"]
        window = s.quiet_window
        if window:
            typer.echo(f"免打扰：{fmt_window(window)}{'（现在是免打扰时段）' if info['quiet_now'] else ''}")
        else:
            typer.echo("免打扰：关")
        at = s.digest_at
        when = f"每天 {at:%H:%M}" if at else "不自动发（notify-hub digest 手动发）"
        typer.echo(f"每日汇总：{when}，等着汇总的 {counts.get('digest', 0)} 条")
        typer.echo(f"发件箱：{s.db_path}")
        if counts:
            typer.echo("  " + " · ".join(f"{STATUS_LABEL.get(k, k)} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
        else:
            typer.echo("  还是空的")
        oldest = info["oldest_waiting"]
        if oldest is not None:
            typer.echo(f"最早一条没发出去的：#{oldest['id']}「{oldest['title']}」，{_ago(time.time() - oldest['created_at'])}")
        if info["problems"]:
            typer.echo("最近的问题：")
            for row in info["problems"]:
                typer.echo(f"  #{row['id']}「{row['title']}」：{row['last_error']}")


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


@app.command()
def schedule(action: str = typer.Argument("status", help="install（装上）| uninstall（卸掉）| status（看状态）")) -> None:
    """定时任务：每 10 分钟跑一次 flush（补发、免打扰结束后合并、到点发汇总）。macOS 用 launchd，装在你自己的用户下。"""
    if action not in ("install", "uninstall", "status"):
        typer.echo(f"❌ 只能是 install、uninstall 或 status，不是 {action!r}", err=True)
        raise typer.Exit(2)
    settings = _settings()
    if sys.platform != "darwin":
        typer.echo("launchd 只有 macOS 有。其他系统用 crontab -e 加上这一行：")
        typer.echo(launchd.cron_line(settings))
        return
    if action == "install":
        try:
            path = launchd.install(settings)
        except (RuntimeError, OSError) as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"✅ 装好了：每 {launchd.INTERVAL // 60} 分钟跑一次 notify-hub flush（{path}）")
        typer.echo(f"   日志：{launchd.log_path(settings)}（只记有事发生的时候）")
        return
    if action == "uninstall":
        existed = launchd.uninstall()
        typer.echo("✅ 卸掉了定时任务，配置和发件箱都还在" if existed else "本来就没装")
        return
    path = launchd.plist_path()
    if not path.exists():
        typer.echo("⏹  还没装。要装就运行 notify-hub schedule install")
        return
    state = "launchd 已加载" if launchd.loaded() else "⚠️ launchd 没加载，再运行一次 notify-hub schedule install"
    typer.echo(f"✅ 已装：{path}（{state}）")
    log = launchd.log_path(settings)
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        typer.echo(f"—— {log} 最后 {len(lines)} 行 ——")
        for line in lines:
            typer.echo(line)


@app.command("claude-hook")
def claude_hook_command() -> None:
    """给 Claude Code 的 hooks 用：从标准输入读 hook 的 JSON，推一条通知。退出码永远是 0，不会打断 Claude Code。"""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        notice = claude_hook.from_hook(data) if isinstance(data, dict) else None
        if notice is None:
            return
        with Hub(load_settings()) as hub:
            hub.notify(notice.title, notice.body, source=claude_hook.SOURCE)
    except Exception as exc:  # noqa: BLE001 —— hook 出错只记一句，不影响 Claude Code
        typer.echo(f"notify-hub claude-hook：{exc}", err=True)


@app.command()
def version() -> None:
    typer.echo(f"notify-hub {__version__}")


__all__ = ["app", "fill_env", "Level"]
