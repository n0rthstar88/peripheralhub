import pytest

from peripheralhub.wd75.macros import (
    Delay, Down, MacroBufferFull, Raw, Tap, Text, Up,
    decode_buffer, encode_buffer, encoded_size,
)

EMPTY = [[]] * 15


def test_empty_buffer_is_16_empty_macros():
    assert decode_buffer(bytes(1048), 16) == [[]] * 16


def test_text_and_actions_roundtrip():
    m = [[Text("hi"), Tap(0x0028), Delay(100), Down(0x00E1), Tap(0x0004), Up(0x00E1)]] + EMPTY
    assert decode_buffer(encode_buffer(m, 1048), 16) == m


def test_delay_encoding():
    assert encode_buffer([[Delay(100)]] + EMPTY, 1048).startswith(b"\x01\x04100|\x00")


def test_8bit_tap_encoding():
    assert encode_buffer([[Tap(0x28)]] + EMPTY, 1048).startswith(b"\x01\x01\x28\x00")


def test_16bit_keycode_tap_roundtrips():
    m = [[Tap(0x5221), Down(0x5222), Up(0x5222)]] + EMPTY
    buf = encode_buffer(m, 1048)
    assert buf.startswith(b"\x01\x05\x21\x52\x01\x06\x22\x52\x01\x07\x22\x52\x00")
    assert decode_buffer(buf, 16) == m


def test_unknown_bytes_preserved_as_raw():
    buf = b"ab\x01\x09\x41\x42\x00\x01\x04xx|\x00\x80\x00" + bytes(100)
    macros = decode_buffer(buf, 3)
    assert macros[0] == [Text("ab"), Raw(b"\x01\x09\x41\x42")]
    assert macros[1] == [Raw(b"\x01\x04xx|")]
    assert macros[2] == [Raw(b"\x80")]
    assert encode_buffer(macros, len(buf)) == buf[: len(buf)]


def test_overflow_raises():
    with pytest.raises(MacroBufferFull):
        encode_buffer([[Text("x" * 1048)]] + EMPTY, 1048)


def test_encoded_size_counts_terminators():
    assert encoded_size([[Text("hi")], []]) == 3 + 1
