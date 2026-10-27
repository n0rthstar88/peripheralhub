#!/usr/bin/env python3
"""Light one custom-frame column at a time on the Basilisk V3 to map LED columns.

usage: basilisk_led_map.py            interactive: Enter = next column, q = quit
       basilisk_led_map.py COLUMN     light only that column (0-based), hold 5 s
Restores the spectrum effect on exit.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peripheralhub.basilisk.device import Basilisk  # noqa: E402


def frame(col: int, n: int) -> list[tuple[int, int, int]]:
    return [(255, 255, 255) if i == col else (0, 0, 0) for i in range(n)]


def main() -> int:
    mouse = Basilisk()
    if not mouse.open():
        print("Basilisk not found")
        return 1
    n = mouse.MATRIX_COLS
    try:
        if len(sys.argv) > 1:
            col = int(sys.argv[1])
            mouse.send_frame(frame(col, n))
            print(f"column {col} lit")
            time.sleep(5)
        else:
            for col in range(n):
                mouse.send_frame(frame(col, n))
                if input(f"column {col}/{n - 1} lit; Enter = next, q = quit: ").strip().lower() == "q":
                    break
    finally:
        mouse.apply_effect("spectrum")
        mouse.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
