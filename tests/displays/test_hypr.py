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
