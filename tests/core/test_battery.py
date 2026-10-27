from peripheralhub.core.battery import (
    BatteryReading, age_text, battery_color, keyboard_battery, read_upower_keyboard,
)
from peripheralhub.core.settings import Settings
from peripheralhub.wd75.device import Connection

KBD = "/org/freedesktop/UPower/devices/keyboard_dev_00_60_A3_43_B0_64"


class FakeBus:
    def __init__(self, devices):
        self.devices = devices

    def enumerate_devices(self):
        return list(self.devices)

    def get_properties(self, path):
        return self.devices[path]


def test_battery_color_thresholds():
    assert [battery_color(x) for x in (100, 41, 40, 20, 19, 0)] == [
        "green", "green", "amber", "amber", "red", "red"]


def test_age_text():
    assert age_text(30) == "just now" and age_text(300) == "5 min ago"
    assert age_text(7200) == "2 h ago" and age_text(3 * 86400) == "3 days ago"


def test_keyboard_battery_live_is_stored_then_used_when_on_cable(tmp_path):
    s = Settings(str(tmp_path / "s.json"))
    r = keyboard_battery(BatteryReading(94, None, True, 1000.0), Connection.BLUETOOTH, s, 1000.0)
    assert r.live and r.level == 94
    r = keyboard_battery(None, Connection.USB, s, 8200.0)
    assert (r.level, r.charging, r.live, r.measured_at) == (94, True, False, 1000.0)
    r = keyboard_battery(None, Connection.DONGLE, s, 8200.0)
    assert (r.level, r.charging, r.live) == (94, None, False)


def test_keyboard_battery_unknown_when_never_seen(tmp_path):
    s = Settings(str(tmp_path / "s.json"))
    assert keyboard_battery(None, Connection.DONGLE, s, 5.0).level is None


def test_upower_finds_keyboard_by_model():
    bus = FakeBus({
        "/other": {"Model": "Mouse", "Percentage": 50.0},
        KBD: {"Model": "Womier WD75 BT1", "Percentage": 93.6, "State": 1, "IsPresent": True},
    })
    r = read_upower_keyboard(bus, now=7.0)
    assert (r.level, r.charging, r.live, r.measured_at) == (94, True, True, 7.0)


def test_upower_not_present_is_none():
    bus = FakeBus({KBD: {"Model": "Womier WD75 BT1", "Percentage": 94.0, "IsPresent": False}})
    assert read_upower_keyboard(bus) is None


def test_upower_mac_path_needs_matching_model():
    bus = FakeBus({KBD: {"Model": "Other Keyboard", "NativePath": "dev_00_60_A3_43_B0_64",
                         "Percentage": 80.0}})
    assert read_upower_keyboard(bus) is None
    bus = FakeBus({KBD: {"Model": "WD75 BT", "NativePath": "dev_00_60_A3_43_B0_64",
                         "Percentage": 80.0}})
    assert read_upower_keyboard(bus).level == 80


def test_upower_no_device_or_bus_error():
    assert read_upower_keyboard(FakeBus({})) is None

    class Broken(FakeBus):
        def enumerate_devices(self):
            raise RuntimeError("no bus")

    assert read_upower_keyboard(Broken({})) is None
