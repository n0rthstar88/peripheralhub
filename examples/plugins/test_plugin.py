"""A harmless test plugin: exercises every plugin hook and never touches hardware. Delete this file to remove it."""
import time
from pathlib import Path

from peripheralhub.plugin import Peripheral, battery_reading, run_command

HEARTBEAT = Path.home() / ".cache" / "peripheralhub-test-plugin-heartbeat"


class TestPage:
    """A custom page, built only when the app opens it, so the service and CLI never need GTK."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        heading = Gtk.Label(label="Test Plugin is running")
        heading.add_css_class("title-1")
        self._status = Gtk.Label(label="Waiting for status")
        self._service = Gtk.Label()
        self._result = Gtk.Label(label="Button not pressed yet")
        button = Gtk.Button(label="Run a test command", halign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.connect("clicked", self._on_clicked)
        for widget in (heading, self._status, self._service, button, self._result):
            self._box.append(widget)
        self._show_service()
        GLib.timeout_add_seconds(1, self._show_service)

    def widget(self):
        return self._box

    def on_status(self, status) -> None:
        level = status.battery.level if status.battery else "no reading"
        self._status.set_label(f"State: {status.state} · Simulated battery: {level}")

    def _show_service(self) -> bool:
        try:
            age = int(time.time() - HEARTBEAT.stat().st_mtime)
            self._service.set_label(f"Background service last ran this plugin {age} s ago")
        except OSError:
            self._service.set_label("Background service hasn't run this plugin yet")
        return True

    def _on_clicked(self, _button) -> None:
        result = run_command("date +%T")
        self._result.set_label(f"Command ran at {result.output}" if result.ok else f"Failed: {result.output}")


class TestPlugin(Peripheral):
    id = "test-plugin"
    title = "Test Plugin"
    icon = "applications-science-symbolic"
    has_battery = True

    def poll(self) -> str:
        return "connected"

    def read_battery(self):
        # Moves between 50% and 100% so it stays above any low-battery threshold.
        return battery_reading(50 + int(time.time() / 60) % 51, charging=False)

    def page(self, ctx):
        return TestPage()

    def background(self) -> None:
        HEARTBEAT.touch()


def register(api) -> None:
    api.add_device(TestPlugin())
