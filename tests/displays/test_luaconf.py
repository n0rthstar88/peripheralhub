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


def test_unknown_keys_and_spacing_preserved():
    text = 'hl.monitor({output="DP-1",  mode = "1x1@1",vrr = 1 , position="9x9", scale=2}) -- keep\n'
    out = update_monitors(text, [replace(DP1, transform=3)])
    assert out == (
        'hl.monitor({output="DP-1",  mode = "2560x1080@75",vrr = 1 , position="0x0", scale=1, transform = 3}) -- keep\n'
    )


def test_existing_transform_replaced_in_place():
    text = 'hl.monitor({ output = "DP-1", transform = 1, bitdepth = 10 })\n'
    assert update_monitors(text, [replace(DP1, transform=2)]) == (
        'hl.monitor({ output = "DP-1", transform = 2, bitdepth = 10, mode = "2560x1080@75", '
        'position = "0x0", scale = 1 })\n'
    )


def test_crlf_preserved(tmp_path):
    text = "-- c\r\n" + 'hl.monitor({ output = "DP-1", mode = "a", position = "0x0", scale = 1, transform = 0 })\r\n'
    out = update_monitors(text, [replace(DP1, transform=1), HDMI])
    assert out.startswith("-- c\r\n") and "\n" not in out.replace("\r\n", "")
    assert out.endswith('transform = 0 })\r\n')
    f = tmp_path / "m.lua"
    f.write_bytes(text.encode())
    write_monitors(str(f), [DP1], 5)
    assert b"\r\n" in f.read_bytes() and b"\n" not in f.read_bytes().replace(b"\r\n", b"")


def test_same_second_backup_not_overwritten(tmp_path):
    f = tmp_path / "monitors.lua"
    f.write_text(FIXTURE)
    b1 = write_monitors(str(f), [replace(DP1, transform=1)], 100)
    b2 = write_monitors(str(f), [replace(DP1, transform=2)], 100)
    assert b1 != b2
    assert Path(b1).read_text() == FIXTURE
    assert "transform = 1" in Path(b2).read_text()


def test_prefix_output_not_confused():
    text = 'hl.monitor({ output = "DP-10", mode = "a", position = "0x0", scale = 1 })\n'
    assert update_monitors(text, [DP1]).startswith(text)


def test_no_trailing_newline_and_unchanged_roundtrip():
    text = 'hl.monitor({ output = "DP-1", mode = "2560x1080@75", position = "0x0", scale = 1, transform = 0 })'
    assert update_monitors(text, [DP1]) == text
    assert update_monitors(text, [DP1, HDMI]).startswith(text + "\n")
    full = FIXTURE.replace(", scale = 1 })", ", scale = 1, transform = 0 })")
    assert update_monitors(full, [DP1, HDMI]) == full
