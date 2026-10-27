"""Shared WD75 page plumbing: status banners, the gated content view, and the sub-tab registry."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from peripheralhub.wd75.device import Connection, Wd75State  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

_BANNERS: dict[Wd75State, tuple[str, str]] = {
    Wd75State.ASLEEP: ("Keyboard asleep", "Press any key on the keyboard, then try again."),
    Wd75State.NO_PERMISSION: ("Allow access", "PeripheralHub needs a one-time permission to talk to your keyboard."),
    Wd75State.BLUETOOTH_ONLY: ("Settings need the cable or 2.4G dongle", "Battery is live over Bluetooth."),
    Wd75State.DISCONNECTED: ("Keyboard not connected", "Connect it with the cable or the 2.4G dongle."),
}


def status_banner(state: Wd75State, connection: Connection) -> tuple[str, str] | None:
    """(title, body) to show instead of the controls, or None when the keyboard is READY."""
    return _BANNERS.get(state)


def install_script() -> Path:
    return Path(__file__).resolve().parents[3] / "install.sh"


def to_state(s: DeviceStatus) -> Wd75State:
    try:
        return Wd75State(s.state)
    except ValueError:
        return Wd75State.DISCONNECTED


class KbSubPage(Protocol):
    def widget(self) -> Gtk.Widget: ...
    def on_status(self, s: DeviceStatus) -> None: ...


# (stack name, title, icon, factory). Later tasks append their tab here, in display order.
KbTab = tuple[str, str, str, "Callable[[AppContext], KbSubPage]"]
KB_TABS: list[KbTab] = []


class KeyboardPage:
    """The WD75 device page: an Adw.ViewStack with one child per entry in KB_TABS."""

    def __init__(self, ctx: AppContext) -> None:
        self._stack = Adw.ViewStack()
        self._subs: list[KbSubPage] = []
        for name, title, icon, factory in KB_TABS:
            sub = factory(ctx)
            self._subs.append(sub)
            self._stack.add_titled_with_icon(sub.widget(), name, title, icon)

    def widget(self) -> Gtk.Widget:
        return self._stack

    def on_status(self, s: DeviceStatus) -> None:
        for sub in self._subs:
            sub.on_status(s)


def keyboard_page(ctx: AppContext) -> KeyboardPage:
    return KeyboardPage(ctx)


class GatedView(Gtk.Stack):
    """Shows `content` when the keyboard is READY, otherwise a banner with Retry (and Allow)."""

    def __init__(self, ctx: AppContext, content: Gtk.Widget, on_retry: Callable[[], None] | None = None) -> None:
        super().__init__(vexpand=True)
        self._ctx = ctx
        self._on_retry_done = on_retry
        self.state = Wd75State.DISCONNECTED
        self.add_named(content, "content")
        self._status = Adw.StatusPage(icon_name="input-keyboard-symbolic")
        self._error = Gtk.Label(wrap=True, visible=False, margin_top=6)
        self._error.add_css_class("error")
        self._allow = Gtk.Button(label="Allow", halign=Gtk.Align.CENTER)
        self._allow.add_css_class("suggested-action")
        self._allow.add_css_class("pill")
        self._allow.connect("clicked", self._on_allow)
        self._retry = Gtk.Button(label="Retry", halign=Gtk.Align.CENTER)
        self._retry.add_css_class("pill")
        self._retry.connect("clicked", self._on_retry)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._allow)
        box.append(self._retry)
        box.append(self._error)
        self._status.set_child(box)
        self.add_named(self._status, "banner")
        self.set_state(Wd75State.DISCONNECTED, Connection.DISCONNECTED)

    def set_state(self, state: Wd75State, connection: Connection) -> None:
        self.state = state
        banner = status_banner(state, connection)
        if banner is None:
            self.set_visible_child_name("content")
            return
        self._status.set_title(banner[0])
        self._status.set_description(banner[1])
        self._allow.set_visible(state is Wd75State.NO_PERMISSION)
        self._error.set_visible(False)
        self.set_visible_child_name("banner")

    def _on_retry(self, _b) -> None:
        try:
            self._ctx.registry.refresh_keyboard()
        except Exception as e:  # never crash the UI on a failed re-read
            self._show_error(f"Retry failed: {e}")
            return
        if self._on_retry_done is not None:
            self._on_retry_done()

    def _on_allow(self, _b) -> None:
        script = install_script()
        if not script.exists():
            self._show_error(f"Installer not found at {script}.")
            return
        self._allow.set_sensitive(False)
        try:
            proc = Gio.Subprocess.new(["pkexec", str(script), "--udev-only"], Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            self._allow.set_sensitive(True)
            self._show_error(f"Could not start pkexec: {e.message}")
            return
        proc.communicate_utf8_async(None, None, self._on_allow_done)

    def _on_allow_done(self, proc: Gio.Subprocess, res) -> None:
        self._allow.set_sensitive(True)
        try:
            _ok, _out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as e:
            self._show_error(f"Permission setup failed: {e.message}")
            return
        if proc.get_exit_status() != 0:
            self._show_error((err or "").strip() or "Permission setup was cancelled or failed.")
            return
        self._on_retry(None)

    def _show_error(self, text: str) -> None:
        self._error.set_label(text)
        self._error.set_visible(True)
