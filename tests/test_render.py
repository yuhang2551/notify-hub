from notify_hub import render
from notify_hub.models import make_message


def _kinds(card):
    return [e["tag"] for e in card["elements"]]


def test_card_color_follows_level():
    assert render.card(make_message("x", level="urgent"))["header"]["template"] == "red"
    assert render.card(make_message("x", level="normal"))["header"]["template"] == "blue"
    assert render.card(make_message("x", level="digest"))["header"]["template"] == "grey"


def test_card_without_body_or_link_has_only_footer():
    card = render.card(make_message("只有标题", source="mail"))
    assert card["header"]["title"] == {"tag": "plain_text", "content": "只有标题"}
    assert _kinds(card) == ["note"]
    assert card["elements"][0]["elements"][0]["content"].startswith("mail · 普通 · ")


def test_body_is_plain_text_so_markdown_links_stay_text():
    body = "点这里 [领取奖励](https://evil.example)"
    card = render.card(make_message("x", body))
    assert card["elements"][0] == {"tag": "div", "text": {"tag": "plain_text", "content": body}}
    assert "action" not in _kinds(card)


def test_link_becomes_button_showing_its_domain():
    card = render.card(make_message("x", link="https://www.example.com/run/1"))
    action = card["elements"][0]
    assert action["tag"] == "action"
    button = action["actions"][0]
    assert button["text"]["content"] == "打开 example.com"
    assert button["url"] == "https://www.example.com/run/1"
    assert button["type"] == "primary"
    assert render.card(make_message("x", level="urgent", link="https://a.example"))["elements"][0]["actions"][0]["type"] == "danger"


def test_long_body_is_clipped():
    card = render.card(make_message("x", "字" * (render.BODY_MAX + 50)))
    content = card["elements"][0]["text"]["content"]
    assert len(content) == render.BODY_MAX and content.endswith("…")


def test_console_text():
    out = render.text(make_message("备份失败", "磁盘满了", level="urgent", source="backup", link="https://a.example/x"))
    lines = out.splitlines()
    assert lines[0] == "🔴 备份失败"
    assert lines[1] == "磁盘满了"
    assert lines[2] == "打开 a.example：https://a.example/x"
    assert lines[3].startswith("backup · 紧急 · ")
