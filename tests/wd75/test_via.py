import json
from pathlib import Path

import pytest
from fake_via import FakeKeyboard

from peripheralhub.core.hidraw import HidrawDevice
from peripheralhub.wd75.via import (
    ALLOWED_COMMANDS, CommandNotAllowed, HidrawTransport, RgbState, ViaClient, ViaError, ViaTimeout,
    ViaUnhandled,
)

SNAPSHOT = json.loads((Path(__file__).parent.parent / "data" / "factory-snapshot.json").read_text())


def seeded_keyboard() -> FakeKeyboard:
    kb = FakeKeyboard()
    for l, layer in enumerate(SNAPSHOT["keymap"]):
        for r, row in enumerate(layer):
            for c, code in enumerate(row):
                kb.keymap[(l, r, c)] = int(code, 16)
    return kb


def test_allowlist_exact():
    assert ALLOWED_COMMANDS == frozenset(
        [0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0C, 0x0D, 0x0E, 0x0F, 0x11, 0x12])


@pytest.mark.parametrize("cmd", [0x0A, 0x0B, 0x16, 0xFE, 0xFF])
def test_disallowed_command_never_reaches_transport(cmd):
    kb = FakeKeyboard()
    via = ViaClient(kb)
    with pytest.raises(CommandNotAllowed):
        via.send(bytes([cmd]))
    assert kb.sent == []


def test_protocol_version_and_counts():
    via = ViaClient(FakeKeyboard())
    assert via.protocol_version() == 12
    assert via.layer_count() == 5
    assert via.macro_count() == 16
    assert via.macro_buffer_size() == 1048


def test_read_keymap_bulk_matches_per_key():
    kb = seeded_keyboard()
    via = ViaClient(kb)
    keymap = via.read_keymap(5, 6, 16)
    assert keymap[0][5][9] == 0x5221
    assert keymap == [[[int(c, 16) for c in row] for row in layer] for layer in SNAPSHOT["keymap"]]
    assert via.get_keycode(0, 5, 9) == 0x5221


def test_set_keycode_reads_back():
    kb = FakeKeyboard()
    ViaClient(kb).set_keycode(0, 2, 1, 0x0004)
    assert kb.keymap[(0, 2, 1)] == 0x0004
    assert [p[0] for p in kb.sent] == [0x05, 0x04]


def test_set_keycode_mismatch_raises():
    kb = FakeKeyboard()
    orig = kb.exchange
    kb.exchange = lambda p: bytes([0x04, 0, 0, 0, 0, 0x99]) + bytes(26) if p[0] == 0x04 else orig(p)
    with pytest.raises(ViaError):
        ViaClient(kb).set_keycode(0, 2, 1, 0x0004)


def test_reset_keymap_sends_0x06():
    kb = FakeKeyboard()
    ViaClient(kb).reset_keymap()
    assert kb.sent[0][0] == 0x06


def test_rgb_get_set_save():
    kb = FakeKeyboard()
    via = ViaClient(kb)
    assert via.get_rgb() == RgbState(191, 4, 0, 0, 255)
    via.set_effect(7)
    assert kb.sent[-1][:4] == bytes([0x07, 0x03, 0x02, 0x07])
    via.set_brightness(10)
    via.set_speed(3)
    via.set_color(20, 30)
    assert via.get_rgb() == RgbState(10, 7, 3, 20, 30)
    via.save_rgb()
    assert kb.sent[-1][:2] == bytes([0x09, 0x03])


def test_macro_buffer_roundtrip_in_28_byte_chunks():
    kb = FakeKeyboard()
    via = ViaClient(kb)
    data = bytes(i % 251 for i in range(1048))
    via.write_macro_buffer(data)
    assert bytes(kb.macro) == data
    assert via.read_macro_buffer() == data
    writes = [p for p in kb.sent if p[0] == 0x0F]
    assert writes and all(p[3] <= 28 for p in writes)


def test_write_macro_buffer_rejects_oversize():
    with pytest.raises(ViaError):
        ViaClient(FakeKeyboard()).write_macro_buffer(bytes(1049))


def test_timeout_raises_via_timeout():
    kb = FakeKeyboard()

    def boom(packet):
        kb.sent.append(packet)
        raise ViaTimeout("no reply")

    kb.exchange = boom
    with pytest.raises(ViaTimeout):
        ViaClient(kb).protocol_version()
    assert len(kb.sent) == 1


def test_oserror_becomes_via_error(tmp_path):
    path = tmp_path / "node"
    path.write_bytes(b"")
    t = HidrawTransport(str(path))
    t.close()
    with pytest.raises(ViaError):
        ViaClient(t).protocol_version()


def test_hidraw_transport_prefixes_report_id_and_times_out():
    class Dev:
        written = None

        def write(self, data):
            self.written = data

        def read(self, timeout, size=64):
            return None

    t = HidrawTransport.__new__(HidrawTransport)
    t._dev, t._timeout = Dev(), 0.1
    with pytest.raises(ViaTimeout):
        t.exchange(bytes([1]) + bytes(31))
    assert t._dev.written == b"\x00\x01" + bytes(31)


def test_unhandled_reply_raises():
    kb = FakeKeyboard()
    kb.exchange = lambda p: bytes([0xFF]) + bytes(31)
    with pytest.raises(ViaUnhandled):
        ViaClient(kb).protocol_version()


def test_wrong_reply_command_raises_via_error():
    kb = FakeKeyboard()
    kb.exchange = lambda p: bytes([0x42]) + bytes(31)
    with pytest.raises(ViaError):
        ViaClient(kb).protocol_version()
