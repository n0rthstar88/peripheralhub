#!/usr/bin/env python3
"""Find valid RGB effect ids by previewing 0..63 (VIA 0x07 only; never saves). Restores the original."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peripheralhub.wd75.device import Wd75, Wd75State  # noqa: E402
from peripheralhub.wd75.via import ViaError  # noqa: E402


def main() -> int:
    wd = Wd75(backup_dir="/nonexistent-unused")
    state = wd.refresh()
    if state != Wd75State.READY:
        print(f"keyboard not ready: {state.value}")
        return 2
    via = wd.via
    original = via.get_rgb().effect
    print(f"original effect: {original}")
    valid: list[int] = []
    error: Exception | None = None
    try:
        for i in range(64):
            via.set_effect(i)
            time.sleep(0.1)
            if via.get_rgb().effect == i:
                valid.append(i)
    except ViaError as e:
        error = e
        print(f"error: {e}")
    finally:
        try:
            via.set_effect(original)
            time.sleep(0.1)
            ok = via.get_rgb().effect == original
        except ViaError as e:
            ok = False
            print(f"restore failed: {e}")
        print(f"restored original effect {original}: {'verified' if ok else 'NOT VERIFIED'}")
    print(f"valid ids: {valid}")
    return 0 if error is None and ok else 1


if __name__ == "__main__":
    sys.exit(main())
