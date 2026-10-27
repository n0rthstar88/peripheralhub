"""Low-battery desktop notifications (shared by the app and the background service)."""
from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.settings import Settings
from peripheralhub.core.systemd import service_active

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus

APP_ICON = "dev.hufflabs.PeripheralHub"
DEFAULT_THRESHOLD = 20
REARM_MARGIN = 5


def notify_send(summary: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", "-a", "PeripheralHub", "-i", APP_ICON, summary, body],
                       timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


class LowBatteryNotifier:
    """Fires once per device when a live, non-charging level reaches the threshold.

    Re-arms when the level climbs REARM_MARGIN points above the threshold or the device starts charging.
    """

    def __init__(self, settings: Settings, send: Callable[[str, str], None] = notify_send) -> None:
        self._settings = settings
        self._send = send
        self._fired: set[str] = set()

    def threshold(self) -> int:
        try:
            return int(self._settings.get("battery.low_threshold", DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            return DEFAULT_THRESHOLD

    def check(self, device_id: str, title: str, r: BatteryReading | None) -> bool:
        if r is None or not r.live or r.level is None:
            return False
        limit = self.threshold()
        if r.charging or r.level >= limit + REARM_MARGIN:
            self._fired.discard(device_id)
            return False
        if r.level > limit or device_id in self._fired:
            return False
        self._fired.add(device_id)
        self._send(f"{title} battery low", f"{r.level}% left. Charge it soon.")
        return True


class AppBatteryWatch:
    """The app's side of low-battery notifications: stays quiet while the background service runs (it notifies)."""

    def __init__(self, notifier: LowBatteryNotifier, is_service_active: Callable[[], bool] = service_active,
                 clock: Callable[[], float] = time.monotonic, recheck: float = 60) -> None:
        self._notifier, self._is_active, self._clock, self._recheck = notifier, is_service_active, clock, recheck
        self._checked_at: float | None = None
        self._active = False

    def feed(self, statuses: Iterable[DeviceStatus]) -> None:
        now = self._clock()
        if self._checked_at is None or now - self._checked_at >= self._recheck:
            self._active, self._checked_at = self._is_active(), now
        if self._active:
            return
        for s in statuses:
            if s.battery is not None:
                self._notifier.check(s.id, s.title, s.battery)
