"""配置：~/.notify-hub/.env 加环境变量。优先级：传进来的 overrides > 环境变量 > .env 文件 > 默认值。"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

DEFAULT_HOME = Path.home() / ".notify-hub"

# 只读这几项。0.2 版的免打扰、汇总、定时任务、去重、限流那些配置项不再读，旧的 .env 里留着也没关系
ENV_MAP = {
    "NOTIFY_HUB_HOME": "home",
    "NOTIFY_HUB_CHANNEL": "channel",
    "LARK_DOMAIN": "lark_domain",
    "LARK_APP_ID": "lark_app_id",
    "LARK_APP_SECRET": "lark_app_secret",
    "LARK_RECEIVE_ID": "lark_receive_id",
    "LARK_RECEIVE_ID_TYPE": "lark_receive_id_type",
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

    @property
    def env_path(self) -> Path:
        return self.home / ".env"

    def missing_lark(self, *, need_receiver: bool = True) -> list[str]:
        names = ["LARK_APP_ID", "LARK_APP_SECRET"] + (["LARK_RECEIVE_ID"] if need_receiver else [])
        return [name for name in names if not getattr(self, ENV_MAP[name])]


def env_file_path() -> Path:
    if os.environ.get("NOTIFY_HUB_ENV"):
        return Path(os.environ["NOTIFY_HUB_ENV"]).expanduser()
    home = Path(os.environ.get("NOTIFY_HUB_HOME", DEFAULT_HOME)).expanduser()
    return home / ".env"


def _coerce(field: str, raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return None
    if field == "home":
        return Path(value).expanduser()
    if field == "channel" and value not in CHANNELS:
        raise ValueError(f"只能是 {' 或 '.join(CHANNELS)}")
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
