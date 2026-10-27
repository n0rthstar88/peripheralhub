"""Key geometry parsed from the VIA (KLE) layout JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Key:
    row: int
    col: int
    x: float
    y: float
    w: float
    h: float


def load_layout(path: str | None = None) -> list[Key]:
    if path is None:
        text = resources.files("peripheralhub.wd75").joinpath("data/WD75_V2.json").read_text()
    else:
        with open(path) as f:
            text = f.read()
    rows = json.loads(text)["layouts"]["keymap"]
    keys: list[Key] = []
    y = 0.0
    for line in rows:
        x = 0.0
        w = h = 1.0
        dx = dy = 0.0
        for item in line:
            if isinstance(item, dict):
                w = item.get("w", w)
                h = item.get("h", h)
                dx += item.get("x", 0.0)
                dy += item.get("y", 0.0)
                continue
            y_ = y + dy
            x += dx
            r, c = item.split("\n")[0].split(",")
            keys.append(Key(int(r), int(c), x, y_, w, h))
            x += w
            w = h = 1.0
            dx = 0.0
            if dy:
                y += dy
                dy = 0.0
        y += 1
    return keys
