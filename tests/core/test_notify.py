from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.notify import LowBatteryNotifier
from peripheralhub.core.settings import Settings


def reading(level, charging=False, live=True):
    return BatteryReading(level, charging, live, 0.0)


def make(tmp_path, threshold=20):
    s = Settings(str(tmp_path / "settings.json"))
    s.set("battery.low_threshold", threshold)
    sent = []
    return LowBatteryNotifier(s, send=lambda summary, body: sent.append((summary, body))), sent


def test_fires_once_below_threshold(tmp_path):
    n, sent = make(tmp_path)
    fired = [n.check("headset", "Arctis Nova 7P", reading(v)) for v in (25, 20, 18)]
    assert fired == [False, True, False]
    assert len(sent) == 1
    assert "Arctis Nova 7P" in sent[0][0] and "20%" in sent[0][1]


def test_rearms_after_recovery(tmp_path):
    n, sent = make(tmp_path)
    for v in (18, 26, 19):
        n.check("headset", "Arctis Nova 7P", reading(v))
    assert len(sent) == 2


def test_no_rearm_on_small_recovery(tmp_path):
    n, sent = make(tmp_path)
    for v in (18, 24, 19):
        n.check("headset", "Arctis Nova 7P", reading(v))
    assert len(sent) == 1


def test_charging_rearms(tmp_path):
    n, sent = make(tmp_path)
    n.check("wd75", "WD75 V2", reading(15))
    n.check("wd75", "WD75 V2", reading(16, charging=True))
    n.check("wd75", "WD75 V2", reading(15))
    assert len(sent) == 2


def test_stale_or_charging_never_fires(tmp_path):
    n, sent = make(tmp_path)
    assert not n.check("wd75", "WD75 V2", reading(5, live=False))
    assert not n.check("wd75", "WD75 V2", reading(5, charging=True))
    assert not n.check("wd75", "WD75 V2", None)
    assert not n.check("wd75", "WD75 V2", reading(None))
    assert sent == []


def test_devices_tracked_separately_and_threshold_read_live(tmp_path):
    n, sent = make(tmp_path)
    n.check("wd75", "WD75 V2", reading(19))
    n.check("headset", "Arctis Nova 7P", reading(19))
    assert len(sent) == 2
    n._settings.set("battery.low_threshold", 10)
    assert not n.check("mouse", "M", reading(15))


def test_app_watch_defers_to_running_service(tmp_path):
    from peripheralhub.core.notify import AppBatteryWatch
    from peripheralhub.core.registry import DeviceStatus
    n, sent = make(tmp_path)
    active = [True]
    now = [0.0]
    calls = []

    def is_active():
        calls.append(now[0])
        return active[0]

    w = AppBatteryWatch(n, is_service_active=is_active, clock=lambda: now[0], recheck=60)
    low = [DeviceStatus("headset", "Arctis Nova 7P", "connected", None, reading(10)),
           DeviceStatus("displays", "Displays", "ready", None, None)]
    w.feed(low)
    assert sent == []
    now[0] = 30
    w.feed(low)
    assert len(calls) == 1  # cached between rechecks
    active[0] = False
    now[0] = 61
    w.feed(low)
    assert len(sent) == 1 and len(calls) == 2


def test_settings_threshold_clamp():
    from peripheralhub.ui.pages.settings import clamp_threshold
    assert clamp_threshold(5) == 10
    assert clamp_threshold(31) == 30
    assert clamp_threshold("x") == 20
    assert clamp_threshold(14.6) == 15
