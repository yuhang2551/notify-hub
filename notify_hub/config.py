"""配置：~/.notify-hub/.env 加环境变量。优先级：传进来的 overrides > 环境变量 > .env 文件 > 默认值。"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from datetime import time
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .timing import Window, parse_daily, parse_window

DEFAULT_HOME = Path.home() / ".notify-hub"

ENV_MAP = {
    "NOTIFY_HUB_HOME": "home",
    "NOTIFY_HUB_CHANNEL": "channel",
    "LARK_DOMAIN": "lark_domain",
    "LARK_APP_ID": "lark_app_id",
    "LARK_APP_SECRET": "lark_app_secret",
    "LARK_RECEIVE_ID": "lark_receive_id",
    "LARK_RECEIVE_ID_TYPE": "lark_receive_id_type",
    "NOTIFY_HUB_RATE_LIMIT": "rate_limit",
    "NOTIFY_HUB_DEDUP_MINUTES": "dedup_minutes",
    "NOTIFY_HUB_KEY_HOURS": "key_hours",
    "NOTIFY_HUB_GIVE_UP_HOURS": "give_up_hours",
    "NOTIFY_HUB_QUIET_HOURS": "quiet_hours",
    "NOTIFY_HUB_DIGEST_TIME": "digest_time",
}

# init --from 时从别的 .env（比如邮件监控的）复制过来的项
LARK_KEYS = ["LARK_DOMAIN", "LARK_APP_ID", "LARK_APP_SECRET", "LARK_RECEIVE_ID", "LARK_RECEIVE_ID_TYPE"]

CHANNELS = ("lark", "console")


@dataclass
class Settings:
    home: Path = DEFAULT_HOME
    channel: str = "lark"  # lark | console（console 只在终端打印，不发出去）
    lark_domain: str = "https://open.larksuite.com"  # 飞书国内版是 https://open.feishu.cn
    lark_app_id: str | None = None
    lark_app_secret: str | None = None
    lark_receive_id: str | None = None
    lark_receive_id_type: str | None = None  # 不填就按 id 前缀判断（oc_ 群、ou_ 个人）
    rate_limit: int = 20  # 同一来源一小时最多推几条，超出的进汇总
    dedup_minutes: int = 10  # 没给 key 时，同样的内容多少分钟内只推一次
    key_hours: int = 24  # 给了 key 时，同一个 key 多少小时内只推一次
    give_up_hours: int = 24  # 发不出去的消息重试多少小时后放弃
    quiet_hours: str = "23:00-08:00"  # 免打扰时段：normal 先存着，结束后合成一张卡发；off 关掉
    digest_time: str = "18:00"  # 每天几点发汇总；off 不自动发（还可以手动 notify-hub digest）

    @property
    def db_path(self) -> Path:
        return self.home / "outbox.db"

    @property
    def env_path(self) -> Path:
        return self.home / ".env"

    @property
    def quiet_window(self) -> Window | None:
        return parse_window(self.quiet_hours)

    @property
    def digest_at(self) -> time | None:
        return parse_daily(self.digest_time)

    def missing_lark(self, *, need_receiver: bool = True) -> list[str]:
        names = ["LARK_APP_ID", "LARK_APP_SECRET"] + (["LARK_RECEIVE_ID"] if need_receiver else [])
        return [name for name in names if not getattr(self, ENV_MAP[name])]


def env_file_path() -> Path:
    if os.environ.get("NOTIFY_HUB_ENV"):
        return Path(os.environ["NOTIFY_HUB_ENV"]).expanduser()
    home = Path(os.environ.get("NOTIFY_HUB_HOME", DEFAULT_HOME)).expanduser()
    return home / ".env"


_INT_FIELDS = {"rate_limit", "dedup_minutes", "key_hours", "give_up_hours"}


def _coerce(field: str, raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None
    if field == "home":
        return Path(value).expanduser()
    if field == "channel":
        if value not in CHANNELS:
            raise ValueError(f"只能是 {' 或 '.join(CHANNELS)}")
        return value
    if field == "quiet_hours":
        return "off" if parse_window(value) is None else value
    if field == "digest_time":
        return "off" if parse_daily(value) is None else value
    if field in _INT_FIELDS:
        try:
            number = int(value)
        except ValueError:
            raise ValueError("要写整数") from None
        if number < 1:
            raise ValueError("要大于 0")
        return number
    return value


def load_settings(env_file: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    merged: dict[str, str] = {}
    path = env_file or env_file_path()
    if path.exists():
        merged.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    merged.update({k: v for k, v in os.environ.items() if k in ENV_MAP})

    values: dict[str, Any] = {}
    for env_name, field in ENV_MAP.items():
        if env_name in merged:
            try:
                coerced = _coerce(field, merged[env_name])
            except ValueError as exc:
                raise ValueError(f"配置 {env_name} 有问题：{exc}") from exc
            if coerced is not None:
                values[field] = coerced
    if overrides:
        known = {f.name for f in fields(Settings)}
        values.update({k: v for k, v in overrides.items() if k in known and v is not None})
    return Settings(**values)
