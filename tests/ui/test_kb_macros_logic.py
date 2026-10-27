from peripheralhub.ui.pages.kb_macros import (
    Recorder, describe, validate_delay, validate_text,
)
from peripheralhub.wd75.macros import Delay, Down, Raw, Tap, Text, Up


def test_validate_text():
    assert validate_text("hello\tworld\n~") is None
    assert "é" in validate_text("café")
    assert validate_text("a\x00b") is not None


def test_validate_delay():
    assert validate_delay("100") is None
    for bad in ("", "0", "-5", "1.5", "abc", " "):
        assert validate_delay(bad) is not None


def test_recorder_collapses_tap_and_inserts_delay():
    r = Recorder()
    r.event(0x04, True, 0)
    r.event(0x04, False, 20)
    r.event(0x05, True, 400)
    r.event(0x05, False, 460)
    assert r.finish(500) == [Tap(0x04), Delay(380), Down(0x05), Delay(60), Up(0x05)]


def test_recorder_hold_modifier_and_autorepeat():
    r = Recorder()
    r.event(0xE1, True, 0)
    r.event(0xE1, True, 10)  # auto-repeat ignored
    r.event(0x04, True, 30)
    r.event(0x04, False, 60)
    r.event(0xE1, False, 80)
    assert r.finish(80) == [Down(0xE1), Tap(0x04), Up(0xE1)]


def test_recorder_releases_still_held_keys():
    r = Recorder()
    r.event(0x04, True, 0)
    assert r.finish(10) == [Down(0x04), Up(0x04)]


def test_describe():
    assert describe(Text("hi")) == 'Type "hi"'
    assert describe(Tap(0x04)) == "Tap A"
    assert describe(Delay(50)) == "Wait 50 ms"
    assert describe(Raw(b"\x01")) == "Unknown step"
