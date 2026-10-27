#!/usr/bin/env python3
"""Find valid RGB effect ids by previewing 0..63 (VIA 0x07 only; never saves). Restores the original."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from peripheralhub.wd75.device import Wd75, Wd75State  # noqa: E402
from peripheralhub.wd75.via import ViaError  # noqa: E402

BACKUP_DIR = Path.home() / ".local/share/peripheralhub/backups"


def probe(wd: Wd75, delay: float = 0.1) -> tuple[int, list[int], bool, ViaError | None]:
    """All writes go through wd.apply_rgb, so the pre-write backup is taken first.
    Returns (original, valid ids, restore verified, error)."""
    wd.ensure_backup()
    original = wd.via.get_rgb().effect
    valid: list[int] = []
    error: ViaError | None = None
    try:
        for i in range(64):
            wd.apply_rgb(effect=i)
            time.sleep(delay)
            if wd.via.get_rgb().effect == i:
                valid.append(i)
    except ViaError as e:
        error = e
    finally:
        try:
            wd.apply_rgb(effect=original)
            time.sleep(delay)
            ok = wd.via.get_rgb().effect == original
        except ViaError:
            ok = False
    return original, valid, ok, error


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    wd = Wd75(backup_dir=str(BACKUP_DIR))
    state = wd.refresh()
    if state != Wd75State.READY:
        print(f"keyboard not ready: {state.value}")
        return 2
    original, valid, ok, error = probe(wd)
    print(f"original effect: {original}")
    if error:
        print(f"error: {error}")
    print(f"restored original effect {original}: {'verified' if ok else 'NOT VERIFIED'}")
    print(f"valid ids: {valid}")
    return 0 if error is None and ok else 1


if __name__ == "__main__":
    sys.exit(main())
