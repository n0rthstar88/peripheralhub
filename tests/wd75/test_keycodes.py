import json
from pathlib import Path

from peripheralhub.wd75.keycodes import CATALOG, CATEGORIES, is_dangerous, label, layer_target, search

NAMES = ["Windows", "Windows Fn", "Mac", "Mac Fn", "Layer 4"]


def test_basic_labels():
    assert label(0x0004) == "A" and label(0x0029) == "Esc" and label(0x00E1) == "LShift"
    assert label(0x0001) == "▽" and label(0x0000) == ""


def test_layer_keys():
    assert label(0x5221) == "MO(1)"
    assert label(0x5221, NAMES) == "Fn → Windows Fn"
    assert label(0x5262, NAMES) == "Toggle → Mac"
    assert label(0x4104, NAMES) == "LT(Windows Fn, A)"
    assert label(0x4104) == "LT(1, A)"
    assert layer_target(0x5223) == 3 and layer_target(0x4104) == 1
    assert layer_target(0x0004) is None


def test_mods_and_tap():
    assert label(0x0204) == "LShift+A"
    assert label(0x2104) == "MT(LCtrl, A)"


def test_womier_customs():
    assert label(0x7E00) == "Battery Query" and label(0x7E04) == "2.4GHz"
    assert label(0x7E0F) == "Heart Toggle" and label(0x7E10) == "Heart Hue"
    assert label(0x7E11) == "Womier 0x7E11 (unknown)"


def test_special_and_danger():
    assert label(0x7C03) == "Clear EEPROM" and is_dangerous(0x7C03) and is_dangerous(0x7C00)
    assert not is_dangerous(0x0004)


def test_unknown_code_renders_hex():
    assert label(0x6ABC) == "0x6ABC"


def test_search_finds_by_name_and_label():
    assert any(k.code == 0x7E0F for k in search("heart"))


def test_catalog_unique_and_categories_valid():
    assert len({k.code for k in CATALOG}) == len(CATALOG)
    assert {k.category for k in CATALOG} <= set(CATEGORIES)


def test_every_snapshot_keycode_has_non_hex_label():
    snap = json.loads((Path(__file__).parents[1] / "data" / "factory-snapshot.json").read_text())
    codes = {int(c, 16) for layer in snap["keymap"] for row in layer for c in row}
    for code in codes - {0x7E11}:
        assert "0x" not in label(code), hex(code)
