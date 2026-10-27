import pytest

from peripheralhub.displays.model import Monitor
from peripheralhub.ui.pages.displays import (
    Selection, ViewMap, build_layout, fit_view, has_monitor_override, parse_mode,
)


def mon(name, w, h, x=0, y=0, scale=1.0, transform=0, refresh=60.0, modes=None):
    return Monitor(name, name, w, h, refresh, x, y, scale, transform, modes or [f"{w}x{h}@60"])


def test_parse_mode():
    assert parse_mode("2560x1080@59.98") == (2560, 1080, 59.98)
    assert parse_mode("1920x1080@144") == (1920, 1080, 144.0)
    with pytest.raises(ValueError):
        parse_mode("garbage")


def test_fit_view_maps_true_relative_size_and_round_trips():
    ms = [mon("DP-1", 2560, 1080), mon("HDMI-A-1", 1920, 1080, x=2560)]
    v = fit_view(ms, 900, 400)
    assert v.scale > 0
    # logical 2560 wide vs 1920 wide keep the 4:3 ratio on screen
    assert (2560 * v.scale) / (1920 * v.scale) == pytest.approx(4 / 3)
    for lx, ly in [(0, 0), (2560, 1080), (-300, 200)]:
        cx, cy = v.to_canvas(lx, ly)
        assert v.to_logical(cx, cy) == pytest.approx((lx, ly))
    # whole layout fits on the canvas
    x1, y1 = v.to_canvas(4480, 1080)
    assert 0 <= v.to_canvas(0, 0)[0] and x1 <= 900 and y1 <= 400


def test_fit_view_respects_rotation_and_scale():
    ms = [mon("A", 1920, 1080, transform=1, scale=2.0)]  # logical 540 x 960
    v = fit_view(ms, 800, 800)
    assert isinstance(v, ViewMap)
    x0, y0 = v.to_canvas(0, 0)
    x1, y1 = v.to_canvas(540, 960)
    assert (y1 - y0) / (x1 - x0) == pytest.approx(960 / 540)


def test_fit_view_empty_is_safe():
    assert fit_view([], 100, 100).scale > 0


def test_build_layout_applies_selection_and_leaves_input_alone():
    a = mon("A", 2560, 1080, modes=["2560x1080@60", "1920x1080@60"])
    b = mon("B", 1920, 1080, x=2560)
    out = build_layout([a, b], {"A": Selection("1920x1080@60", 1.5, 1)})
    assert (out[0].width, out[0].height, out[0].refresh, out[0].scale, out[0].transform) == (1920, 1080, 60.0, 1.5, 1)
    assert out[1] == b
    assert a.width == 2560 and a.transform == 0


def test_has_monitor_override(tmp_path):
    p = tmp_path / "omasettings.lua"
    assert not has_monitor_override(str(p))  # missing file
    p.write_text("hl.config({ gaps = 1 })\n")
    assert not has_monitor_override(str(p))
    p.write_text('hl.monitor({ output = "DP-1" })\n')
    assert has_monitor_override(str(p))


def test_reattach_snaps_rotated_monitor_back_to_its_neighbour():
    from peripheralhub.ui.pages.displays import reattach
    from peripheralhub.displays.model import validate_layout
    a = mon("DP-1", 2560, 1080, transform=1)  # now 1080 wide: gap to B at 2560
    b = mon("HDMI-A-1", 1920, 1080, x=2560)
    out = reattach([a, b], "DP-1")
    assert validate_layout(out) == []
    assert out[1] == b
    ok = [mon("A", 100, 100), mon("B", 100, 100, x=100)]
    assert reattach(ok, "A") is ok
