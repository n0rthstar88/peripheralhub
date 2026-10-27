import os

from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.registry import DeviceStatus
from peripheralhub.core.settings import Settings
from peripheralhub.service import Service


class FakeBasilisk:
    MATRIX_COLS = 11
    ZONES = {"logo": range(0, 1), "wheel": range(1, 2), "strip": range(2, 11)}

    def __init__(self):
        self.calls = []
        self.frames = 0

    def __getattr__(self, name):
        if name.startswith("set_") or name == "apply_effect":
            return lambda *a, **kw: self.calls.append((name, a, kw))
        raise AttributeError(name)

    def send_frame(self, colors):
        assert len(colors) == 11
        self.frames += 1


class FakeRegistry:
    def __init__(self, mouse="ready"):
        self.mouse = mouse
        self.device_polls = 0
        self.battery_polls = 0
        self.headset = None

    def poll_devices(self):
        self.device_polls += 1

    def poll_batteries(self):
        self.battery_polls += 1

    def statuses(self):
        return [DeviceStatus("basilisk", "Basilisk V3", self.mouse, None, None),
                DeviceStatus("headset", "Arctis Nova 7P", "connected", None, self.headset)]


class FakeNotifier:
    def __init__(self):
        self.checks = []

    def check(self, device_id, title, r):
        self.checks.append((device_id, r))
        return False


def make(tmp_path, effect=None, mouse="ready", **extra):
    s = Settings(str(tmp_path / "settings.json"))
    if effect is not None:
        s.set("mouse.effect", effect)
    for k, v in extra.items():
        s.set(k.replace("__", "."), v)
    b, r, n = FakeBasilisk(), FakeRegistry(mouse), FakeNotifier()
    return Service(s, b, r, n, clock=lambda: 0.0), s, b, r, n


def run(svc, seconds, dt=0.01, start=0.0):
    for i in range(round(seconds / dt)):
        svc.step(start + i * dt)


def test_host_effect_sends_frames_at_20fps(tmp_path):
    svc, _s, b, _r, _n = make(tmp_path, {"kind": "host", "name": "color_cycle", "params": {"period": 8}})
    run(svc, 1.0)
    assert b.frames == 20


def test_firmware_effect_sends_no_frames(tmp_path):
    svc, _s, b, _r, _n = make(tmp_path, {"kind": "firmware", "name": "spectrum", "params": {}})
    run(svc, 1.0)
    assert b.frames == 0


def test_no_frames_while_mouse_absent(tmp_path):
    svc, _s, b, _r, _n = make(tmp_path, {"kind": "host", "name": "color_cycle", "params": {}}, mouse="disconnected")
    run(svc, 1.0)
    assert b.frames == 0


def test_settings_change_picked_up(tmp_path):
    svc, s, b, _r, _n = make(tmp_path, {"kind": "firmware", "name": "spectrum", "params": {}})
    run(svc, 0.5)
    other = Settings(str(s.path))  # the app's instance
    other.set("mouse.effect", {"kind": "host", "name": "breathing", "params": {"color": [255, 0, 0]}})
    os.utime(s.path, (1e9, 2e9))  # bump mtime even on coarse-timestamp filesystems
    run(svc, 0.5, start=0.5)
    assert b.frames >= 9


def test_mouse_reappears_reapplies(tmp_path):
    svc, _s, b, r, _n = make(tmp_path, {"kind": "firmware", "name": "static", "params": {"color": [1, 2, 3]}},
                             mouse="disconnected", mouse__dpi=800)
    run(svc, 3.0)
    assert b.calls == []
    r.mouse = "ready"
    run(svc, 3.0, start=3.0)
    names = [c[0] for c in b.calls]
    assert names.count("set_dpi") == 1
    assert ("apply_effect", ("static",), {"color": [1, 2, 3]}) in b.calls
    run(svc, 3.0, start=6.0)
    assert [c[0] for c in b.calls].count("set_dpi") == 1


def test_apply_saved_mouse_full(tmp_path):
    svc, _s, b, _r, _n = make(tmp_path, {"kind": "host", "name": "color_cycle", "params": {}},
                              mouse__dpi=1600, mouse__poll=500, mouse__brightness=128,
                              mouse__stages={"values": [400, 800], "active": 2})
    svc.apply_saved_mouse()
    assert ("set_dpi", (1600,), {}) in b.calls
    assert ("set_stages", ([400, 800], 2), {}) in b.calls
    assert ("set_poll", (500,), {}) in b.calls
    assert ("set_brightness", (128,), {}) in b.calls
    assert not any(c[0] == "apply_effect" for c in b.calls)  # host effects are frames, not firmware


def test_polling_cadence_and_notifier(tmp_path):
    svc, _s, _b, r, n = make(tmp_path)
    r.headset = BatteryReading(10, False, True, 0.0)
    run(svc, 10.0, dt=0.05)
    assert 5 <= r.device_polls <= 6
    assert r.battery_polls == 1
    assert ("headset", r.headset) in n.checks


def test_frame_error_does_not_crash(tmp_path):
    svc, _s, b, _r, _n = make(tmp_path, {"kind": "host", "name": "color_cycle", "params": {}})

    def boom(colors):
        raise OSError("gone")

    b.send_frame = boom
    run(svc, 0.2)
