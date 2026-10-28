import pytest

from notify_hub.config import Settings, load_settings


def test_defaults(tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    assert settings.channel == "lark" and settings.lark_domain == "https://open.larksuite.com"
    assert settings.lark_receive_id_type is None


def test_reads_env_file_and_environment_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "NOTIFY_HUB_CHANNEL=console\nLARK_APP_ID=cli_file\nLARK_RECEIVE_ID=oc_1\nLARK_RECEIVE_ID_TYPE=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LARK_APP_ID", "cli_env")
    settings = load_settings(env)
    assert settings.channel == "console" and settings.lark_receive_id == "oc_1"
    assert settings.lark_app_id == "cli_env"
    assert settings.lark_receive_id_type is None  # 空值等于没填


def test_overrides_win(tmp_path):
    assert load_settings(tmp_path / "none.env", overrides={"channel": "console", "unknown": 1}).channel == "console"


def test_home_and_env_file_from_environment(tmp_path, monkeypatch):
    home = tmp_path / "custom"
    home.mkdir()
    (home / ".env").write_text("LARK_APP_ID=cli_home\n", encoding="utf-8")
    monkeypatch.setenv("NOTIFY_HUB_HOME", str(home))
    settings = load_settings()
    assert settings.home == home and settings.lark_app_id == "cli_home"
    assert settings.env_path == home / ".env"


def test_bad_channel_is_explained(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NOTIFY_HUB_CHANNEL=email\n", encoding="utf-8")
    with pytest.raises(ValueError, match="NOTIFY_HUB_CHANNEL.*lark 或 console"):
        load_settings(env)


def test_old_settings_are_ignored(tmp_path):
    """0.2 版的免打扰、汇总、定时任务、限流配置留在旧的 .env 里，就算写错了也不报错：已经不读了。"""
    env = tmp_path / ".env"
    env.write_text(
        "NOTIFY_HUB_QUIET_HOURS=23:00\nNOTIFY_HUB_DIGEST_TIME=6pm\nNOTIFY_HUB_SCHEDULE_TIMES=noon\nNOTIFY_HUB_RATE_LIMIT=lots\n",
        encoding="utf-8",
    )
    settings = load_settings(env)
    assert settings == Settings(home=tmp_path / "hub")


def test_missing_lark(tmp_path):
    assert Settings(home=tmp_path).missing_lark() == ["LARK_APP_ID", "LARK_APP_SECRET", "LARK_RECEIVE_ID"]
    assert Settings(home=tmp_path, lark_app_id="a", lark_app_secret="b").missing_lark(need_receiver=False) == []
