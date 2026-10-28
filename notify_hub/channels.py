"""推送渠道：Lark 应用机器人，和只在终端打印的 console。"""
from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from . import render
from .config import Settings
from .models import Message


class ChannelError(RuntimeError):
    """发送失败。network=True 表示连不上或 Lark 一时出错（5xx、429），隔几秒重试可能就好；其他错误（配置不对、没权限、收件方不对）重试也没用。"""

    def __init__(self, message: str, *, network: bool = False):
        super().__init__(message)
        self.network = network


class Channel(Protocol):
    name: str

    def send(self, msg: Message) -> None: ...

    def close(self) -> None: ...


class ConsoleChannel:
    name = "console"

    def __init__(self) -> None:
        self.sent: list[Message] = []

    def send(self, msg: Message) -> None:
        self.sent.append(msg)
        print("─" * 40)
        print(render.text(msg))

    def close(self) -> None:
        pass


def infer_receive_id_type(receive_id: str | None) -> str:
    """没写 LARK_RECEIVE_ID_TYPE 时按 id 的样子判断：oc_ 是群，ou_ 是个人 open_id，on_ 是 union_id，带 @ 的是邮箱。"""
    rid = (receive_id or "").strip()
    if rid.startswith("oc_"):
        return "chat_id"
    if rid.startswith("on_"):
        return "union_id"
    if "@" in rid:
        return "email"
    return "open_id"


class LarkChannel:
    """Lark / 飞书应用机器人：用 app_id + app_secret 换 tenant_access_token，再以机器人身份发卡片消息。"""

    name = "lark"

    def __init__(
        self,
        *,
        domain: str,
        app_id: str,
        app_secret: str,
        receive_id: str = "",
        receive_id_type: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type or infer_receive_id_type(receive_id)
        self._client = httpx.Client(base_url=domain.rstrip("/"), timeout=timeout, transport=transport)
        self._token: str | None = None

    def _request(self, method: str, path: str, what: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ChannelError(f"{what}：连不上 Lark（{exc.__class__.__name__}）", network=True) from exc
        if response.status_code >= 500 or response.status_code == 429:
            # Lark 自己出问题或者嫌我们发太快：算暂时性的，hub 会隔几秒再试
            raise ChannelError(f"{what}：Lark 返回 HTTP {response.status_code}", network=True)
        try:
            data = response.json()
        except ValueError:
            raise ChannelError(f"{what}：返回的不是 JSON（HTTP {response.status_code}）：{response.text[:200]}") from None
        code = data.get("code", 0)
        if response.status_code != 200 or code != 0:
            raise ChannelError(f"{what}失败：HTTP {response.status_code} code={code} {data.get('msg', '')}".rstrip())
        return data

    def _tenant_token(self) -> str:
        if not self._token:
            data = self._request(
                "POST", "/open-apis/auth/v3/tenant_access_token/internal", "获取 tenant_access_token",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            self._token = data.get("tenant_access_token")
            if not self._token:
                raise ChannelError("tenant_access_token 为空")
        return self._token

    def send(self, msg: Message) -> None:
        if not self.receive_id:
            raise ChannelError("没有设置 LARK_RECEIVE_ID（用 notify-hub chats 查群 id）")
        token = self._tenant_token()
        payload = {
            "receive_id": self.receive_id,
            "msg_type": "interactive",
            "content": json.dumps(render.card(msg), ensure_ascii=False),
        }
        self._request(
            "POST", "/open-apis/im/v1/messages", "发送消息",
            params={"receive_id_type": self.receive_id_type},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            # 自己编码成 UTF-8：中文不转成 \uXXXX，卡片才不会超过 Lark 30 KB 的上限
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )

    def list_chats(self) -> list[dict[str, str]]:
        """机器人所在的群（需要权限 im:chat:readonly）。"""
        token = self._tenant_token()
        chats: list[dict[str, str]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET", "/open-apis/im/v1/chats", "获取群列表",
                params=params, headers={"Authorization": f"Bearer {token}"},
            ).get("data", {})
            chats.extend({"chat_id": item.get("chat_id", ""), "name": item.get("name", "")} for item in data.get("items", []))
            page_token = data.get("page_token") if data.get("has_more") else None
            if not page_token:
                return chats

    def close(self) -> None:
        self._client.close()


def build_channel(settings: Settings, *, need_receiver: bool = True, transport: httpx.BaseTransport | None = None) -> Channel:
    if settings.channel == "console":
        return ConsoleChannel()
    missing = settings.missing_lark(need_receiver=need_receiver)
    if missing:
        raise ChannelError(f"{settings.env_path} 里还缺：{', '.join(missing)}")
    return LarkChannel(
        domain=settings.lark_domain,
        app_id=settings.lark_app_id or "",
        app_secret=settings.lark_app_secret or "",
        receive_id=settings.lark_receive_id or "",
        receive_id_type=settings.lark_receive_id_type,
        transport=transport,
    )
