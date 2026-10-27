from peripheralhub.core.battery import BatteryReading
from peripheralhub.ui.battery import battery_view


def test_live_caption():
    assert battery_view(BatteryReading(94, None, True, 0), 0) == ("94%", "green", False)


def test_stale_caption():
    assert battery_view(BatteryReading(94, None, False, 0), 7200) == ("94% · 2 h ago", "green", False)


def test_charging_on_cable():
    assert battery_view(BatteryReading(94, True, False, 0), 60)[2] is True


def test_unknown():
    assert battery_view(BatteryReading(None, True, False, 0), 0) == ("Charging", "green", True)
    assert battery_view(None, 0) == ("No reading yet", "neutral", False)
