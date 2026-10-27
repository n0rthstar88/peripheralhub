import functools
import operator

import pytest

from peripheralhub.basilisk import protocol as p


def test_report_layout_and_crc():
    r = p.build_report(0x04, 0x05, 0x07, bytes([1, 0x06, 0x40, 0x06, 0x40, 0, 0]))
    assert len(r) == 90 and r[1] == 0x1F and r[5] == 0x07 and r[6] == 0x04 and r[7] == 0x05
    assert r[88] == functools.reduce(operator.xor, r[2:88]) and r[89] == 0


def test_set_dpi_args():
    assert p.set_dpi(1600, 1600)[8:15] == bytes([1, 0x06, 0x40, 0x06, 0x40, 0, 0])


def test_poll_mapping():
    assert p.set_poll(500)[8] == 0x02
    assert p.set_poll(1000)[8] == 0x01 and p.set_poll(125)[8] == 0x08
    with pytest.raises(ValueError):
        p.set_poll(250)


def test_stages_encoding():
    r = p.set_dpi_stages([400, 800], active=2)
    assert r[5] == 0x26 and r[6:8] == bytes([0x04, 0x06])
    assert r[8 : 8 + 3 + 14] == bytes([1, 2, 2, 1, 0x01, 0x90, 0x01, 0x90, 0, 0, 2, 0x03, 0x20, 0x03, 0x20, 0, 0])


def test_getters_class_id_size():
    for rep, (c, i, s) in [
        (p.get_dpi(), (0x04, 0x85, 7)),
        (p.get_dpi_stages(), (0x04, 0x86, 0x26)),
        (p.get_poll(), (0x00, 0x85, 1)),
        (p.get_brightness(), (0x0F, 0x84, 3)),
    ]:
        assert (rep[6], rep[7], rep[5]) == (c, i, s)


def test_brightness_args():
    assert p.set_brightness(50)[8:11] == bytes([1, 0, 50])


def test_effect_layouts_match_openrazer():
    assert p.effect_none()[5:12] == bytes([6, 0x0F, 0x02, 1, 0, 0, 0])
    s = p.effect_static(1, 2, 3)
    assert s[5] == 9 and s[8:17] == bytes([1, 0, 1, 0, 0, 1, 1, 2, 3])
    b = p.effect_breathing(4, 5, 6)
    assert b[5] == 9 and b[8:17] == bytes([1, 0, 2, 1, 0, 1, 4, 5, 6])
    assert p.effect_spectrum()[5] == 6 and p.effect_spectrum()[8:11] == bytes([1, 0, 3])
    w = p.effect_wave(1)
    assert w[5] == 6 and w[8:13] == bytes([1, 0, 4, 1, 0x28])
    r = p.effect_reactive(2, 7, 8, 9)
    assert r[5] == 9 and r[8:17] == bytes([1, 0, 5, 0, 2, 1, 7, 8, 9])
    assert p.effect_reactive(9, 0, 0, 0)[12] == 4  # speed clamped


def test_custom_frame_and_effect_custom():
    f = p.custom_frame(0, 0, [(1, 2, 3), (4, 5, 6)])
    assert f[6:8] == bytes([0x0F, 0x03]) and f[5] == 0x47
    assert f[8:10] == b"\x00\x00" and f[10:13] == bytes([0, 0, 1]) and f[13:19] == bytes([1, 2, 3, 4, 5, 6])
    e = p.effect_custom()
    assert e[5] == 0x0C and e[6:8] == bytes([0x0F, 0x02]) and e[8:11] == bytes([0, 0, 8])


def test_parse_report_status():
    raw = bytearray(p.build_report(0x04, 0x85, 7, b""))
    raw[0] = p.OK
    raw[9:11] = b"\x06\x40"
    rep = p.parse_report(bytes(raw))
    assert (rep.status, rep.cmd_class, rep.cmd_id) == (p.OK, 0x04, 0x85)
    assert rep.args[1:3] == b"\x06\x40" and len(rep.args) == 80
    assert p.parse_report(bytes([p.UNSUPPORTED]) + bytes(89)).status == p.UNSUPPORTED
