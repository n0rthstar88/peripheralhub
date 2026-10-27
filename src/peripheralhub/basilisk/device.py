"""Razer Basilisk V3 over hidraw (USB interface 3)."""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

from peripheralhub.basilisk import protocol as p
from peripheralhub.core.hidraw import HidrawDevice, HidrawNode, find_nodes

VID, PID, INTERFACE = 0x1532, 0x0099, 3
MAX_ATTEMPTS = 3


class RazerError(Exception):
    pass


_STATUS_NAMES = {p.FAIL: "FAIL", p.TIMEOUT: "TIMEOUT", p.UNSUPPORTED: "UNSUPPORTED", p.BUSY: "BUSY"}


def transact(hid, report: bytes, sleep: Callable[[float], None] = time.sleep) -> p.Report:
    """Send one 90-byte report and return the parsed reply."""
    lock = getattr(hid, "locked", contextlib.nullcontext)
    try:
        with lock():
            for _ in range(MAX_ATTEMPTS):
                hid.set_feature(0, report)
                sleep(0.0006)
                reply = p.parse_report(hid.get_feature(0, p.REPORT_LEN))
                if reply.status != p.BUSY:
                    break
    except OSError as e:
        raise RazerError(f"I/O error: {e}") from e
    if reply.status != p.OK:
        name = _STATUS_NAMES.get(reply.status, f"{reply.status:#04x}")
        raise RazerError(f"{name} for class {report[6]:#04x} id {report[7]:#04x}")
    return reply


class Basilisk:
    # Hardware-verified OK: off, static, spectrum, wave. "breathing" and "reactive" are accepted by
    # apply_effect but the firmware answers UNSUPPORTED (status 0x05), so they are not listed here.
    EFFECTS = ("off", "static", "spectrum", "wave")
    # OpenRazer: RazerBasiliskV3.MATRIX_DIMS = [1, 11]
    MATRIX_COLS = 11
    # Provisional (OpenRazer names three LEDs: logo, scroll wheel, backlight/strip); not yet mapped on hardware.
    ZONES: dict[str, range] = {"logo": range(0, 1), "wheel": range(1, 2), "strip": range(2, 11)}

    def __init__(
        self,
        node_lister: Callable[[], list[HidrawNode]] | None = None,
        opener: Callable[[str], HidrawDevice] = HidrawDevice,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._list = node_lister or (lambda: find_nodes(VID, PID, interface=INTERFACE))
        self._open = opener
        self._sleep = sleep
        self._hid = None
        self._path: str | None = None
        self.state = "disconnected"

    def open(self) -> bool:
        self.close()
        nodes = self._list()
        if not nodes:
            self.state = "disconnected"
            return False
        try:
            self._hid = self._open(nodes[0].path)
            self._path = nodes[0].path
        except PermissionError:
            self.state = "no_permission"
            raise
        self.state = "ready"
        return True

    def present(self) -> bool:
        """True while the opened node is still listed (no device I/O)."""
        try:
            return self._hid is not None and any(n.path == self._path for n in self._list())
        except OSError:
            return False

    def close(self) -> None:
        if self._hid is not None:
            self._hid.close()
            self._hid = None
        self.state = "disconnected"

    def _tx(self, report: bytes) -> p.Report:
        if self._hid is None:
            raise RazerError("device not open")
        try:
            return transact(self._hid, report, self._sleep)
        except RazerError as e:
            if "I/O error" in str(e):
                self.close()
            raise

    def dpi(self) -> tuple[int, int]:
        a = self._tx(p.get_dpi()).args
        return (a[1] << 8 | a[2], a[3] << 8 | a[4])

    def set_dpi(self, x: int, y: int | None = None) -> None:
        self._tx(p.set_dpi(x, x if y is None else y))

    def stages(self) -> tuple[list[int], int]:
        a = self._tx(p.get_dpi_stages()).args
        active, count = a[1], a[2]
        return [a[3 + 7 * i + 1] << 8 | a[3 + 7 * i + 2] for i in range(count)], active

    def set_stages(self, values: list[int], active: int) -> None:
        if not 1 <= len(values) <= 5 or not 1 <= active <= len(values):
            raise ValueError("1-5 stages and a 1-based active stage are required")
        self._tx(p.set_dpi_stages(values, active))

    def poll(self) -> int:
        return p.poll_from_code(self._tx(p.get_poll()).args[0])

    def set_poll(self, hz: int) -> None:
        self._tx(p.set_poll(hz))

    def brightness(self) -> int:
        return self._tx(p.get_brightness(p.SCROLL_LED)).args[2]

    def set_brightness(self, v: int) -> None:
        self._tx(p.set_brightness(max(0, min(255, v))))

    def apply_effect(self, name: str, **params) -> None:
        r, g, b = params.get("color", (0, 0, 0))
        builders = {
            "off": p.effect_none,
            "static": lambda: p.effect_static(r, g, b),
            "breathing": lambda: p.effect_breathing(r, g, b),
            "spectrum": p.effect_spectrum,
            "wave": lambda: p.effect_wave(params.get("direction", 1)),
            "reactive": lambda: p.effect_reactive(params.get("speed", 2), r, g, b),
        }
        if name not in builders:
            raise ValueError(f"unknown effect {name!r}")
        self._tx(builders[name]())

    def send_frame(self, colors: list[tuple[int, int, int]]) -> None:
        if len(colors) != self.MATRIX_COLS:
            raise ValueError(f"frame needs {self.MATRIX_COLS} colours")
        self._tx(p.custom_frame(0, 0, colors))
        self._tx(p.effect_custom())
