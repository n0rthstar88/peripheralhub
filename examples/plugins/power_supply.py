"""Example plugin: show a battery the kernel reports under /sys/class/power_supply.

Copy to ~/.config/peripheralhub/plugins/ and set NAME to a folder that exists there.
"""
from pathlib import Path

from peripheralhub.plugin import Peripheral, battery_reading

NAME = "BAT0"


class PowerSupply(Peripheral):
    id = "power-supply"
    title = "System Battery"
    icon = "battery-symbolic"
    hint = f"{NAME} not found"
    has_battery = True

    def __init__(self) -> None:
        self._path = Path("/sys/class/power_supply") / NAME

    def poll(self) -> str:
        return "connected" if self._path.exists() else "disconnected"

    def read_battery(self):
        if not self._path.exists():
            return None
        level = int((self._path / "capacity").read_text())
        status = (self._path / "status").read_text().strip()
        return battery_reading(level, status == "Charging")


def register(api) -> None:
    api.add_device(PowerSupply())
