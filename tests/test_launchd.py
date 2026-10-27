import plistlib
import subprocess

import pytest

from notify_hub import launchd
from notify_hub.config import Settings


class FakeLaunchctl:
    """记下调用了哪些 launchctl 子命令；可以让 bootstrap 失败几次、让 load 失败。"""

    def __init__(self, fail_bootstrap: int = 0, fail_load: bool = False):
        self.calls: list[str] = []
        self.fail_bootstrap = fail_bootstrap
        self.fail_load = fail_load

    def __call__(self, args, **kwargs):
        self.calls.append(args[1])
        failed = (args[1] == "bootstrap" and self.fail_bootstrap > 0) or (args[1] == "load" and self.fail_load)
        if args[1] == "bootstrap" and self.fail_bootstrap > 0:
            self.fail_bootstrap -= 1
        return subprocess.CompletedProcess(args, 5 if failed else 0, stdout="", stderr="Bootstrap failed: 5" if failed else "")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(launchd.time, "sleep", lambda seconds: None)


def test_plist_runs_flush_every_ten_minutes(tmp_path):
    data = launchd.plist(Settings(home=tmp_path / "hub"))
    assert data["Label"] == "com.notify-hub.flush"
    assert data["ProgramArguments"][1:] == ["-m", "notify_hub", "flush", "--quiet"]
    assert data["StartInterval"] == 600 and data["RunAtLoad"] is True
    assert data["StandardOutPath"] == str(tmp_path / "hub" / "logs" / "flush.log")
    assert data["EnvironmentVariables"]["NOTIFY_HUB_HOME"] == str(tmp_path / "hub")
    assert "NOTIFY_HUB_ENV" not in data["EnvironmentVariables"]


def test_a_custom_env_file_is_passed_on(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_HUB_ENV", "/x/notify.env")
    assert launchd.plist(Settings(home=tmp_path))["EnvironmentVariables"]["NOTIFY_HUB_ENV"] == "/x/notify.env"


def test_install_writes_the_plist_and_loads_it(tmp_path):
    run = FakeLaunchctl()
    path = launchd.install(Settings(home=tmp_path / "hub"), directory=tmp_path / "agents", run=run)
    assert path == tmp_path / "agents" / "com.notify-hub.flush.plist"
    assert plistlib.loads(path.read_bytes())["Label"] == launchd.LABEL
    assert run.calls == ["bootout", "bootstrap"]
    assert (tmp_path / "hub" / "logs").is_dir()


def test_install_retries_then_falls_back_to_load(tmp_path):
    run = FakeLaunchctl(fail_bootstrap=2)
    launchd.install(Settings(home=tmp_path / "hub"), directory=tmp_path, run=run)
    assert run.calls == ["bootout", "bootstrap", "bootstrap", "load"]
    with pytest.raises(RuntimeError, match="Bootstrap failed"):
        launchd.install(Settings(home=tmp_path / "hub"), directory=tmp_path, run=FakeLaunchctl(fail_bootstrap=2, fail_load=True))


def test_uninstall(tmp_path):
    run = FakeLaunchctl()
    assert not launchd.uninstall(directory=tmp_path, run=run)
    launchd.install(Settings(home=tmp_path / "hub"), directory=tmp_path, run=run)
    assert launchd.uninstall(directory=tmp_path, run=run)
    assert not launchd.plist_path(tmp_path).exists()


def test_cron_line_for_other_systems(tmp_path):
    line = launchd.cron_line(Settings(home=tmp_path / "hub"))
    assert line.startswith("*/10 * * * * ") and "-m notify_hub flush --quiet" in line
    assert line.endswith(f"{tmp_path / 'hub' / 'logs' / 'flush.log'} 2>&1")
