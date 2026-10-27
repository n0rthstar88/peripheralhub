from __future__ import annotations

from peripheralhub.displays.model import (
    Monitor, logical_size, mode_string, normalize, snap_position, validate_layout,
)


def mon(name="DP-1", w=2560, h=1080, r=75.001, x=0, y=0, scale=1.0, transform=0, disabled=False):
    return Monitor(name, name, w, h, r, x, y, scale, transform, [], disabled)


def test_logical_size_rotation_and_scale():
    assert logical_size(mon(scale=2, transform=1)) == (540.0, 1280.0)


def test_mode_string_rounds_close_refresh():
    assert mode_string(mon(r=75.001)) == "2560x1080@75"
    assert mode_string(mon(w=1920, r=143.999)) == "1920x1080@144"
    assert mode_string(mon(r=59.94)) == "2560x1080@59.94"


def test_snap_to_right_edge():
    dp1 = mon()
    hdmi = mon("HDMI-A-1", 1920, 1080, 143.999, 2550, 12)
    assert snap_position(hdmi, [dp1], 2550, 12) == (2560, 0)


def test_snap_leaves_far_positions_alone():
    assert snap_position(mon("B"), [mon()], 3000, 500) == (3000, 500)


def test_validate_overlap_and_gap():
    dp1 = mon()
    assert any("overlap" in e for e in validate_layout([dp1, mon("H", 1920, 1080, 144, 2000, 0)]))
    assert any("not touching" in e for e in validate_layout([dp1, mon("H", 1920, 1080, 144, 2660, 0)]))
    assert validate_layout([dp1, mon("H", 1920, 1080, 144, 2560, 0)]) == []


def test_validate_corner_only_is_not_touching_and_all_disabled():
    a, b = mon(), mon("H", 1920, 1080, 144, 2560, 1080)
    assert any("not touching" in e for e in validate_layout([a, b]))
    assert validate_layout([mon(disabled=True)])


def test_normalize_shifts_to_origin():
    out = normalize([mon(x=100, y=50), mon("H", x=2660, y=50)])
    assert [(m.x, m.y) for m in out] == [(0, 0), (2560, 0)]


def test_fractional_scale_snapped_neighbour_is_valid():
    a = mon(w=1920, h=1080, scale=1.75)  # logical 1097.14 wide
    b = mon("B", w=1920, h=1080, scale=1.75)
    x, y = snap_position(b, [a], 1090, 5)
    b.x, b.y = x, y
    assert validate_layout([a, b]) == []
