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


def test_plist_runs_flush_morning_noon_and_evening(tmp_path):
    data = launchd.plist(Settings(home=tmp_path / "hub"))
    assert data["Label"] == "com.notify-hub.flush"
    assert data["ProgramArguments"][1:] == ["-m", "notify_hub", "flush", "--quiet"]
    assert data["StartCalendarInterval"] == [{"Hour": 8, "Minute": 0}, {"Hour": 12, "Minute": 0}, {"Hour": 18, "Minute": 0}]
    assert "StartInterval" not in data and data["RunAtLoad"] is True
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


def test_installed_reads_back_the_times(tmp_path):
    assert launchd.installed(tmp_path) is None
    settings = Settings(home=tmp_path / "hub", schedule_times="21:30,7:05")
    launchd.install(settings, directory=tmp_path, run=FakeLaunchctl())
    assert launchd.installed(tmp_path) == launchd.describe(settings) == "每天 07:05、21:30"
    # 0.2.0 装的是每 10 分钟一次：看得出来和现在的配置不一样
    launchd.plist_path(tmp_path).write_bytes(plistlib.dumps({"Label": launchd.LABEL, "StartInterval": 600}))
    assert launchd.installed(tmp_path) == "每 10 分钟"


def test_late_cards(tmp_path):
    assert launchd.late_cards(Settings(home=tmp_path)) == []  # 默认的 08:00 和 18:00 都在定时任务里
    notes = launchd.late_cards(Settings(home=tmp_path, quiet_hours="23:00-07:00", digest_time="21:00"))
    assert len(notes) == 2 and "07:00" in notes[0] and "21:00" in notes[1]
    assert launchd.late_cards(Settings(home=tmp_path, quiet_hours="off", digest_time="off", schedule_times="12:00")) == []


def test_uninstall(tmp_path):
    run = FakeLaunchctl()
    assert not launchd.uninstall(directory=tmp_path, run=run)
    launchd.install(Settings(home=tmp_path / "hub"), directory=tmp_path, run=run)
    assert launchd.uninstall(directory=tmp_path, run=run)
    assert not launchd.plist_path(tmp_path).exists()


def test_cron_lines_for_other_systems(tmp_path):
    [line] = launchd.cron_lines(Settings(home=tmp_path / "hub"))
    assert line.startswith("0 8,12,18 * * * ") and "-m notify_hub flush --quiet" in line
    assert line.endswith(f"{tmp_path / 'hub' / 'logs' / 'flush.log'} 2>&1")
    lines = launchd.cron_lines(Settings(home=tmp_path, schedule_times="07:30,12:00,21:30"))
    assert [line.split(" * * * ")[0] for line in lines] == ["0 12", "30 7,21"]
