import time

from peripheralhub import cli
from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.registry import DeviceStatus


class FakeRegistry:
    def __init__(self):
        now = time.time()
        self._s = [
            DeviceStatus("wd75", "WD75 V2", "ready", "2.4G", BatteryReading(94, None, False, now - 2 * 3600)),
            DeviceStatus("basilisk", "Basilisk V3", "ready", None, None),
            DeviceStatus("headset", "Arctis Nova 7P", "connected", None, BatteryReading(64, True, True, now)),
            DeviceStatus("displays", "Displays", "ready", None, None),
        ]

    def poll_devices(self):
        pass

    def poll_batteries(self):
        pass

    def statuses(self):
        return list(self._s)


def test_cli_status_output(capsys):
    assert cli.main(["status"], registry=FakeRegistry()) == 0
    out = capsys.readouterr().out.splitlines()
    assert any(l.split() == ["WD75", "V2", "2.4G", "94%", "·", "2", "h", "ago"] for l in out), out
    assert any("Basilisk V3" in l and "connected" in l for l in out)
    assert any("Arctis Nova 7P" in l and "64% charging" in l for l in out)
    assert not any("Displays" in l for l in out)


def test_cli_battery_lists_only_batteries(capsys):
    assert cli.main(["battery"], registry=FakeRegistry()) == 0
    out = capsys.readouterr().out
    assert "WD75 V2" in out and "Arctis Nova 7P" in out and "Basilisk" not in out


class FakeWd75:
    def __init__(self):
        self.restored = None

    def refresh(self):
        from peripheralhub.wd75.device import Wd75State
        return Wd75State.READY

    def restore(self, target, **scope):
        self.restored = scope
        return 3

    def ensure_backup(self):
        return "/tmp/backup.json"


def test_restore_factory_requires_yes(capsys):
    wd = FakeWd75()
    assert cli.main(["restore-factory"], wd75=wd) == 2
    assert wd.restored is None
    assert "--yes" in capsys.readouterr().err


def test_restore_factory_layer(capsys):
    wd = FakeWd75()
    assert cli.main(["restore-factory", "--layer", "2", "--yes"], wd75=wd) == 0
    assert wd.restored == {"layers": [2]}
    assert "3 keys" in capsys.readouterr().out


def test_restore_factory_refuses_when_not_ready(capsys):
    from peripheralhub.wd75.device import Wd75State
    wd = FakeWd75()
    wd.refresh = lambda: Wd75State.ASLEEP
    assert cli.main(["restore-factory", "--yes"], wd75=wd) == 1
    assert wd.restored is None


def test_mouse_dpi_rejects_out_of_range(capsys):
    assert cli.main(["mouse", "dpi", "50"], basilisk=object()) == 2
