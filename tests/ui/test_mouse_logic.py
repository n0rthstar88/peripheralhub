import pytest

from peripheralhub.ui.pages.mouse_dpi import clamp_dpi, validate_stages


def test_clamp_dpi_bounds_and_step():
    assert clamp_dpi(30000) == 26000
    assert clamp_dpi(123) == 100
    assert clamp_dpi(1625) == 1650
    assert clamp_dpi(1624) == 1600
    assert clamp_dpi(6400) == 6400


def test_validate_stages_clamps_each():
    assert validate_stages([400, 99999, 10]) == [400, 26000, 100]


def test_validate_stages_rejects_bad_counts():
    with pytest.raises(ValueError):
        validate_stages([])
    with pytest.raises(ValueError):
        validate_stages([400] * 6)


def test_effect_params_per_effect():
    from peripheralhub.ui.pages.mouse_lighting import effect_params

    v = {"color": (1, 2, 3), "color2": (4, 5, 6), "period": 5.0,
         "logo": (7, 7, 7), "wheel": (8, 8, 8), "strip": (9, 9, 9)}
    assert effect_params("static", v, None) == {"color": [1, 2, 3]}
    assert effect_params("spectrum", v, None) == {}
    assert effect_params("breathing", v, None) == {"color": [1, 2, 3], "period": 5.0}
    assert effect_params("color_cycle", v, None) == {"period": 5.0}
    assert effect_params("strip_gradient", v, None) == {"colors": [[1, 2, 3], [4, 5, 6]], "period": 5.0}
    assert effect_params("zones_static", v, None)["zone_colors"] == {
        "logo": [7, 7, 7], "wheel": [8, 8, 8], "strip": [9, 9, 9]}
    assert effect_params("match_keyboard", v, {"hue": 85, "sat": 200}) == {"hue": 85, "sat": 200}
    assert effect_params("match_keyboard", v, None) == {"hue": 0, "sat": 255}
