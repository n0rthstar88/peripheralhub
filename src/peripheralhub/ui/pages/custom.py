"""The standard page for custom devices: status, battery and action buttons."""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from peripheralhub.core.extensions import Action, Peripheral, run_command  # noqa: E402
from peripheralhub.ui.battery import BatteryWidget  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus

ACTION_TIMEOUT = 30.0


class CustomDevicePage:
    def __init__(self, device: Peripheral) -> None:
        self._device = device
        self._toasts = Adw.ToastOverlay()
        self._status = Adw.StatusPage(icon_name=device.icon, title=device.title, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self._battery = BatteryWidget()
        self._battery.set_halign(Gtk.Align.CENTER)
        self._battery.set_visible(False)
        box.append(self._battery)
        for action in device.actions:
            button = Gtk.Button(label=action.label)
            button.add_css_class("pill")
            button.connect("clicked", self._on_action, action)
            box.append(button)
        self._status.set_child(box)
        self._toasts.set_child(self._status)

    def widget(self) -> Gtk.Widget:
        return self._toasts

    def on_status(self, s: DeviceStatus) -> None:
        text = {"disconnected": self._device.hint, "connected": "Connected"}.get(s.state, "")
        self._status.set_description(GLib.markup_escape_text(text))
        self._battery.set_visible(s.battery is not None)
        if s.battery is not None:
            self._battery.set_reading(s.battery, time.time())

    def _on_action(self, button: Gtk.Button, action: Action) -> None:
        button.set_sensitive(False)

        def work() -> None:
            result = run_command(action.command, ACTION_TIMEOUT)
            GLib.idle_add(self._finished, button, action, result)

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, button: Gtk.Button, action: Action, result) -> bool:
        button.set_sensitive(True)
        text = f"{action.label}: done" if result.ok else f"{action.label} failed: {result.output or 'no output'}"
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text[:200]), timeout=6))
        return GLib.SOURCE_REMOVE
