"""Background service: re-applies saved mouse settings, animates host mouse effects, warns on low battery."""
from __future__ import annotations

import signal
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from peripheralhub.basilisk.device import Basilisk
from peripheralhub.basilisk.effects import make_effect
from peripheralhub.core.notify import LowBatteryNotifier
from peripheralhub.core.registry import BACKUP_DIR, Registry
from peripheralhub.core.settings import DEFAULT_PATH, Settings
from peripheralhub.wd75.device import Wd75Probe

FPS = 20
DEVICE_POLL_S = 2.0
BATTERY_POLL_S = 60.0
_EPS = 1e-6  # float drift when the clock advances in fixed steps


def _log(what: str) -> None:
    print(f"peripheralhub-service: {what}", file=sys.stderr)
    traceback.print_exc()


class Service:
    def __init__(self, settings: Settings, basilisk: Basilisk, registry: Registry, notifier: LowBatteryNotifier,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._settings, self._mouse, self._registry, self._notifier = settings, basilisk, registry, notifier
        self._clock = clock
        self._mtime = settings.mtime()
        self._effect_key: Any = None
        self._frame_fn: Callable[[float], list] | None = None
        self._effect_start = 0.0
        self._next_frame = 0.0
        self._next_devices: float | None = None
        self._next_batteries: float | None = None
        self._mouse_ready = False

    # -- mouse
    def apply_saved_mouse(self) -> None:
        """Best effort: each saved setting is applied on its own, so one failure doesn't skip the rest."""
        s = self._settings
        steps: list[tuple[str, Callable[[], None]]] = []
        if (dpi := s.get("mouse.dpi")) is not None:
            steps.append(("dpi", lambda: self._mouse.set_dpi(int(dpi))))
        stages = s.get("mouse.stages")
        if isinstance(stages, dict) and stages.get("values"):
            steps.append(("stages", lambda: self._mouse.set_stages(
                [int(v) for v in stages["values"]], int(stages.get("active", 1)))))
        if (poll := s.get("mouse.poll")) is not None:
            steps.append(("poll", lambda: self._mouse.set_poll(int(poll))))
        if (brightness := s.get("mouse.brightness")) is not None:
            steps.append(("brightness", lambda: self._mouse.set_brightness(int(brightness))))
        effect = s.get("mouse.effect")
        if isinstance(effect, dict) and effect.get("kind") == "firmware" and effect.get("name"):
            steps.append(("effect", lambda: self._mouse.apply_effect(effect["name"], **(effect.get("params") or {}))))
        for what, fn in steps:
            try:
                fn()
            except Exception:
                _log(f"restoring mouse {what} failed")

    def _host_effect(self, now: float) -> None:
        effect = self._settings.get("mouse.effect")
        key = repr(effect)
        if key != self._effect_key:
            self._effect_key, self._frame_fn = key, None
            if isinstance(effect, dict) and effect.get("kind") == "host":
                try:
                    self._frame_fn = make_effect(effect["name"], self._mouse.MATRIX_COLS, self._mouse.ZONES,
                                                 **(effect.get("params") or {}))
                except Exception:
                    _log(f"bad host effect {effect!r}")
                self._effect_start, self._next_frame = now, now
        if self._frame_fn is None or not self._mouse_ready or now + _EPS < self._next_frame:
            return
        self._next_frame += 1 / FPS
        if self._next_frame <= now:  # fell behind (suspend, slow I/O): don't burst to catch up
            self._next_frame = now + 1 / FPS
        try:
            self._mouse.send_frame([tuple(c) for c in self._frame_fn(now - self._effect_start)])
        except Exception:
            pass  # unplugged mid-frame: the next device poll notices

    # -- loop
    def _mouse_state(self) -> str:
        return next((s.state for s in self._registry.statuses() if s.id == "basilisk"), "disconnected")

    def step(self, now: float) -> None:
        mtime = self._settings.mtime()
        if mtime != self._mtime:
            self._mtime = mtime
            self._settings.reload()
        if self._next_devices is None or now + _EPS >= self._next_devices:
            self._next_devices = now + DEVICE_POLL_S
            try:
                self._registry.poll_devices()
            except Exception:
                _log("device poll failed")
            ready = self._mouse_state() == "ready"
            if ready and not self._mouse_ready:
                self._mouse_ready = True
                self.apply_saved_mouse()
            self._mouse_ready = ready
        if self._next_batteries is None or now + _EPS >= self._next_batteries:
            self._next_batteries = now + BATTERY_POLL_S
            try:
                self._registry.poll_batteries()
                for s in self._registry.statuses():
                    if s.battery is not None:
                        self._notifier.check(s.id, s.title, s.battery)
            except Exception:
                _log("battery poll failed")
        self._host_effect(now)

    def run(self, stop: Callable[[], bool], sleep: Callable[[float], None] = time.sleep) -> None:
        while not stop():
            self.step(self._clock())
            sleep(1 / FPS / 2)


def main() -> int:
    settings = Settings(DEFAULT_PATH)
    basilisk = Basilisk()
    registry = Registry(settings, wd75=Wd75Probe(str(Path(BACKUP_DIR).expanduser())), basilisk=basilisk)
    service = Service(settings, basilisk, registry, LowBatteryNotifier(settings))
    stopping = False

    def on_term(_sig, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    try:
        service.run(lambda: stopping)
    finally:
        basilisk.close()
    return 0
