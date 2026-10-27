import os

import pytest

from notify_hub.config import Settings
from notify_hub.hub import Hub


class FakeChannel:
    """记下发了什么；设置 fail_with 就让每次发送都抛这个异常。"""

    name = "fake"

    def __init__(self) -> None:
        self.sent = []
        self.fail_with: Exception | None = None
        self.calls = 0
        self.closed = False

    def send(self, msg) -> None:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(msg)

    def close(self) -> None:
        self.closed = True


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """测试不读你真实的 ~/.notify-hub，也不受外面 LARK_ 环境变量影响。"""
    for name in list(os.environ):
        if name.startswith(("NOTIFY_HUB_", "LARK_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("NOTIFY_HUB_HOME", str(tmp_path / "hub"))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(home=tmp_path / "hub", channel="console")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def hub(settings, channel, clock):
    h = Hub(settings, channel=channel, clock=clock)
    yield h
    h.close()
