"""Single source of truth for which devices exist, how they are connected and their battery."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from peripheralhub.basilisk.device import Basilisk
from peripheralhub.core.battery import BatteryReading, keyboard_battery, read_upower_keyboard
from peripheralhub.core.settings import Settings
from peripheralhub.headset.device import read_headset
from peripheralhub.wd75.device import Connection, Wd75

BACKUP_DIR = "~/.local/share/peripheralhub/backups"
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
    ) -> None:
        self._settings = settings
        self._wd75 = wd75 or Wd75(str(Path(BACKUP_DIR).expanduser()))
        self._basilisk = basilisk or Basilisk()
        self._headset_reader = headset_reader
        self._upower_reader = upower_reader
        self._clock = clock
        self._subscribers: list[Callable[[list[DeviceStatus]], None]] = []
        self._wd_state = "disconnected"
        self._wd_connection: Connection = Connection.DISCONNECTED
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
        return [
            DeviceStatus("wd75", "WD75 V2", self._wd_state,
                         _CONNECTION_TEXT.get(self._wd_connection), self._kb_battery),
            DeviceStatus("basilisk", "Basilisk V3", self._mouse_state, None, None),
            DeviceStatus("headset", "Arctis Nova 7P",
                         "connected" if headset is not None else "disconnected", None, headset),
            DeviceStatus("displays", "Displays", "ready", None, None),
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

    def poll_devices(self) -> list[DeviceStatus]:
        previous = self._wd_connection
        try:
            self._wd_state = self._wd75.refresh().value
            self._wd_connection = self._wd75.connection
        except Exception:
            self._wd_state, self._wd_connection = "disconnected", Connection.DISCONNECTED
        if self._kb_battery is None or self._wd_connection != previous:
            live = self._last_live if self._wd_connection is Connection.BLUETOOTH else None
            self._recompute_keyboard(live)
        self._poll_basilisk()
        self._update()
        return self.statuses()

    def _poll_basilisk(self) -> None:
        if self._basilisk.state == "ready":
            self._mouse_state = "ready"
            return
        try:
            self._basilisk.open()
        except Exception:  # PermissionError sets basilisk.state itself
            pass
        self._mouse_state = self._basilisk.state if self._basilisk.state in (
            "disconnected", "no_permission", "ready") else "disconnected"

    def poll_batteries(self) -> None:
        try:
            live = self._upower_reader()
        except Exception:
            live = None
        self._last_live = live
        self._recompute_keyboard(live)
        try:
            self._headset_battery = self._headset_reader()
        except Exception:
            self._headset_battery = None
        self._update()
