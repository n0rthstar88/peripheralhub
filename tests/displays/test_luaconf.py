from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from peripheralhub.displays.luaconf import (
    UnsupportedConfig, parse_monitors, render_monitor, update_monitors, write_monitors,
)
from peripheralhub.displays.model import Monitor

FIXTURE = (Path(__file__).parent / "fixtures" / "monitors.lua").read_text()

DP1 = Monitor("DP-1", "x", 2560, 1080, 75.001, 0, 0, 1.0, 0, [])
HDMI = Monitor("HDMI-A-1", "y", 1920, 1080, 143.999, 2560, 0, 1.0, 0, [])


def test_parse_user_file():
    p = parse_monitors(FIXTURE)
    assert p["HDMI-A-1"] == {"mode": "1920x1080@144", "position": "2560x0", "scale": 1.0, "transform": 0}
    assert p["DP-1"]["mode"] == "2560x1080@75"


def test_render_monitor():
    assert render_monitor(DP1) == (
        'hl.monitor({ output = "DP-1", mode = "2560x1080@75", position = "0x0", scale = 1, transform = 0 })'
    )


def test_writer_preserves_unrelated_lines_and_appends_missing():
    unknown = 'hl.monitor({ output = "UNKNOWN-1", mode = "preferred", position = "auto", scale = 1 })'
    text = FIXTURE + "\n-- my note\n" + unknown + "\n"
    new = replace(DP1, name="DP-2", x=4480)
    out = update_monitors(text, [replace(DP1, transform=1), HDMI, new])
    lines = out.splitlines()
    for keep in (
        "local omarchy_gdk_scale = 1", 'local omarchy_monitor_scale = "auto"',
        'hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))', "-- my note", unknown,
        "-- See https://wiki.hypr.land/Configuring/Basics/Monitors/",
    ):
        assert keep in lines
    assert 'hl.monitor({ output = "DP-1", mode = "2560x1080@75", position = "0x0", scale = 1, transform = 1 })' in lines
    assert 'transform = 0' in [l for l in lines if "HDMI-A-1" in l][0]
    assert lines[-1].startswith('hl.monitor({ output = "DP-2"')
    assert out.count("DP-1") == text.count("DP-1")


def test_multiline_known_output_unsupported():
    text = 'hl.monitor({\n  output = "DP-1",\n  mode = "preferred",\n})\n'
    with pytest.raises(UnsupportedConfig):
        update_monitors(text, [DP1])
    assert update_monitors(text, [HDMI]).startswith(text)


def test_commented_line_is_not_edited():
    text = '-- hl.monitor({ output = "DP-1", mode = "x" })\n'
    out = update_monitors(text, [DP1])
    assert out.startswith(text) and out.count("DP-1") == 2


def test_write_creates_backup(tmp_path):
    f = tmp_path / "monitors.lua"
    f.write_text(FIXTURE)
    backup = write_monitors(str(f), [replace(DP1, transform=1)], 1234.9)
    assert backup == str(f) + ".bak.1234"
    assert Path(backup).read_text() == FIXTURE
    assert "transform = 1" in f.read_text()
