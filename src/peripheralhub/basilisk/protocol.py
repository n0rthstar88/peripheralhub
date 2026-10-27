"""Razer 90-byte feature-report protocol (Basilisk V3, hidraw interface 3).

Layouts follow OpenRazer, fetched 2026-10-27 at commit
477f4d6d3ab7e9deb6310d5bd3742560c5cbe80d (master HEAD):
  https://raw.githubusercontent.com/openrazer/openrazer/master/driver/razerchromacommon.c
  https://raw.githubusercontent.com/openrazer/openrazer/master/driver/razermouse_driver.c
  https://raw.githubusercontent.com/openrazer/openrazer/master/daemon/openrazer_daemon/hardware/mouse.py
OpenRazer's RazerBasiliskV3 (0x1532:0x0099): MATRIX_DIMS = [1, 11], DPI_MAX = 26000.
"""
from __future__ import annotations

import functools
import operator
from dataclasses import dataclass

TRANSACTION_ID = 0x1F
VARSTORE = 0x01
NOSTORE = 0x00
ZERO_LED = 0x00
SCROLL_LED = 0x01  # the all-LED (ZERO_LED) brightness getter FAILs on the Basilisk V3; per-LED reads work
LOGO_LED = 0x04

OK = 0x02
BUSY = 0x01
FAIL = 0x03
TIMEOUT = 0x04
UNSUPPORTED = 0x05

REPORT_LEN = 90
ARG_LEN = 80

_POLL = {1000: 0x01, 500: 0x02, 125: 0x08}
_FX_NONE, _FX_STATIC, _FX_BREATHING, _FX_SPECTRUM, _FX_WAVE, _FX_REACTIVE, _FX_CUSTOM = 0, 1, 2, 3, 4, 5, 8


@dataclass(frozen=True)
class Report:
    status: int
    cmd_class: int
    cmd_id: int
    args: bytes


def build_report(cmd_class: int, cmd_id: int, data_size: int, args: bytes = b"", transaction_id: int = TRANSACTION_ID) -> bytes:
    if len(args) > ARG_LEN:
        raise ValueError("too many argument bytes")
    buf = bytearray(REPORT_LEN)
    buf[1] = transaction_id
    buf[5] = data_size
    buf[6] = cmd_class
    buf[7] = cmd_id
    buf[8 : 8 + len(args)] = args
    buf[88] = functools.reduce(operator.xor, buf[2:88])
    return bytes(buf)


def parse_report(buf: bytes) -> Report:
    if len(buf) < REPORT_LEN:
        raise ValueError(f"short report ({len(buf)} bytes)")
    return Report(buf[0], buf[6], buf[7], bytes(buf[8 : 8 + ARG_LEN]))


def get_dpi() -> bytes:
    return build_report(0x04, 0x85, 7, bytes([VARSTORE]))


def set_dpi(x: int, y: int, store: int = VARSTORE) -> bytes:
    return build_report(0x04, 0x05, 7, bytes([store, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0, 0]))


def get_dpi_stages() -> bytes:
    return build_report(0x04, 0x86, 0x26, bytes([VARSTORE]))


def set_dpi_stages(stages: list[int], active: int) -> bytes:
    args = bytearray([VARSTORE, active, len(stages)])
    for i, dpi in enumerate(stages):
        args += bytes([i + 1, dpi >> 8, dpi & 0xFF, dpi >> 8, dpi & 0xFF, 0, 0])
    return build_report(0x04, 0x06, 0x26, bytes(args))


def get_poll() -> bytes:
    return build_report(0x00, 0x85, 1)


def set_poll(hz: int) -> bytes:
    if hz not in _POLL:
        raise ValueError(f"unsupported polling rate {hz}")
    return build_report(0x00, 0x05, 1, bytes([_POLL[hz]]))


def poll_from_code(code: int) -> int:
    for hz, c in _POLL.items():
        if c == code:
            return hz
    raise ValueError(f"unknown polling code {code:#x}")


def get_brightness(led: int = ZERO_LED) -> bytes:
    return build_report(0x0F, 0x84, 3, bytes([VARSTORE, led]))


def set_brightness(v: int, led: int = ZERO_LED) -> bytes:
    return build_report(0x0F, 0x04, 3, bytes([VARSTORE, led, v]))


def _effect(size: int, effect_id: int, extra: dict[int, int] | None = None) -> bytes:
    args = bytearray(size)
    args[0], args[1], args[2] = VARSTORE, ZERO_LED, effect_id
    for i, v in (extra or {}).items():
        args[i] = v
    return build_report(0x0F, 0x02, size, bytes(args))


def effect_none() -> bytes:
    return _effect(6, _FX_NONE)


def effect_static(r: int, g: int, b: int) -> bytes:
    return _effect(9, _FX_STATIC, {5: 1, 6: r, 7: g, 8: b})


def effect_breathing(r: int, g: int, b: int) -> bytes:
    return _effect(9, _FX_BREATHING, {3: 1, 5: 1, 6: r, 7: g, 8: b})


def effect_spectrum() -> bytes:
    return _effect(6, _FX_SPECTRUM)


def effect_wave(direction: int) -> bytes:
    return _effect(6, _FX_WAVE, {3: max(0, min(2, direction)), 4: 0x28})


def effect_reactive(speed: int, r: int, g: int, b: int) -> bytes:
    return _effect(9, _FX_REACTIVE, {4: max(1, min(4, speed)), 5: 1, 6: r, 7: g, 8: b})


def custom_frame(row: int, start: int, colors: list[tuple[int, int, int]]) -> bytes:
    args = bytearray([0, 0, row, start, start + len(colors) - 1])
    for r, g, b in colors:
        args += bytes([r, g, b])
    return build_report(0x0F, 0x03, 0x47, bytes(args))


def effect_custom() -> bytes:
    args = bytearray(0x0C)
    args[0], args[1], args[2] = NOSTORE, ZERO_LED, _FX_CUSTOM
    return build_report(0x0F, 0x02, 0x0C, bytes(args))
