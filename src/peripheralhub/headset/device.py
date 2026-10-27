from __future__ import annotations

import json
import subprocess
import time

from peripheralhub.core.battery import BatteryReading


def parse_headsetcontrol(json_text: str, now: float | None = None) -> BatteryReading | None:
    try:
        devices = json.loads(json_text).get("devices") or []
    except (ValueError, AttributeError):
        return None
    for dev in devices:
        battery = dev.get("battery") or {}
        status = battery.get("status")
        level = battery.get("level")
        if status in ("BATTERY_AVAILABLE", "BATTERY_CHARGING") and isinstance(level, int):
            t = time.time() if now is None else now
            return BatteryReading(level, status == "BATTERY_CHARGING", True, t)
    return None


def read_headset(run=subprocess.run) -> BatteryReading | None:
    try:
        proc = run(
            ["headsetcontrol", "-b", "-o", "json"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_headsetcontrol(proc.stdout)
