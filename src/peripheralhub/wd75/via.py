"""QMK VIA client over raw HID with a hard command allowlist."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from peripheralhub.core.hidraw import HidrawDevice

PACKET_SIZE = 32
CHUNK = 28

ALLOWED_COMMANDS: frozenset[int] = frozenset(
    [0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0C, 0x0D, 0x0E, 0x0F, 0x11, 0x12]
)

CMD_PROTOCOL_VERSION = 0x01
CMD_GET_KEYCODE = 0x04
CMD_SET_KEYCODE = 0x05
CMD_RESET_KEYMAP = 0x06
CMD_SET_VALUE = 0x07
CMD_GET_VALUE = 0x08
CMD_SAVE_VALUE = 0x09
CMD_MACRO_COUNT = 0x0C
CMD_MACRO_SIZE = 0x0D
CMD_MACRO_READ = 0x0E
CMD_MACRO_WRITE = 0x0F
CMD_LAYER_COUNT = 0x11
CMD_KEYMAP_READ = 0x12

CHANNEL_RGB = 0x03
RGB_BRIGHTNESS, RGB_EFFECT, RGB_SPEED, RGB_COLOR = 1, 2, 3, 4


class ViaError(Exception):
    pass


class ViaTimeout(ViaError):
    pass


class CommandNotAllowed(ViaError):
    pass


class ViaUnhandled(ViaError):
    pass


class Transport(Protocol):
    def exchange(self, packet: bytes) -> bytes:
        """Send a 32-byte packet, return the 32-byte reply. Raises ViaTimeout."""


class HidrawTransport:
    def __init__(self, path: str, timeout: float = 1.0) -> None:
        self._dev = HidrawDevice(path)
        self._timeout = timeout

    def exchange(self, packet: bytes) -> bytes:
        try:
            self._dev.write(b"\x00" + packet)
            reply = self._dev.read(self._timeout, 64)
        except OSError as e:
            raise ViaError(f"hidraw I/O failed: {e}") from e
        if reply is None:
            raise ViaTimeout("keyboard did not reply")
        if len(reply) < PACKET_SIZE:
            raise ViaError(f"short reply ({len(reply)} bytes)")
        return reply[:PACKET_SIZE]

    def close(self) -> None:
        self._dev.close()


@dataclass(frozen=True)
class RgbState:
    brightness: int
    effect: int
    speed: int
    hue: int
    saturation: int


class ViaClient:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def send(self, payload: bytes) -> bytes:
        """Allowlist-check, pad to 32 bytes, exchange, and validate the reply."""
        if not payload or payload[0] not in ALLOWED_COMMANDS:
            raise CommandNotAllowed(f"VIA command {payload[:1].hex() or '<empty>'} is not allowed")
        if len(payload) > PACKET_SIZE:
            raise ViaError("payload longer than 32 bytes")
        reply = self._t.exchange(bytes(payload).ljust(PACKET_SIZE, b"\x00"))
        if reply[0] == 0xFF:
            raise ViaUnhandled(f"keyboard does not handle command {payload[0]:#04x}")
        if reply[0] != payload[0]:
            raise ViaError(f"unexpected reply {reply[0]:#04x} to command {payload[0]:#04x}")
        return reply

    def protocol_version(self) -> int:
        return int.from_bytes(self.send(bytes([CMD_PROTOCOL_VERSION]))[1:3], "big")

    def layer_count(self) -> int:
        return self.send(bytes([CMD_LAYER_COUNT]))[1]

    def get_keycode(self, layer: int, row: int, col: int) -> int:
        return int.from_bytes(self.send(bytes([CMD_GET_KEYCODE, layer, row, col]))[4:6], "big")

    def set_keycode(self, layer: int, row: int, col: int, code: int) -> None:
        self.send(bytes([CMD_SET_KEYCODE, layer, row, col]) + code.to_bytes(2, "big"))
        got = self.get_keycode(layer, row, col)
        if got != code:
            raise ViaError(f"keycode read-back mismatch: wrote {code:#06x}, read {got:#06x}")

    def _read_buffer(self, cmd: int, total: int) -> bytes:
        out = bytearray()
        for off in range(0, total, CHUNK):
            n = min(CHUNK, total - off)
            reply = self.send(bytes([cmd]) + off.to_bytes(2, "big") + bytes([n]))
            out += reply[4:4 + n]
        return bytes(out)

    def read_keymap(self, layers: int, rows: int, cols: int) -> list[list[list[int]]]:
        raw = self._read_buffer(CMD_KEYMAP_READ, layers * rows * cols * 2)
        return [
            [
                [int.from_bytes(raw[((l * rows + r) * cols + c) * 2:][:2], "big") for c in range(cols)]
                for r in range(rows)
            ]
            for l in range(layers)
        ]

    def reset_keymap(self) -> None:
        self.send(bytes([CMD_RESET_KEYMAP]))

    def _get_rgb_value(self, value_id: int) -> bytes:
        return self.send(bytes([CMD_GET_VALUE, CHANNEL_RGB, value_id]))[3:5]

    def _set_rgb_value(self, value_id: int, *values: int) -> None:
        self.send(bytes([CMD_SET_VALUE, CHANNEL_RGB, value_id, *values]))

    def get_rgb(self) -> RgbState:
        color = self._get_rgb_value(RGB_COLOR)
        return RgbState(
            brightness=self._get_rgb_value(RGB_BRIGHTNESS)[0],
            effect=self._get_rgb_value(RGB_EFFECT)[0],
            speed=self._get_rgb_value(RGB_SPEED)[0],
            hue=color[0],
            saturation=color[1],
        )

    def set_brightness(self, v: int) -> None:
        self._set_rgb_value(RGB_BRIGHTNESS, v)

    def set_effect(self, v: int) -> None:
        self._set_rgb_value(RGB_EFFECT, v)

    def set_speed(self, v: int) -> None:
        self._set_rgb_value(RGB_SPEED, v)

    def set_color(self, hue: int, sat: int) -> None:
        self._set_rgb_value(RGB_COLOR, hue, sat)

    def save_rgb(self) -> None:
        self.send(bytes([CMD_SAVE_VALUE, CHANNEL_RGB]))

    def macro_count(self) -> int:
        return self.send(bytes([CMD_MACRO_COUNT]))[1]

    def macro_buffer_size(self) -> int:
        return int.from_bytes(self.send(bytes([CMD_MACRO_SIZE]))[1:3], "big")

    def read_macro_buffer(self) -> bytes:
        return self._read_buffer(CMD_MACRO_READ, self.macro_buffer_size())

    def write_macro_buffer(self, data: bytes) -> None:
        if len(data) > self.macro_buffer_size():
            raise ViaError("macro data larger than the device buffer")
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            self.send(bytes([CMD_MACRO_WRITE]) + off.to_bytes(2, "big") + bytes([len(chunk)]) + chunk)
