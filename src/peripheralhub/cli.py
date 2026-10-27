"""phub: command-line access to PeripheralHub (status, batteries, keyboard snapshot/restore, mouse DPI)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from peripheralhub.basilisk.device import Basilisk, RazerError
from peripheralhub.core.battery import BatteryReading, age_text
from peripheralhub.core.registry import BACKUP_DIR, DeviceStatus, Registry
from peripheralhub.core.settings import DEFAULT_PATH, Settings
from peripheralhub.wd75.device import Wd75, Wd75Probe, Wd75State
from peripheralhub.wd75.snapshot import factory_snapshot, save_snapshot
from peripheralhub.wd75.via import ViaError

DPI_MIN, DPI_MAX = 100, 26000
_STATE_TEXT = {
    "disconnected": "not connected",
    "no_permission": "no permission (run install.sh --udev-only)",
    "asleep": "asleep",
    "ready": "connected",
    "connected": "connected",
    "bluetooth_only": "connected",
}


def battery_text(r: BatteryReading | None, now: float) -> str:
    if r is None or r.level is None:
        return "charging" if r is not None and r.charging else ""
    text = f"{r.level}%"
    if r.charging:
        text += " charging"
    if not r.live:
        text += f" · {age_text(max(0.0, now - r.measured_at))}"
    return text


def _status_line(s: DeviceStatus, now: float) -> str:
    where = s.connection if s.connection and s.state != "disconnected" else _STATE_TEXT.get(s.state, s.state)
    return f"{s.title:<16}{where:<14}{battery_text(s.battery, now)}".rstrip()


def _registry() -> Registry:
    settings = Settings(DEFAULT_PATH)
    return Registry(settings, wd75=Wd75Probe(str(Path(BACKUP_DIR).expanduser())))


def _polled(registry) -> list[DeviceStatus]:
    registry.poll_devices()
    registry.poll_batteries()
    return [s for s in registry.statuses() if s.id != "displays"]


def cmd_status(registry) -> int:
    now = time.time()
    for s in _polled(registry):
        print(_status_line(s, now))
    return 0


def cmd_battery(registry) -> int:
    now = time.time()
    for s in _polled(registry):
        if s.battery is not None:
            print(f"{s.title:<16}{battery_text(s.battery, now) or 'no reading yet'}")
    return 0


def _ready_wd75(wd75) -> int:
    state = wd75.refresh()
    if state != Wd75State.READY:
        print(f"Keyboard not available over VIA ({state.value}); connect it by cable or dongle and press a key.",
              file=sys.stderr)
        return 1
    return 0


def cmd_snapshot(wd75, out: str) -> int:
    if rc := _ready_wd75(wd75):
        return rc
    save_snapshot(wd75.take_snapshot(), out)
    print(f"Saved {out}")
    return 0


def cmd_restore_factory(wd75, layer: int | None, yes: bool) -> int:
    if not yes:
        print("This rewrites keyboard keys to factory defaults. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    if rc := _ready_wd75(wd75):
        return rc
    scope = {} if layer is None else {"layers": [layer]}
    n = wd75.restore(factory_snapshot(), **scope)
    backup = wd75.ensure_backup()
    print(f"Restored {n} keys to factory defaults. Backup: {backup}")
    return 0


def cmd_mouse_dpi(basilisk, value: int | None) -> int:
    if value is not None and not DPI_MIN <= value <= DPI_MAX:
        print(f"DPI must be {DPI_MIN}-{DPI_MAX}", file=sys.stderr)
        return 2
    if not basilisk.open():
        print("Basilisk V3 not connected", file=sys.stderr)
        return 1
    try:
        if value is None:
            x, y = basilisk.dpi()
            print(x if x == y else f"{x}x{y}")
        else:
            basilisk.set_dpi(value)
            Settings(DEFAULT_PATH).set("mouse.dpi", value)
            print(f"DPI set to {value}")
    finally:
        basilisk.close()
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="phub", description="PeripheralHub command line")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="devices, connection and battery")
    sub.add_parser("battery", help="battery levels")
    snap = sub.add_parser("snapshot", help="save the keyboard keymap/lighting/macros to a JSON file")
    snap.add_argument("out")
    rf = sub.add_parser("restore-factory", help="restore factory keymap (all layers or one)")
    rf.add_argument("--layer", type=int, choices=range(5), metavar="N")
    rf.add_argument("--yes", action="store_true")
    mouse = sub.add_parser("mouse", help="mouse settings")
    msub = mouse.add_subparsers(dest="mouse_cmd", required=True)
    dpi = msub.add_parser("dpi", help="show or set DPI")
    dpi.add_argument("value", nargs="?", type=int)
    return ap


def main(argv: list[str] | None = None, *, registry=None, wd75=None, basilisk=None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.cmd == "status":
            return cmd_status(registry or _registry())
        if args.cmd == "battery":
            return cmd_battery(registry or _registry())
        if args.cmd in ("snapshot", "restore-factory"):
            wd75 = wd75 or Wd75(str(Path(BACKUP_DIR).expanduser()))
            if args.cmd == "snapshot":
                return cmd_snapshot(wd75, args.out)
            return cmd_restore_factory(wd75, args.layer, args.yes)
        return cmd_mouse_dpi(basilisk or Basilisk(), args.value)
    except PermissionError as e:
        print(f"No permission: {e}. Run install.sh --udev-only.", file=sys.stderr)
    except (ViaError, RazerError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
    return 1
