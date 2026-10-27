import json

import httpx
import pytest

from notify_hub.channels import ChannelError, ConsoleChannel, LarkChannel, build_channel, infer_receive_id_type
from notify_hub.config import Settings
from notify_hub.models import make_message

TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"


def _token_ok():
    return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})


def _channel(handler, **kwargs) -> LarkChannel:
    params = {"domain": "https://open.larksuite.com", "app_id": "cli_x", "app_secret": "s", "receive_id": "oc_group"}
    params.update(kwargs)
    return LarkChannel(transport=httpx.MockTransport(handler), **params)


@pytest.mark.parametrize(
    ("receive_id", "expected"),
    [("oc_example", "chat_id"), ("ou_example", "open_id"), ("on_example", "union_id"), ("me@example.com", "email"), ("", "open_id"), (None, "open_id")],
)
def test_infer_receive_id_type(receive_id, expected):
    assert infer_receive_id_type(receive_id) == expected


def test_sends_an_interactive_card_to_the_chat():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == TOKEN_PATH:
            assert json.loads(request.content) == {"app_id": "cli_x", "app_secret": "s"}
            return _token_ok()
        assert request.url.path == "/open-apis/im/v1/messages"
        assert request.url.params["receive_id_type"] == "chat_id"  # oc_ 开头，自动按群发
        assert request.headers["Authorization"] == "Bearer t-1"
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_1"}})

    channel = _channel(handler)
    channel.send(make_message("实验跑完了", "IC 0.031", level="urgent", link="https://example.com/r/1"))
    channel.send(make_message("第二条"))
    channel.close()

    paths = [r.url.path for r in seen]
    assert paths.count(TOKEN_PATH) == 1  # 一个进程里 token 只拿一次
    body = json.loads(seen[1].content)
    assert body["receive_id"] == "oc_group" and body["msg_type"] == "interactive"
    card = json.loads(body["content"])
    assert card["header"]["template"] == "red" and card["header"]["title"]["content"] == "实验跑完了"


def test_explicit_receive_id_type_wins():
    channel = _channel(lambda r: _token_ok(), receive_id="oc_group", receive_id_type="open_id")
    assert channel.receive_id_type == "open_id"
    channel.close()


def test_lark_error_code_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return _token_ok()
        return httpx.Response(400, json={"code": 230001, "msg": "invalid receive_id"})

    with pytest.raises(ChannelError, match="230001") as info:
        _channel(handler).send(make_message("x"))
    assert info.value.network is False


@pytest.mark.parametrize(
    "response",
    [
        lambda request: httpx.Response(502, text="bad gateway"),
        lambda request: httpx.Response(429, json={"code": 99991400, "msg": "too many requests"}),
    ],
)
def test_server_trouble_counts_as_network(response):
    with pytest.raises(ChannelError) as info:
        _channel(response).send(make_message("x"))
    assert info.value.network is True


def test_connection_error_counts_as_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(ChannelError, match="连不上 Lark") as info:
        _channel(handler).send(make_message("x"))
    assert info.value.network is True


def test_bad_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10003, "msg": "invalid app_secret"})

    with pytest.raises(ChannelError, match="tenant_access_token"):
        _channel(handler).send(make_message("x"))


def test_needs_a_receiver():
    with pytest.raises(ChannelError, match="LARK_RECEIVE_ID"):
        _channel(lambda r: _token_ok(), receive_id="").send(make_message("x"))


def test_lists_chats_across_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return _token_ok()
        assert request.url.path == "/open-apis/im/v1/chats"
        if request.url.params.get("page_token") == "p2":
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_2", "name": "实验"}], "has_more": False}})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"chat_id": "oc_1", "name": "通知"}], "has_more": True, "page_token": "p2"}})

    assert _channel(handler, receive_id="").list_chats() == [{"chat_id": "oc_1", "name": "通知"}, {"chat_id": "oc_2", "name": "实验"}]


def test_build_channel(tmp_path):
    assert isinstance(build_channel(Settings(home=tmp_path, channel="console")), ConsoleChannel)
    with pytest.raises(ChannelError, match="LARK_APP_ID, LARK_APP_SECRET, LARK_RECEIVE_ID"):
        build_channel(Settings(home=tmp_path))
    lark = build_channel(Settings(home=tmp_path, lark_app_id="cli_x", lark_app_secret="s"), need_receiver=False)
    assert isinstance(lark, LarkChannel)
    lark.close()
