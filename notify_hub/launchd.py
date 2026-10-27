"""macOS 定时任务（launchd）：每天在固定的几个时间运行 notify-hub flush，默认 08:00、12:00、18:00。

08:00 免打扰结束，把夜里攒下的合成一张卡发出去；18:00 发每日汇总；中午那次补发之前没发出去的。
平常的通知来了就发，不等定时任务；定时任务只是兜底，任何一次推送成功后也会顺手做这些。
电脑睡着错过了，醒来后 launchd 补跑一次（错过几次也只补一次）；关机错过了，开机登录后补跑。
"""
from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .timing import fmt_times

LABEL = "com.notify-hub.flush"

Run = Callable[..., subprocess.CompletedProcess]


def program_args() -> list[str]:
    """用当前这个 Python 跑，uv tool 装的就是它自己的环境，不依赖 PATH。"""
    return [sys.executable, "-m", "notify_hub", "flush", "--quiet"]


def log_path(settings: Settings) -> Path:
    return settings.home / "logs" / "flush.log"


def agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(directory: Path | None = None) -> Path:
    return (directory or agents_dir()) / f"{LABEL}.plist"


def describe(settings: Settings) -> str:
    return f"每天 {fmt_times(settings.schedule_at)}"


def plist(settings: Settings) -> dict[str, Any]:
    env = {"PYTHONUTF8": "1", "NOTIFY_HUB_HOME": str(settings.home)}
    if os.environ.get("NOTIFY_HUB_ENV"):  # 用 --env 指定过配置文件的，定时任务也用同一个
        env["NOTIFY_HUB_ENV"] = os.environ["NOTIFY_HUB_ENV"]
    log = str(log_path(settings))
    return {
        "Label": LABEL,
        "ProgramArguments": program_args(),
        "StartCalendarInterval": [{"Hour": t.hour, "Minute": t.minute} for t in settings.schedule_at],
        "RunAtLoad": True,  # 装上和开机登录时各跑一次，补上关机时错过的
        "ProcessType": "Background",
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": env,
    }


def installed(directory: Path | None = None) -> str | None:
    """装好的 plist 里写的是什么时间，写法和 describe 一样，方便比较；没装返回 None。"""
    path = plist_path(directory)
    if not path.exists():
        return None
    data = plistlib.loads(path.read_bytes())
    entries = data.get("StartCalendarInterval")
    if isinstance(entries, dict):
        entries = [entries]
    if entries:
        return "每天 " + "、".join(f"{e.get('Hour', 0):02d}:{e.get('Minute', 0):02d}" for e in entries)
    if data.get("StartInterval"):  # 0.2.0 装的是每 10 分钟一次
        return f"每 {data['StartInterval'] // 60} 分钟"
    return "没写时间"


def late_cards(settings: Settings) -> list[str]:
    """免打扰结束、每日汇总这两个时刻定时任务不跑的话，对应的卡片会晚到下一次运行。"""
    times = settings.schedule_at
    notes = []
    window = settings.quiet_window
    if window and window[1] not in times:
        notes.append(f"免打扰 {window[1]:%H:%M} 结束，定时任务那时不跑，夜里攒的卡片会晚到下一次运行")
    if settings.digest_at and settings.digest_at not in times:
        notes.append(f"每日汇总是 {settings.digest_at:%H:%M}，定时任务那时不跑，汇总会晚到下一次运行")
    return notes


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(settings: Settings, *, directory: Path | None = None, run: Run | None = None) -> Path:
    """写 plist 并让 launchd 加载；装过的先卸下再装，改了时间或路径也能重装。"""
    run = run or subprocess.run
    path = plist_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path(settings).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(plistlib.dumps(plist(settings)))
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    errors = []
    for attempt in range(2):  # 刚卸下时立刻加载偶尔会失败，等一下再试一次
        result = run(["launchctl", "bootstrap", _domain(), str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            return path
        errors.append((result.stderr or result.stdout or "").strip())
        if attempt == 0:
            time.sleep(1)
    legacy = run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
    if legacy.returncode == 0:
        return path
    raise RuntimeError(f"launchctl 加载失败：{errors[-1] or legacy.stderr.strip()}")


def uninstall(*, directory: Path | None = None, run: Run | None = None) -> bool:
    """卸下并删掉 plist。返回之前有没有装过。"""
    run = run or subprocess.run
    path = plist_path(directory)
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def loaded(*, run: Run | None = None) -> bool:
    result = (run or subprocess.run)(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    return result.returncode == 0


def cron_lines(settings: Settings) -> list[str]:
    """不是 macOS 时用 cron，时间一样，分钟相同的写成一行。cron 不补跑关机时错过的。"""
    command = f"{shlex.join(program_args())} >> {shlex.quote(str(log_path(settings)))} 2>&1"
    hours: dict[int, list[int]] = {}
    for t in settings.schedule_at:
        hours.setdefault(t.minute, []).append(t.hour)
    return [f"{minute} {','.join(map(str, hs))} * * * {command}" for minute, hs in sorted(hours.items())]
