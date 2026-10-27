"""In-memory VIA keyboard implementing the Transport protocol, shared by wd75 tests."""
from __future__ import annotations

PACKET = 32


class FakeKeyboard:
    def __init__(self, layers: int = 5, rows: int = 6, cols: int = 16) -> None:
        self.layers, self.rows, self.cols = layers, rows, cols
        self.keymap: dict[tuple[int, int, int], int] = {
            (l, r, c): 0 for l in range(layers) for r in range(rows) for c in range(cols)
        }
        self.rgb: dict[int, list[int]] = {1: [191, 0], 2: [4, 0], 3: [0, 0], 4: [0, 255]}
        self.macro = bytearray(1048)
        self.macro_count = 16
        self.sent: list[bytes] = []

    def _flat(self) -> bytearray:
        out = bytearray()
        for l in range(self.layers):
            for r in range(self.rows):
                for c in range(self.cols):
                    out += self.keymap[(l, r, c)].to_bytes(2, "big")
        return out

    def exchange(self, packet: bytes) -> bytes:
        assert len(packet) == PACKET
        self.sent.append(bytes(packet))
        p = bytearray(packet)
        cmd = p[0]
        if cmd == 0x01:
            p[1:3] = (12).to_bytes(2, "big")
        elif cmd == 0x11:
            p[1] = self.layers
        elif cmd == 0x0C:
            p[1] = self.macro_count
        elif cmd == 0x0D:
            p[1:3] = len(self.macro).to_bytes(2, "big")
        elif cmd == 0x04:
            p[4:6] = self.keymap[(p[1], p[2], p[3])].to_bytes(2, "big")
        elif cmd == 0x05:
            self.keymap[(p[1], p[2], p[3])] = int.from_bytes(p[4:6], "big")
        elif cmd == 0x06:
            self.keymap = {k: 0 for k in self.keymap}
        elif cmd == 0x12:
            off, n = int.from_bytes(p[1:3], "big"), p[3]
            p[4:4 + n] = self._flat()[off:off + n]
        elif cmd == 0x0E:
            off, n = int.from_bytes(p[1:3], "big"), p[3]
            p[4:4 + n] = self.macro[off:off + n]
        elif cmd == 0x0F:
            off, n = int.from_bytes(p[1:3], "big"), p[3]
            self.macro[off:off + n] = p[4:4 + n]
        elif cmd == 0x08 and p[1] == 0x03:
            p[3:5] = bytes(self.rgb[p[2]])
        elif cmd == 0x07 and p[1] == 0x03:
            self.rgb[p[2]] = list(p[3:5]) if p[2] == 4 else [p[3], 0]
        elif cmd == 0x09:
            pass
        else:
            p[0] = 0xFF
        return bytes(p)
