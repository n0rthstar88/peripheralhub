from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.registry import Registry
from peripheralhub.core.settings import Settings
from peripheralhub.wd75.device import Connection, Wd75State


class FakeWd75:
    def __init__(self, connection=Connection.DONGLE, state=Wd75State.READY):
        self.connection, self.state = connection, state

    def refresh(self):
        return self.state


class FakeBasilisk:
    def __init__(self, state="ready"):
        self.target, self.state, self.opens = state, "disconnected", 0

    def open(self):
        self.opens += 1
        self.state = self.target
        return self.state == "ready"


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
        def refresh(self):
            raise OSError("gone")

    reading = BatteryReading(55, False, True, 1.0)
    reg, *_ = make(tmp_path, wd75=BoomWd(), basilisk=Boom(), headset=reading)
    reg.poll_devices()
    reg.poll_batteries()
    s = by_id(reg.statuses())
    assert s["headset"].state == "connected" and s["headset"].battery == reading
    assert s["basilisk"].state == "no_permission"
    assert s["wd75"].state == "disconnected"
