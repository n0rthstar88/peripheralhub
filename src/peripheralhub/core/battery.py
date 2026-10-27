from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from peripheralhub.core.settings import Settings
from peripheralhub.wd75.device import Connection

UPOWER = "org.freedesktop.UPower"
UPOWER_PATH = "/org/freedesktop/UPower"
DEVICE_IFACE = "org.freedesktop.UPower.Device"
MODEL_PREFIX = "Womier WD75"
_MAC = re.compile(r"(?:[0-9A-Fa-f]{2}[:_-]){5}[0-9A-Fa-f]{2}")


@dataclass(frozen=True)
class BatteryReading:
    level: int | None
    charging: bool | None
    live: bool
    measured_at: float


def battery_color(level: int) -> str:
    if level > 40:
        return "green"
    if level >= 20:
        return "amber"
    return "red"


def age_text(seconds: float) -> str:
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


class UPowerBus(Protocol):
    def enumerate_devices(self) -> list[str]: ...
    def get_properties(self, path: str) -> dict[str, Any]: ...


class _DBusUPower:
    def __init__(self) -> None:
        import dbus

        self._dbus = dbus
        self._bus = dbus.SystemBus()

    def _iface(self, path: str, iface: str):
        obj = self._bus.get_object(UPOWER, path)
        return self._dbus.Interface(obj, iface)

    def enumerate_devices(self) -> list[str]:
        return [str(p) for p in self._iface(UPOWER_PATH, UPOWER).EnumerateDevices()]

    def get_properties(self, path: str) -> dict[str, Any]:
        props = self._iface(path, "org.freedesktop.DBus.Properties")
        return dict(props.GetAll(DEVICE_IFACE))


def _is_keyboard(path: str, props: dict[str, Any]) -> bool:
    model = str(props.get("Model", ""))
    if model.startswith(MODEL_PREFIX):
        return True
    # BlueZ-style identity (MAC in native path/serial) only counts with a WD75-looking model
    ident = f"{props.get('NativePath', '')} {props.get('Serial', '')} {path}"
    return bool(_MAC.search(ident)) and "WD75" in model


def read_upower_keyboard(bus: UPowerBus | None = None, now: float | None = None) -> BatteryReading | None:
    """Live WD75 battery from UPower (only present while it is on Bluetooth)."""
    import time

    try:
        bus = bus or _DBusUPower()
        for path in bus.enumerate_devices():
            props = bus.get_properties(path)
            if not _is_keyboard(path, props):
                continue
            if props.get("IsPresent") is not True:
                return None
            if "Percentage" not in props:
                return None
            t = time.time() if now is None else now
            return BatteryReading(int(round(float(props["Percentage"]))), None, True, t)
    except Exception:  # D-Bus missing/unavailable: treat as "no live reading"
        return None
    return None


def keyboard_battery(
    live: BatteryReading | None, connection: Connection, settings: Settings, now: float
) -> BatteryReading:
    if live is not None and live.level is not None:
        settings.set("battery.wd75", {"level": live.level, "at": live.measured_at})
        return live
    stored = settings.get("battery.wd75")
    if not stored:
        return BatteryReading(None, None, False, now)
    charging = True if connection is Connection.USB else None
    return BatteryReading(int(stored["level"]), charging, False, float(stored["at"]))
