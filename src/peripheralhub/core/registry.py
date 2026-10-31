"""Single source of truth for which devices exist, how they are connected and their battery."""
from __future__ import annotations

import sys
import threading
import time
import traceback
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from peripheralhub.basilisk.device import Basilisk
from peripheralhub.core.battery import BatteryReading, keyboard_battery, read_upower_keyboard
from peripheralhub.core.extensions import Peripheral
from peripheralhub.core.settings import Settings
from peripheralhub.headset.device import read_headset
from peripheralhub.wd75.device import Connection, Wd75

BACKUP_DIR = "~/.local/share/peripheralhub/backups"
EXTRA_BATTERY_WAIT_S = 6.0
_CONNECTION_TEXT = {Connection.USB: "USB", Connection.DONGLE: "2.4G", Connection.BLUETOOTH: "Bluetooth"}


@dataclass
class DeviceStatus:
    id: str
    title: str
    state: str
    connection: str | None
    battery: BatteryReading | None


class Registry:
    def __init__(
        self,
        settings: Settings,
        wd75: Wd75 | None = None,
        basilisk: Basilisk | None = None,
        headset_reader: Callable[[], BatteryReading | None] = read_headset,
        upower_reader: Callable[[], BatteryReading | None] = read_upower_keyboard,
        clock: Callable[[], float] = time.time,
        extras: Sequence[Peripheral] = (),
        hidden: Collection[str] = (),
    ) -> None:
        self._settings = settings
        self._wd75 = wd75 or Wd75(str(Path(BACKUP_DIR).expanduser()))
        self._basilisk = basilisk or Basilisk()
        self._headset_reader = headset_reader
        self._upower_reader = upower_reader
        self._clock = clock
        self.hidden = set(hidden)
        self.extras = [d for d in extras if d.id not in self.hidden]
        self._extra_states: dict[str, str] = {d.id: "disconnected" for d in self.extras}
        self._extra_batteries: dict[str, BatteryReading | None] = {}
        self._extra_threads: dict[str, threading.Thread] = {}
        self._extra_failed: set[str] = set()
        self._subscribers: list[Callable[[list[DeviceStatus]], None]] = []
        self._wd_state = "disconnected"
        self._wd_connection: Connection = Connection.DISCONNECTED
        self._wd_key: tuple | None = None
        self._mouse_state = "disconnected"
        self._kb_battery: BatteryReading | None = None
        self._last_live: BatteryReading | None = None
        self._headset_battery: BatteryReading | None = None
        self._statuses = self._build()

    def subscribe(self, callback: Callable[[list[DeviceStatus]], None]) -> None:
        self._subscribers.append(callback)

    def statuses(self) -> list[DeviceStatus]:
        return list(self._statuses)

    def _build(self) -> list[DeviceStatus]:
        headset = self._headset_battery
        builtin = [
            DeviceStatus("wd75", "WD75 V2", self._wd_state,
                         _CONNECTION_TEXT.get(self._wd_connection), self._kb_battery),
            DeviceStatus("basilisk", "Basilisk V3", self._mouse_state, None, None),
            DeviceStatus("headset", "Arctis Nova 7P",
                         "connected" if headset is not None else "disconnected", None, headset),
            DeviceStatus("displays", "Displays", "ready", None, None),
        ]
        return [s for s in builtin if s.id not in self.hidden] + [
            DeviceStatus(d.id, d.title, self._extra_states[d.id], None, self._extra_batteries.get(d.id))
            for d in self.extras
        ]

    def _update(self) -> None:
        new = self._build()
        if new == self._statuses:
            return
        self._statuses = new
        for cb in list(self._subscribers):
            cb(self.statuses())

    def _recompute_keyboard(self, live: BatteryReading | None) -> None:
        self._kb_battery = keyboard_battery(live, self._wd_connection, self._settings, self._clock())

    def _poll_keyboard(self, force: bool) -> None:
        """Probe cheaply; only a connection/node change (or force) triggers the heavy refresh()."""
        if "wd75" in self.hidden:
            return
        try:
            key = (self._wd75.probe(), self._wd75.node_path)
            if force or key != self._wd_key:
                if self._wd75.busy:
                    return  # a write is in flight: retry on the next poll
                self._wd_state = self._wd75.refresh().value
                self._wd_key = key
            self._wd_connection = self._wd75.connection
        except Exception:
            self._wd_state, self._wd_connection, self._wd_key = "disconnected", Connection.DISCONNECTED, None

    def poll_devices(self) -> list[DeviceStatus]:
        previous = self._wd_connection
        self._poll_keyboard(force=False)
        self._after_keyboard(previous)
        return self.statuses()

    def refresh_keyboard(self) -> list[DeviceStatus]:
        """Explicit re-check (e.g. a page's Retry button): opens the VIA node and queries it."""
        previous = self._wd_connection
        self._poll_keyboard(force=True)
        self._after_keyboard(previous)
        return self.statuses()

    def _after_keyboard(self, previous: Connection) -> None:
        if self._kb_battery is None or self._wd_connection != previous:
            live = self._last_live if self._wd_connection is Connection.BLUETOOTH else None
            self._recompute_keyboard(live)
        self._poll_basilisk()
        self._poll_extras()
        self._update()

    def _extra_failure(self, d: Peripheral, what: str) -> None:
        """Log a failing device once, not on every poll."""
        if d.id not in self._extra_failed:
            self._extra_failed.add(d.id)
            print(f"peripheralhub: {d.id} {what} failed", file=sys.stderr)
            traceback.print_exc()

    def _poll_extras(self) -> None:
        for d in self.extras:
            try:
                self._extra_states[d.id] = d.poll()
            except Exception:
                self._extra_states[d.id] = "disconnected"
                self._extra_failure(d, "poll")

    def _read_extra_battery(self, d: Peripheral) -> None:
        try:
            reading = d.read_battery()
            self._extra_batteries[d.id] = reading if isinstance(reading, BatteryReading) else None
        except Exception:
            self._extra_batteries[d.id] = None
            self._extra_failure(d, "battery read")

    def _poll_extra_batteries(self) -> None:
        """Read all at once on daemon threads, so a slow or stuck device can't hold up the app for long."""
        started = []
        for d in self.extras:
            running = self._extra_threads.get(d.id)
            if running is not None and running.is_alive():
                continue  # still stuck from last time: don't pile up threads
            thread = threading.Thread(target=self._read_extra_battery, args=(d,), daemon=True)
            self._extra_threads[d.id] = thread
            thread.start()
            started.append(thread)
        deadline = time.monotonic() + EXTRA_BATTERY_WAIT_S
        for thread in started:
            thread.join(max(0.0, deadline - time.monotonic()))
        self._poll_extras()

    def _poll_basilisk(self) -> None:
        if "basilisk" in self.hidden:
            return
        if self._basilisk.state == "ready":
            try:
                if self._basilisk.present():
                    self._mouse_state = "ready"
                    return
                self._basilisk.close()
            except Exception:
                pass
        try:
            self._basilisk.open()
        except Exception:  # PermissionError sets basilisk.state itself
            pass
        self._mouse_state = self._basilisk.state if self._basilisk.state in (
            "disconnected", "no_permission", "ready") else "disconnected"

    def poll_batteries(self) -> None:
        if "wd75" not in self.hidden:
            try:
                live = self._upower_reader()
            except Exception:
                live = None
            self._last_live = live
            self._recompute_keyboard(live)
        if "headset" not in self.hidden:
            try:
                self._headset_battery = self._headset_reader()
            except Exception:
                self._headset_battery = None
        self._poll_extra_batteries()
        self._update()
