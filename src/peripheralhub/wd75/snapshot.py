"""Keyboard state snapshots (backup format) and restore planning."""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from os import PathLike

from .via import RgbState, ViaClient


@dataclass
class Snapshot:
    layers: int
    rows: int
    cols: int
    keymap: list[list[list[int]]]
    macro_buffer: bytes
    rgb: RgbState
    taken: str


def read_snapshot(via: ViaClient, rows: int = 6, cols: int = 16) -> Snapshot:
    layers = via.layer_count()
    return Snapshot(
        layers=layers, rows=rows, cols=cols,
        keymap=via.read_keymap(layers, rows, cols),
        macro_buffer=via.read_macro_buffer(),
        rgb=via.get_rgb(),
        taken=datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
    )


def _from_dict(d: dict) -> Snapshot:
    rgb = d["rgb_matrix"]
    return Snapshot(
        layers=d["layers"], rows=d["matrix"]["rows"], cols=d["matrix"]["cols"],
        keymap=[[[int(v, 16) for v in row] for row in layer] for layer in d["keymap"]],
        macro_buffer=bytes.fromhex(d["macro_buffer_hex"]),
        rgb=RgbState(rgb["brightness"][0], rgb["effect"][0], rgb["speed"][0],
                     rgb["color_hs"][0], rgb["color_hs"][1]),
        taken=d["taken"],
    )


def load_snapshot(path: str | PathLike) -> Snapshot:
    with open(path) as f:
        return _from_dict(json.load(f))


def save_snapshot(s: Snapshot, path: str | PathLike) -> None:
    d = {
        "taken": s.taken,
        "device": ["HID_ID=0003:00008888:00002222"],
        "via_protocol": 12,
        "matrix": {"rows": s.rows, "cols": s.cols},
        "layers": s.layers,
        "keymap": [[[f"0x{v:04X}" for v in row] for row in layer] for layer in s.keymap],
        "macro_count": 16,
        "macro_buffer_size": len(s.macro_buffer),
        "macro_buffer_hex": s.macro_buffer.hex(),
        "rgb_matrix": {
            "brightness": [s.rgb.brightness, 0],
            "effect": [s.rgb.effect, 0],
            "speed": [s.rgb.speed, 0],
            "color_hs": [s.rgb.hue, s.rgb.saturation],
        },
    }
    with open(path, "w") as f:
        json.dump(d, f, indent=1)


def factory_snapshot() -> Snapshot:
    text = resources.files("peripheralhub.wd75").joinpath("data/factory-snapshot.json").read_text()
    return _from_dict(json.loads(text))


def restore_plan(
    current: Snapshot,
    target: Snapshot,
    *,
    layers: Sequence[int] | None = None,
    keys: Sequence[tuple[int, int, int]] | None = None,
) -> list[tuple[int, int, int, int]]:
    """(layer, row, col, code) for keys that differ, optionally scoped."""
    layer_set = None if layers is None else set(layers)
    key_set = None if keys is None else set(keys)
    plan = []
    for l in range(min(current.layers, target.layers)):
        if layer_set is not None and l not in layer_set:
            continue
        for r in range(target.rows):
            for c in range(target.cols):
                if key_set is not None and (l, r, c) not in key_set:
                    continue
                want = target.keymap[l][r][c]
                if current.keymap[l][r][c] != want:
                    plan.append((l, r, c, want))
    return plan
