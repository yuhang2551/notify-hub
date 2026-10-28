import os
import time

import pytest

from notify_hub.config import Settings
from notify_hub.hub import Hub


class FakeChannel:
    """记下发了什么。fail_with 设了就每次都抛它；failures 里放异常，就按顺序先抛完这几个，再正常发。"""

    name = "fake"

    def __init__(self) -> None:
        self.sent = []
        self.fail_with: Exception | None = None
        self.failures: list[Exception] = []
        self.calls = 0
        self.closed = False

    def send(self, msg) -> None:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(msg)

    def close(self) -> None:
        self.closed = True


NOW = 1_800_000_000.0  # 2027-01-15 12:00（UTC+4）

# 测试里的时区固定成 UTC+4（没有夏令时），卡片底部的时间才不随跑测试的机器变
TEST_TZ = "GST-4"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """测试不读你真实的 ~/.notify-hub，也不受外面 LARK_ 环境变量和本机时区影响。"""
    for name in list(os.environ):
        if name.startswith(("NOTIFY_HUB_", "LARK_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("NOTIFY_HUB_HOME", str(tmp_path / "hub"))
    monkeypatch.setenv("TZ", TEST_TZ)
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(home=tmp_path / "hub", channel="console")


@pytest.fixture
def channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def sleeps() -> list[float]:
    """重试前本该等的秒数记在这里，测试不用真等。"""
    return []


@pytest.fixture
def hub(settings, channel, sleeps):
    h = Hub(settings, channel=channel, clock=lambda: NOW, sleep=sleeps.append)
    yield h
    h.close()
