from peripheralhub.ui.keymap_hid import evdev_to_hid


def test_known_keys():
    assert evdev_to_hid(30) == 0x04
    assert evdev_to_hid(28) == 0x28
    assert evdev_to_hid(42) == 0xE1
    assert evdev_to_hid(57) == 0x2C
    assert evdev_to_hid(103) == 0x52


def test_unknown_is_none():
    assert evdev_to_hid(0) is None
    assert evdev_to_hid(9999) is None
