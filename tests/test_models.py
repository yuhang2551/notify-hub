import pytest

from notify_hub.models import TITLE_MAX, Level, check_link, link_domain, make_message


def test_title_is_one_line_and_clipped():
    msg = make_message("  第一行\n第二行  ")
    assert msg.title == "第一行 第二行"
    long = make_message("长" * 500)
    assert len(long.title) == TITLE_MAX and long.title.endswith("…")


def test_defaults():
    msg = make_message("hi")
    assert msg.level is Level.NORMAL and msg.source == "default" and msg.body == "" and msg.link is None and msg.key is None


@pytest.mark.parametrize("bad", ["", "   ", "\n"])
def test_empty_title_rejected(bad):
    with pytest.raises(ValueError, match="标题"):
        make_message(bad)


def test_level_must_be_known():
    assert make_message("x", level="urgent").level is Level.URGENT
    with pytest.raises(ValueError, match="urgent、normal 或 digest"):
        make_message("x", level="loud")


def test_source_must_be_short_and_without_spaces():
    assert make_message("x", source=" mail ").source == "mail"
    assert make_message("x", source="").source == "default"
    with pytest.raises(ValueError, match="来源"):
        make_message("x", source="my mail")


@pytest.mark.parametrize("link", ["https://example.com/a?b=1", "http://localhost:8000/x"])
def test_http_links_accepted(link):
    assert check_link(link) == link


@pytest.mark.parametrize("link", ["javascript:alert(1)", "ftp://example.com/x", "https://", "example.com"])
def test_other_links_rejected(link):
    with pytest.raises(ValueError, match="http"):
        check_link(link)


def test_link_domain_drops_www():
    assert link_domain("https://www.github.com/yuhang2551") == "github.com"
    assert link_domain("https://open.larksuite.com/app") == "open.larksuite.com"
