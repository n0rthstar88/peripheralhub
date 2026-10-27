from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.registry import Registry
from peripheralhub.core.settings import Settings
from peripheralhub.wd75.device import Connection, Wd75State


class FakeWd75:
    def __init__(self, connection=Connection.DONGLE, state=Wd75State.READY):
        self.connection, self.state = connection, state
        self.node_path, self.busy, self.refreshes = "/dev/hidraw1", False, 0

    def probe(self):
        return self.connection

    def refresh(self):
        self.refreshes += 1
        return self.state


class FakeBasilisk:
    def __init__(self, state="ready"):
        self.target, self.state, self.opens, self.plugged = state, "disconnected", 0, True

    def open(self):
        self.opens += 1
        self.state = self.target if self.plugged else "disconnected"
        return self.state == "ready"

    def present(self):
        return self.plugged

    def close(self):
        self.state = "disconnected"


def make(tmp_path, wd75=None, basilisk=None, headset=None, subscribe=True):
    settings = Settings(str(tmp_path / "s.json"))
    settings.set("battery.wd75", {"level": 80, "at": 1000.0})
    wd75 = wd75 or FakeWd75()
    basilisk = basilisk or FakeBasilisk()
    reg = Registry(settings, wd75=wd75, basilisk=basilisk, headset_reader=lambda: headset,
                   upower_reader=lambda: None, clock=lambda: 1100.0)
    calls = []
    if subscribe:
        reg.subscribe(lambda s: calls.append(s))
    return reg, wd75, basilisk, calls


def by_id(statuses):
    return {s.id: s for s in statuses}


def test_statuses_and_change_notification(tmp_path):
    reg, wd75, _, calls = make(tmp_path)
    reg.poll_devices()
    reg.poll_batteries()
    calls.clear()
    assert by_id(reg.statuses())["wd75"].connection == "2.4G"
    assert by_id(reg.statuses())["wd75"].battery.charging is None
    wd75.connection = Connection.USB
    reg.poll_devices()
    assert len(calls) == 1
    kb = by_id(calls[0])["wd75"]
    assert kb.title == "WD75 V2" and kb.connection == "USB" and kb.battery.charging is True
    assert [s.id for s in calls[0]] == ["wd75", "basilisk", "headset", "displays"]
    d = by_id(calls[0])["displays"]
    assert (d.title, d.state, d.connection, d.battery) == ("Displays", "ready", None, None)


def test_no_callback_when_nothing_changed(tmp_path):
    reg, _, basilisk, calls = make(tmp_path)
    reg.poll_devices()
    reg.poll_batteries()
    calls.clear()
    reg.poll_devices()
    reg.poll_batteries()
    assert calls == []
    assert basilisk.opens == 1  # a ready Basilisk is not reopened every poll


def test_headset_absent_shows_disconnected(tmp_path):
    reg, *_ = make(tmp_path, headset=None)
    reg.poll_batteries()
    h = by_id(reg.statuses())["headset"]
    assert (h.state, h.battery) == ("disconnected", None)


def test_headset_present_and_device_errors_become_state(tmp_path):
    class Boom(FakeBasilisk):
        def open(self):
            self.state = "no_permission"
            raise PermissionError

    class BoomWd(FakeWd75):
        def probe(self):
            raise OSError("gone")

    reading = BatteryReading(55, False, True, 1.0)
    reg, *_ = make(tmp_path, wd75=BoomWd(), basilisk=Boom(), headset=reading)
    reg.poll_devices()
    reg.poll_batteries()
    s = by_id(reg.statuses())
    assert s["headset"].state == "connected" and s["headset"].battery == reading
    assert s["basilisk"].state == "no_permission"
    assert s["wd75"].state == "disconnected"


def test_steady_state_polls_do_not_refresh_and_change_refreshes_once(tmp_path):
    reg, wd75, _, _ = make(tmp_path)
    for _ in range(5):
        reg.poll_devices()
    assert wd75.refreshes == 1
    wd75.connection = Connection.USB
    reg.poll_devices()
    reg.poll_devices()
    assert wd75.refreshes == 2
    reg.refresh_keyboard()
    assert wd75.refreshes == 3


def test_refresh_skipped_while_busy_then_retried(tmp_path):
    reg, wd75, _, _ = make(tmp_path)
    wd75.busy = True
    reg.poll_devices()
    assert wd75.refreshes == 0
    wd75.busy = False
    reg.poll_devices()
    assert wd75.refreshes == 1


def test_basilisk_unplug_and_replug(tmp_path):
    reg, _, mouse, _ = make(tmp_path)
    reg.poll_devices()
    assert by_id(reg.statuses())["basilisk"].state == "ready"
    mouse.plugged = False
    reg.poll_devices()
    assert by_id(reg.statuses())["basilisk"].state == "disconnected"
    mouse.plugged = True
    reg.poll_devices()
    assert by_id(reg.statuses())["basilisk"].state == "ready"
    assert mouse.opens == 3
