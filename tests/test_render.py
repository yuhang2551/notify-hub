import json

from notify_hub import render
from notify_hub.models import Level, Message, make_message


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


T = 1_800_000_000.0 + 2 * 3600  # 14:00（测试时区 UTC+4）


def _bundle(level, items, created_at=None):
    return Message(
        title="合并卡片", level=Level(level), source="notify-hub",
        created_at=created_at or items[-1].created_at + 60, items=tuple(items),
    )


def test_held_card_lists_each_message_with_its_button():
    items = [
        make_message("实验跑完了", "IC 0.031", source="exp", link="https://example.com/r/1", created_at=T),
        make_message("导师回复", source="mail", created_at=T + 600),
    ]
    card = render.card(_bundle("normal", items))
    assert card["header"]["template"] == "blue" and card["header"]["title"]["content"] == "合并卡片"
    assert _kinds(card) == ["div", "note", "action", "hr", "div", "note", "hr", "note"]
    assert card["elements"][0]["text"] == {"tag": "plain_text", "content": "实验跑完了\nIC 0.031"}
    assert card["elements"][1]["elements"][0]["content"] == "exp · 14:00"
    assert card["elements"][2]["actions"][0]["text"]["content"] == "打开 example.com"
    assert card["elements"][-1]["elements"][0]["content"].startswith("notify-hub · 普通 · ")


def test_items_from_another_day_show_the_date():
    card = render.card(_bundle("normal", [make_message("昨晚的", source="exp", created_at=T)], created_at=T + 20 * 3600))
    assert card["elements"][1]["elements"][0]["content"] == "exp · 01-15 14:00"


def test_digest_card_groups_titles_by_source():
    items = [
        make_message("订阅 A", source="mail", created_at=T),
        make_message("日报", source="stats", created_at=T + 60),
        make_message("订阅 B", "正文不进汇总", source="mail", created_at=T + 120),
    ]
    card = render.card(_bundle("digest", items))
    assert card["header"]["template"] == "grey"
    assert _kinds(card) == ["div", "hr", "div", "hr", "note"]
    assert card["elements"][0]["text"]["content"] == "mail · 2 条\n• 14:00 订阅 A\n• 14:02 订阅 B"
    assert card["elements"][2]["text"]["content"] == "stats · 1 条\n• 14:01 日报"


def test_long_digest_lists_some_titles_and_counts_the_rest():
    items = [make_message(f"第 {i} 封", source="mail", created_at=T + i) for i in range(render.DIGEST_PER_SOURCE_MAX + 5)]
    lines = render.card(_bundle("digest", items))["elements"][0]["text"]["content"].splitlines()
    assert lines[0] == f"mail · {len(items)} 条" and lines[-1] == "…还有 5 条"
    assert len(lines) == render.DIGEST_PER_SOURCE_MAX + 2


def test_huge_cards_shrink_to_fit_lark():
    items = [make_message("标" * 120, "字" * 2000, source="exp", link="https://example.com", created_at=T + i) for i in range(40)]
    card = render.card(_bundle("normal", items))
    assert len(json.dumps(card, ensure_ascii=False).encode("utf-8")) <= render.CARD_MAX_BYTES
    assert card["elements"][-3]["text"]["content"].startswith("…还有 ")


def test_console_text_for_merged_cards():
    held = render.text(_bundle("normal", [make_message("实验跑完了", "IC 0.031", source="exp", link="https://a.example/x", created_at=T)]))
    assert held.splitlines()[:4] == ["🔵 合并卡片", "  14:00 · exp · 实验跑完了", "    IC 0.031", "    打开 a.example：https://a.example/x"]
    digest = render.text(_bundle("digest", [make_message("日报", source="stats", created_at=T)]))
    assert digest.splitlines()[:3] == ["⚪ 合并卡片", "  stats · 1 条", "  • 14:00 日报"]
