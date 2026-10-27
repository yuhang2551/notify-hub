"""macOS 定时任务（launchd）：每 10 分钟运行一次 notify-hub flush。

flush 会补发失败的消息、免打扰结束后把攒下的合成一张卡、到点发每日汇总。
电脑睡着时不运行，醒来后 launchd 会补跑，所以不会漏。
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

LABEL = "com.notify-hub.flush"
INTERVAL = 600  # 秒

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


def plist(settings: Settings, *, interval: int = INTERVAL) -> dict[str, Any]:
    env = {"PYTHONUTF8": "1", "NOTIFY_HUB_HOME": str(settings.home)}
    if os.environ.get("NOTIFY_HUB_ENV"):  # 用 --env 指定过配置文件的，定时任务也用同一个
        env["NOTIFY_HUB_ENV"] = os.environ["NOTIFY_HUB_ENV"]
    log = str(log_path(settings))
    return {
        "Label": LABEL,
        "ProgramArguments": program_args(),
        "StartInterval": interval,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": env,
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(settings: Settings, *, directory: Path | None = None, run: Run | None = None) -> Path:
    """写 plist 并让 launchd 加载；装过的先卸下再装，改了间隔或路径也能重装。"""
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


def cron_line(settings: Settings) -> str:
    """不是 macOS 时用 cron：每 10 分钟一次。"""
    return f"*/10 * * * * {shlex.join(program_args())} >> {shlex.quote(str(log_path(settings)))} 2>&1"
