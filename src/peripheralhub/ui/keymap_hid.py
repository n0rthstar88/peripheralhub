"""Linux input event codes (evdev) to USB HID keyboard usages, for the macro recorder."""
from __future__ import annotations

_PAIRS: dict[int, int] = {
    1: 0x29, 12: 0x2D, 13: 0x2E, 14: 0x2A, 15: 0x2B, 26: 0x2F, 27: 0x30, 28: 0x28,
    29: 0xE0, 39: 0x33, 40: 0x34, 41: 0x35, 42: 0xE1, 43: 0x31, 51: 0x36, 52: 0x37,
    53: 0x38, 54: 0xE5, 55: 0x55, 56: 0xE2, 57: 0x2C, 58: 0x39, 69: 0x53, 70: 0x47,
    74: 0x56, 78: 0x57, 83: 0x63, 86: 0x64, 87: 0x44, 88: 0x45, 96: 0x58, 97: 0xE4,
    98: 0x54, 99: 0x46, 100: 0xE6, 102: 0x4A, 103: 0x52, 104: 0x4B, 105: 0x50,
    106: 0x4F, 107: 0x4D, 108: 0x51, 109: 0x4E, 110: 0x49, 111: 0x4C, 119: 0x48,
    125: 0xE3, 126: 0xE7, 127: 0x65,
}
_RUNS: tuple[tuple[int, int, int], ...] = (  # (first evdev, count, first HID)
    (2, 10, 0x1E),   # 1..0
    (59, 10, 0x3A),  # F1..F10
    (71, 3, 0x5F),   # keypad 7 8 9
    (75, 3, 0x5C),   # keypad 4 5 6
    (79, 3, 0x59),   # keypad 1 2 3
    (82, 1, 0x62),   # keypad 0
)
_LETTERS = {16: "QWERTYUIOP", 30: "ASDFGHJKL", 44: "ZXCVBNM"}


def _build() -> dict[int, int]:
    table = dict(_PAIRS)
    for first, count, hid in _RUNS:
        for i in range(count):
            table[first + i] = hid + i
    for first, letters in _LETTERS.items():
        for i, ch in enumerate(letters):
            table[first + i] = 0x04 + ord(ch) - ord("A")
    return table


_TABLE = _build()


def evdev_to_hid(evdev_code: int) -> int | None:
    return _TABLE.get(evdev_code)
