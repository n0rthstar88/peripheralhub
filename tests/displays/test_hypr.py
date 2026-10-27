from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from peripheralhub.displays.hypr import ApplyError, RevertController, apply_monitors, read_monitors
from peripheralhub.displays.model import Monitor

FIXTURE = (Path(__file__).parent / "fixtures" / "hyprctl_monitors.json").read_text()

OLD = [Monitor("DP-1", "a", 2560, 1080, 75.001, 0, 0, 1.0, 0, [])]
NEW = [Monitor("DP-1", "a", 2560, 1080, 75.001, 0, 0, 1.0, 1, [])]


def cp(rc=0, out="ok", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def test_read_monitors_parses_hyprctl_json():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return cp(out=FIXTURE)

    ms = read_monitors(run)
    assert calls[0][:4] == ["hyprctl", "monitors", "all", "-j"]
    by = {m.name: m for m in ms}
    hdmi = by["HDMI-A-1"]
    assert (hdmi.width, hdmi.height, hdmi.x, hdmi.y, hdmi.scale, hdmi.transform) == (1920, 1080, 2560, 0, 1.0, 0)
    assert hdmi.refresh == pytest.approx(144, abs=0.01)
    assert "1920x1080@144" in hdmi.modes and "1920x1080@119.88" in hdmi.modes
    assert len(hdmi.modes) == len(set(hdmi.modes))
    assert by["DP-1"].description.startswith("Innovent")


def test_apply_monitors_one_eval_per_monitor_incl_transform():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return cp()

    apply_monitors(NEW, run)
    assert calls == [[
        "hyprctl", "eval",
        'hl.monitor({ output = "DP-1", mode = "2560x1080@75", position = "0x0", scale = 1, transform = 1 })',
    ]]


def test_apply_monitors_disabled_output():
    calls = []
    off = [Monitor("DP-1", "a", 2560, 1080, 75.0, 0, 0, 1.0, 0, [], disabled=True)]
    apply_monitors(off, lambda cmd, **kw: calls.append(cmd) or cp())
    assert calls[0][2] == 'hl.monitor({ output = "DP-1", disabled = true })'


@pytest.mark.parametrize("res", [cp(rc=7, out="error: x"), cp(out="error: bad"), cp(out="Invalid mode")])
def test_apply_monitors_raises_on_failure(res):
    with pytest.raises(ApplyError):
        apply_monitors(NEW, lambda cmd, **kw: res)


def test_apply_monitors_raises_when_hyprctl_missing():
    def run(cmd, **kw):
        raise FileNotFoundError("hyprctl")

    with pytest.raises(ApplyError):
        apply_monitors(NEW, run)


class Rec:
    def __init__(self, fail_first=False):
        self.applied, self.written, self.fail_first = [], [], fail_first

    def apply(self, ms):
        self.applied.append(ms)
        if self.fail_first and len(self.applied) == 1:
            raise ApplyError("boom")

    def write(self, path, ms, now):
        self.written.append((path, ms))
        return path + ".bak.1"


def ctl(rec, seconds=15):
    return RevertController(OLD, apply=rec.apply, write=rec.write, path="/nonexistent/monitors.lua", seconds=seconds)


def test_keep_writes_file_once_and_never_before_keep():
    rec = Rec()
    c = ctl(rec)
    c.start(NEW)
    assert rec.applied == [NEW] and rec.written == []
    assert c.tick() == 14 and rec.written == []
    assert c.keep() == "/nonexistent/monitors.lua.bak.1"
    assert rec.written == [("/nonexistent/monitors.lua", NEW)]
    with pytest.raises(RuntimeError):
        c.keep()
    c.cancel()
    assert len(rec.written) == 1 and rec.applied == [NEW]  # kept: no revert, no extra write


def test_revert_on_cancel_and_on_failure():
    rec = Rec()
    c = ctl(rec)
    c.start(NEW)
    c.cancel()
    assert rec.applied == [NEW, OLD] and rec.written == []

    rec = Rec(fail_first=True)
    with pytest.raises(ApplyError):
        ctl(rec).start(NEW)
    assert rec.applied == [NEW, OLD] and rec.written == []


def test_tick_reverts_at_zero():
    rec = Rec()
    c = ctl(rec)
    c.start(NEW)
    left = [c.tick() for _ in range(15)]
    assert left == list(range(14, -1, -1))
    assert rec.applied == [NEW, OLD] and rec.written == []
    assert c.tick() == 0 and rec.applied == [NEW, OLD]  # no second revert


class Flaky(Rec):
    """apply raises on the calls whose 1-based index is in `fail`."""

    def __init__(self, fail, exc=ApplyError("boom")):
        super().__init__()
        self.fail, self.exc = set(fail), exc

    def apply(self, ms):
        self.applied.append(ms)
        if len(self.applied) in self.fail:
            raise self.exc


def test_cancel_revert_failure_does_not_raise_and_retry_works():
    rec = Flaky({2})
    c = ctl(rec)
    c.start(NEW)
    c.cancel()
    assert c.state == "revert_failed" and isinstance(c.last_error, ApplyError)
    assert c.retry_revert() is True
    assert c.state == "reverted" and c.last_error is None
    assert rec.applied == [NEW, OLD, OLD] and rec.written == []


def test_tick_to_zero_revert_failure_does_not_raise():
    rec = Flaky({2})
    c = ctl(rec, seconds=2)
    c.start(NEW)
    assert c.tick() == 1
    assert c.tick() == 0
    assert c.state == "revert_failed"
    assert c.tick() == 0 and len(rec.applied) == 2
    assert c.retry_revert() and c.state == "reverted"
    with pytest.raises(RuntimeError):
        c.keep()


def test_start_double_failure_names_both():
    rec = Flaky({1, 2}, ApplyError("boom"))
    c = ctl(rec)
    with pytest.raises(ApplyError, match="revert failed") as ei:
        c.start(NEW)
    assert isinstance(ei.value.__cause__, ApplyError)
    assert c.state == "revert_failed" and rec.written == []
    assert c.retry_revert() is True and c.state == "reverted"


def test_start_non_applyerror_triggers_revert():
    rec = Flaky({1}, ValueError("weird"))
    c = ctl(rec)
    with pytest.raises(ApplyError) as ei:
        c.start(NEW)
    assert isinstance(ei.value.__cause__, ValueError)
    assert rec.applied == [NEW, OLD] and c.state == "reverted"


def test_apply_monitors_timeout_becomes_applyerror():
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, 5)

    with pytest.raises(ApplyError):
        apply_monitors(NEW, run)
    assert seen["timeout"] == 5


def test_controller_path_is_required():
    with pytest.raises(TypeError):
        RevertController(OLD)  # type: ignore[call-arg]


def test_read_monitors_rotated_keeps_reported_size():
    import json
    d = json.loads(FIXTURE)[1]
    d["transform"] = 1
    ms = read_monitors(lambda cmd, **kw: cp(out=json.dumps([d])))
    assert (ms[0].width, ms[0].height, ms[0].transform) == (1920, 1080, 1)


def _mon(name, w, h, x=0, y=0, transform=0):
    return Monitor(name, name, w, h, 60.0, x, y, 1.0, transform, [f"{w}x{h}@60"])


def _simulate(current, steps):
    from peripheralhub.displays.model import overlaps
    state = {m.name: m for m in current}
    for s in steps:
        state[s.name] = s
        live = [m for m in state.values() if not m.disabled]
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                assert not overlaps(a, b), f"{a.name} overlaps {b.name} after applying {s}"
    return state


def test_apply_order_revert_after_left_monitor_rotated_never_overlaps():
    from peripheralhub.displays.hypr import apply_order
    current = [_mon("DP-1", 2560, 1080, 0, 0, transform=1), _mon("HDMI-A-1", 1920, 1080, 1080, 0)]
    target = [_mon("DP-1", 2560, 1080, 0, 0), _mon("HDMI-A-1", 1920, 1080, 2560, 0)]
    steps = apply_order(current, target)
    state = _simulate(current, steps)
    assert [state[m.name] for m in target] == target
    assert [s.name for s in steps] == ["HDMI-A-1", "DP-1"]


def test_apply_order_swap_parks_one_monitor():
    from peripheralhub.displays.hypr import apply_order
    current = [_mon("A", 100, 100, 0), _mon("B", 100, 100, 100)]
    target = [_mon("A", 100, 100, 100), _mon("B", 100, 100, 0)]
    steps = apply_order(current, target)
    state = _simulate(current, steps)
    assert [state[m.name] for m in target] == target
    assert len(steps) == 3


def test_apply_order_keeps_order_when_nothing_moves():
    from peripheralhub.displays.hypr import apply_order
    ms = [_mon("A", 100, 100, 0), _mon("B", 100, 100, 100)]
    assert apply_order(ms, ms) == ms


def test_apply_live_reads_current_state_first():
    import json
    from peripheralhub.displays.hypr import apply_live
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["hyprctl", "monitors"]:
            return cp(out=json.dumps([
                {"name": "DP-1", "description": "", "width": 2560, "height": 1080, "refreshRate": 60.0,
                 "x": 0, "y": 0, "scale": 1.0, "transform": 1, "availableModes": []},
                {"name": "HDMI-A-1", "description": "", "width": 1920, "height": 1080, "refreshRate": 60.0,
                 "x": 1080, "y": 0, "scale": 1.0, "transform": 0, "availableModes": []}]))
        return cp()

    apply_live([_mon("DP-1", 2560, 1080, 0, 0), _mon("HDMI-A-1", 1920, 1080, 2560, 0)], run)
    evals = [c[2] for c in calls if c[1] == "eval"]
    assert "HDMI-A-1" in evals[0] and "DP-1" in evals[1]


def test_controller_defaults_to_apply_live():
    from peripheralhub.displays.hypr import apply_live
    assert RevertController([], path="x")._apply is apply_live
