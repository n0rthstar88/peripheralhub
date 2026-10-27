"""WD75 connection detection, reachability state, and safe (backed-up) writes."""
from __future__ import annotations

import functools
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from peripheralhub.core.hidraw import BUS_BLUETOOTH, BUS_USB, HidrawNode, list_nodes

from .snapshot import Snapshot, read_snapshot, restore_plan, save_snapshot
from .via import HidrawTransport, ViaClient, ViaError, ViaTimeout

VID, PID = 0x8888, 0x2222
VIA_DESCRIPTOR_PREFIX = b"\x06\x60\xff\x09\x61"
NAME_CABLE = "Womier WD75"
NAME_DONGLE = "Womier WD75 2.4G"


class Connection(Enum):
    DISCONNECTED = "disconnected"
    USB = "usb"
    DONGLE = "dongle"
    BLUETOOTH = "bluetooth"


class Wd75State(Enum):
    DISCONNECTED = "disconnected"
    NO_PERMISSION = "no_permission"
    ASLEEP = "asleep"
    READY = "ready"
    BLUETOOTH_ONLY = "bluetooth_only"


def detect_connection(nodes: list[HidrawNode]) -> tuple[Connection, HidrawNode | None]:
    """Return the connection mode and the VIA node (None for Bluetooth/disconnected). USB beats dongle."""
    mine = [n for n in nodes if n.vid == VID and n.pid == PID]
    via_nodes = [n for n in mine if n.bus == BUS_USB and n.descriptor.startswith(VIA_DESCRIPTOR_PREFIX)]
    # Linux reports HID_NAME as "<vendor> <product>", e.g. "Womier Womier WD75 2.4G".
    for name, conn in ((NAME_CABLE, Connection.USB), (NAME_DONGLE, Connection.DONGLE)):
        for n in via_nodes:
            if n.name.endswith(name) and (conn == Connection.DONGLE or not n.name.endswith(NAME_DONGLE)):
                return conn, n
    if any(n.bus == BUS_BLUETOOTH for n in mine):
        return Connection.BLUETOOTH, None
    return Connection.DISCONNECTED, None


def _writing(fn):
    """Mark the device busy for the duration of a write so refresh() leaves the transport alone."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self._busy_lock:
            self._busy += 1
        try:
            return fn(self, *a, **kw)
        finally:
            with self._busy_lock:
                self._busy -= 1
    return wrapper


class Wd75:
    def __init__(self, backup_dir: str, transport_factory=HidrawTransport, node_lister=list_nodes) -> None:
        self._backup_dir = Path(backup_dir)
        self._factory = transport_factory
        self._list = node_lister
        self._transport = None
        self._backup_path: str | None = None
        self.connection = Connection.DISCONNECTED
        self.via: ViaClient | None = None
        self.state = Wd75State.DISCONNECTED
        self._busy = 0
        self._busy_lock = threading.Lock()
        self.node_path: str | None = None

    def _drop_transport(self) -> None:
        close = getattr(self._transport, "close", None)
        if close:
            close()
        self._transport = None
        self.via = None

    @property
    def busy(self) -> bool:
        return self._busy > 0

    def probe(self) -> Connection:
        """Cheap presence check: lists hidraw nodes, opens nothing, sends no VIA."""
        self.connection, node = detect_connection(self._list())
        self.node_path = node.path if node else None
        return self.connection

    def refresh(self) -> Wd75State:
        if self.busy:
            return self.state
        self.state = self._refresh()
        return self.state

    def _refresh(self) -> Wd75State:
        self._drop_transport()
        self.connection, node = detect_connection(self._list())
        if self.connection == Connection.DISCONNECTED:
            return Wd75State.DISCONNECTED
        if node is None:
            return Wd75State.BLUETOOTH_ONLY
        try:
            transport = self._factory(node.path)
        except PermissionError:
            return Wd75State.NO_PERMISSION
        except OSError:
            return Wd75State.DISCONNECTED
        via = ViaClient(transport)
        try:
            via.protocol_version()
        except ViaTimeout:
            getattr(transport, "close", lambda: None)()
            return Wd75State.ASLEEP
        except ViaError:
            getattr(transport, "close", lambda: None)()
            return Wd75State.DISCONNECTED
        self._transport, self.via = transport, via
        return Wd75State.READY

    def _require_via(self) -> ViaClient:
        if self.via is None:
            raise ViaError("keyboard is not connected")
        return self.via

    def take_snapshot(self) -> Snapshot:
        return read_snapshot(self._require_via())

    def ensure_backup(self) -> str | None:
        """Write the pre-write backup once per instance; returns its path."""
        if self._backup_path is None:
            snap = self.take_snapshot()
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = self._backup_dir / f"wd75-{stamp}.json"
            n = 1
            while path.exists():
                n += 1
                path = self._backup_dir / f"wd75-{stamp}-{n}.json"
            save_snapshot(snap, path)  # atomic: tmp + os.replace
            self._backup_path = str(path)
        return self._backup_path

    @_writing
    def write_keycode(self, layer: int, row: int, col: int, code: int) -> None:
        self.ensure_backup()
        self._require_via().set_keycode(layer, row, col, code)

    @_writing
    def apply_rgb(self, **changes: int) -> None:
        """Preview RGB changes (VIA 0x07 only, not saved to the keyboard)."""
        unknown = set(changes) - {"brightness", "effect", "speed", "hue", "saturation"}
        if unknown:
            raise TypeError(f"unknown rgb setting(s): {sorted(unknown)}")
        self.ensure_backup()
        via = self._require_via()
        if "brightness" in changes:
            via.set_brightness(changes["brightness"])
        if "effect" in changes:
            via.set_effect(changes["effect"])
        if "speed" in changes:
            via.set_speed(changes["speed"])
        if "hue" in changes or "saturation" in changes:
            cur = via.get_rgb()
            via.set_color(changes.get("hue", cur.hue), changes.get("saturation", cur.saturation))

    @_writing
    def save_rgb(self) -> None:
        self.ensure_backup()
        self._require_via().save_rgb()

    @_writing
    def write_macros(self, buf: bytes) -> None:
        self.ensure_backup()
        self._require_via().write_macro_buffer(buf)

    @_writing
    def reset_keymap(self) -> None:
        """Erase the keymap to firmware defaults (VIA 0x06). Backs up first."""
        self.ensure_backup()
        self._require_via().reset_keymap()

    @_writing
    def restore(self, target: Snapshot, **scope) -> int:
        """Write back keys that differ from target (scope: layers=, keys=). Returns keys written."""
        self.ensure_backup()
        via = self._require_via()
        plan = restore_plan(self.take_snapshot(), target, **scope)
        for layer, row, col, code in plan:
            via.set_keycode(layer, row, col, code)
        return len(plan)
