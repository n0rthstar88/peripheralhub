"""Headset page: a large battery readout for the Arctis Nova 7P (read through headsetcontrol)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from peripheralhub.ui.battery import BatteryWidget  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

CONNECTED_TEXT = "Connected via 2.4G dongle"
ABSENT_TEXT = "Plug the headset dongle directly into the PC (docks may not detect it)."


class HeadsetPage:
    def __init__(self, ctx: AppContext | None = None) -> None:
        self._status = Adw.StatusPage(icon_name="audio-headphones-symbolic", title="Arctis Nova 7P",
                                      vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self._battery = BatteryWidget()
        self._battery.set_halign(Gtk.Align.CENTER)
        box.append(self._battery)
        self._status.set_child(box)
        self._show(None)

    def widget(self) -> Gtk.Widget:
        return self._status

    def on_status(self, s: DeviceStatus) -> None:
        if s.id == "headset":
            self._show(s)

    def _show(self, s: DeviceStatus | None) -> None:
        present = s is not None and s.state != "disconnected"
        self._status.set_description(CONNECTED_TEXT if present else ABSENT_TEXT)
        self._battery.set_visible(present and s.battery is not None)
        if present:
            self._battery.set_reading(s.battery, time.time())


def headset_page(ctx: AppContext) -> HeadsetPage:
    return HeadsetPage(ctx)
