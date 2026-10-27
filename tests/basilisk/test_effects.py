import pytest

from peripheralhub.basilisk.device import Basilisk
from peripheralhub.basilisk.effects import HOST_EFFECTS, make_effect

Z = {"logo": range(0, 1), "wheel": range(1, 2), "strip": range(2, 13)}

PARAMS = {
    "breathing": {"color": (255, 0, 0)},
    "color_cycle": {},
    "strip_gradient": {"colors": [(255, 0, 0), (0, 0, 255)]},
    "zones_static": {"zone_colors": {"logo": (1, 2, 3), "strip": (9, 8, 7)}},
    "match_keyboard": {"hue": 40, "sat": 200},
}


def test_registry_keys():
    assert set(HOST_EFFECTS) == set(PARAMS)


@pytest.mark.parametrize("name", sorted(PARAMS))
@pytest.mark.parametrize("cols,zones", [(13, Z), (Basilisk.MATRIX_COLS, Basilisk.ZONES)])
def test_frames_have_cols_entries_in_range(name, cols, zones):
    f = make_effect(name, cols, zones, **PARAMS[name])
    for t in (0.0, 0.7, 1.0, 3.0, 5.5, 123.4):
        frame = f(t)
        assert len(frame) == cols
        for px in frame:
            assert len(px) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in px)


def test_breathing_peaks_and_troughs():
    f = make_effect("breathing", 13, Z, color=(255, 0, 0), period=4.0)
    assert f(1.0)[0] == (255, 0, 0)
    assert f(3.0)[0] == (0, 0, 0)
    assert 0 < f(2.0)[0][0] < 255
    assert set(f(1.0)) == {(255, 0, 0)}


def test_color_cycle_moves_through_hues():
    f = make_effect("color_cycle", 11, Basilisk.ZONES, period=8.0)
    assert f(0.0)[0] == (255, 0, 0)
    assert f(8.0)[0] == (255, 0, 0)
    assert f(8 / 3)[0][1] > 250  # a third of the way round is green


def test_strip_gradient_blends_colours_along_strip():
    f = make_effect("strip_gradient", 11, Basilisk.ZONES, colors=[(255, 0, 0), (0, 0, 255)])
    frame = f(0.0)
    assert frame[0] == (0, 0, 0) and frame[1] == (0, 0, 0)  # outside the strip
    assert frame[2] != frame[6] != frame[10]
    assert f(3.0) != f(0.0)


def test_zones_static_assigns_by_zone():
    f = make_effect("zones_static", 13, Z, zone_colors={"logo": (1, 2, 3), "strip": (9, 8, 7)})
    frame = f(0)
    assert frame[0] == (1, 2, 3)
    assert frame[1] == (0, 0, 0)  # unlisted zone is off
    assert all(px == (9, 8, 7) for px in frame[2:])
    assert f(99) == frame


def test_match_keyboard_hue():
    assert make_effect("match_keyboard", 13, Z, hue=0, sat=255)(0)[0] == (255, 0, 0)
    r, g, b = make_effect("match_keyboard", 13, Z, hue=85, sat=255)(0)[0]
    assert g > r and g > b
    assert make_effect("match_keyboard", 13, Z, hue=0, sat=0)(0)[0] == (255, 255, 255)


def test_unknown_effect_raises():
    with pytest.raises(ValueError):
        make_effect("nope", 13, Z)
