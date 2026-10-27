"""VIA macro buffer codec.

Macros are NUL-terminated and stored back to back. Printable ASCII (plus newline and
tab) is typed as-is; 0x01 starts an action: 01/02/03 = tap/down/up with a 1-byte
keycode, 04 = delay (ASCII milliseconds then '|'), 05/06/07 = tap/down/up with a
16-bit little-endian keycode (used for keycodes above 0xFF). Anything else is kept
verbatim as Raw so saving never corrupts it.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

PREFIX = 0x01
_TAP, _DOWN, _UP, _DELAY = 1, 2, 3, 4
_TAP16, _DOWN16, _UP16 = 5, 6, 7


class MacroBufferFull(Exception):
    """The macros don't fit in the keyboard's macro buffer."""


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Tap:
    keycode: int


@dataclass(frozen=True)
class Down:
    keycode: int


@dataclass(frozen=True)
class Up:
    keycode: int


@dataclass(frozen=True)
class Delay:
    ms: int


@dataclass(frozen=True)
class Raw:
    data: bytes


Step = Text | Tap | Down | Up | Delay | Raw

_KINDS = {_TAP: Tap, _DOWN: Down, _UP: Up}
_KINDS16 = {_TAP16: Tap, _DOWN16: Down, _UP16: Up}


def _typeable(b: int) -> bool:
    return 0x20 <= b <= 0x7E or b in (0x0A, 0x09)


def decode_buffer(buf: bytes, count: int) -> list[list[Step]]:
    macros: list[list[Step]] = []
    i, n = 0, len(buf)
    for _ in range(count):
        steps: list[Step] = []
        text = bytearray()

        def flush() -> None:
            if text:
                steps.append(Text(text.decode("ascii")))
                text.clear()

        while i < n and buf[i] != 0:
            b = buf[i]
            if b != PREFIX:
                if _typeable(b):
                    text.append(b)
                else:
                    flush()
                    steps.append(Raw(bytes([b])))
                i += 1
                continue
            flush()
            action = buf[i + 1] if i + 1 < n else None
            if action in _KINDS and i + 2 < n and buf[i + 2] != 0:
                steps.append(_KINDS[action](buf[i + 2]))
                i += 3
                continue
            if action in _KINDS16 and i + 3 < n and buf[i + 2] != 0 and buf[i + 3] != 0:
                steps.append(_KINDS16[action](buf[i + 2] | buf[i + 3] << 8))
                i += 4
                continue
            if action == _DELAY:
                end = buf.find(b"|", i + 2)
                digits = buf[i + 2:end] if end >= 0 else b""
                if end >= 0 and digits.isdigit() and b"\x00" not in digits:
                    steps.append(Delay(int(digits)))
                    i = end + 1
                    continue
            # Unknown or malformed action: keep the rest of this macro verbatim.
            end = buf.find(b"\x00", i)
            end = n if end < 0 else end
            steps.append(Raw(bytes(buf[i:end])))
            i = end
        flush()
        macros.append(steps)
        i += 1  # skip the NUL terminator
    return macros


def _encode_macro(macro: Sequence[Step]) -> bytes:
    out = bytearray()
    for s in macro:
        if isinstance(s, Text):
            out += bytes(c for c in s.text.encode("ascii", "ignore") if _typeable(c))
        elif isinstance(s, (Tap, Down, Up)):
            base = {Tap: _TAP, Down: _DOWN, Up: _UP}[type(s)]
            kc = s.keycode
            if 0 < kc <= 0xFF:
                out += bytes([PREFIX, base, kc])
            elif 0xFF < kc <= 0xFFFF and kc & 0xFF and kc >> 8:
                out += bytes([PREFIX, base + 4, kc & 0xFF, kc >> 8])
            else:
                raise ValueError(f"keycode {kc:#06x} cannot be stored in a macro")
        elif isinstance(s, Delay):
            out += bytes([PREFIX, _DELAY]) + str(s.ms).encode() + b"|"
        elif isinstance(s, Raw):
            out += s.data
    out.append(0)
    return bytes(out)


def encoded_size(macros: Sequence[Sequence[Step]]) -> int:
    return sum(len(_encode_macro(m)) for m in macros)


def encode_buffer(macros: Sequence[Sequence[Step]], size: int) -> bytes:
    data = b"".join(_encode_macro(m) for m in macros)
    if len(data) > size:
        raise MacroBufferFull(f"macros need {len(data)} bytes, buffer holds {size}")
    return data + bytes(size - len(data))
