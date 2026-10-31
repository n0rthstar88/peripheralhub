"""Settings page: low-battery threshold, background service, devices, backups, device access, about."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from peripheralhub import __version__  # noqa: E402
from peripheralhub.core.extensions import CONFIG_DIR  # noqa: E402
from peripheralhub.core.notify import DEFAULT_THRESHOLD  # noqa: E402
from peripheralhub.core.registry import BACKUP_DIR  # noqa: E402
from peripheralhub.core.systemd import SERVICE  # noqa: E402
from peripheralhub.ui.pages.kb_common import install_script  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

THRESHOLD_MIN, THRESHOLD_MAX = 10, 30


def clamp_threshold(v) -> int:
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return max(THRESHOLD_MIN, min(THRESHOLD_MAX, v))


class SettingsPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._syncing = False
        self._toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()
        self._toasts.set_child(page)

        battery = Adw.PreferencesGroup(title="Battery")
        self._threshold = Adw.SpinRow.new_with_range(THRESHOLD_MIN, THRESHOLD_MAX, 1)
        self._threshold.set_title("Low-battery warning")
        self._threshold.set_subtitle("Notify when a device drops to this level (%)")
        self._threshold.set_value(clamp_threshold(ctx.settings.get("battery.low_threshold", DEFAULT_THRESHOLD)))
        self._threshold.connect("notify::value", self._on_threshold)
        battery.add(self._threshold)
        page.add(battery)

        service = Adw.PreferencesGroup(title="Background service",
                                       description="Applies mouse settings at login, runs animated mouse effects "
                                                   "and sends low-battery notifications.")
        self._service = Adw.SwitchRow(title="Run in the background")
        self._service.connect("notify::active", self._on_service_toggled)
        service.add(self._service)
        page.add(service)

        page.add(self._devices_group())

        tools = Adw.PreferencesGroup(title="Maintenance")
        backups = Adw.ActionRow(title="Keyboard backups", subtitle=str(Path(BACKUP_DIR).expanduser()),
                                activatable=True)
        backups.add_suffix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        backups.connect("activated", self._on_open_backups)
        tools.add(backups)
        access = Adw.ActionRow(title="Install device access rule",
                               subtitle="One-time permission so the keyboard and mouse work without sudo",
                               activatable=True)
        access.add_suffix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        access.connect("activated", self._on_install_rule)
        self._access = access
        tools.add(access)
        page.add(tools)

        about = Adw.PreferencesGroup(title="About")
        about.add(Adw.ActionRow(title="PeripheralHub", subtitle=f"Version {__version__}"))
        page.add(about)

        self._toasts.connect("map", lambda *_a: self._refresh_service())

    def _devices_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Devices", description="Changes apply the next time the app and "
                                                                  "background service start.")
        hidden = self._ctx.settings.get("devices.hidden", [])
        hidden = hidden if isinstance(hidden, list) else []
        for device_id, title in (("wd75", "WD75 V2"), ("basilisk", "Basilisk V3"), ("headset", "Arctis Nova 7P")):
            row = Adw.SwitchRow(title=title, active=device_id not in hidden)
            row.connect("notify::active", self._on_device_toggled, device_id)
            group.add(row)
        for d in self._ctx.registry.extras:
            row = Adw.SwitchRow(title=GLib.markup_escape_text(d.title), subtitle=GLib.markup_escape_text(d.source),
                                active=True)
            row.connect("notify::active", self._on_device_toggled, d.id)
            group.add(row)
        for e in self._ctx.load_errors:
            row = Adw.ActionRow(title=GLib.markup_escape_text(f"Couldn't load {e.path.name}"),
                                subtitle=GLib.markup_escape_text(e.message))
            row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            group.add(row)
        folder = Adw.ActionRow(title="Custom devices folder", subtitle=str(Path(CONFIG_DIR).expanduser()),
                               activatable=True)
        folder.add_suffix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        folder.connect("activated", self._on_open_config)
        group.add(folder)
        return group

    def _on_device_toggled(self, row, _p, device_id: str) -> None:
        hidden = self._ctx.settings.get("devices.hidden", [])
        hidden = {h for h in hidden if isinstance(h, str)} if isinstance(hidden, list) else set()
        hidden.discard(device_id) if row.get_active() else hidden.add(device_id)
        self._ctx.settings.set("devices.hidden", sorted(hidden))
        self._toast("Restart PeripheralHub to apply this")

    def _on_open_config(self, _row) -> None:
        path = Path(CONFIG_DIR).expanduser()
        try:
            for sub in ("devices", "plugins"):
                (path / sub).mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (OSError, GLib.Error) as e:
            self._toast(f"Could not open {path}: {getattr(e, 'message', e)}")

    def widget(self) -> Gtk.Widget:
        return self._toasts

    def on_status(self, s: DeviceStatus) -> None:
        pass

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))

    def _on_threshold(self, row, _p) -> None:
        self._ctx.settings.set("battery.low_threshold", clamp_threshold(row.get_value()))

    # -- background service
    def _refresh_service(self) -> None:
        try:
            proc = Gio.Subprocess.new(["systemctl", "--user", "is-active", "--quiet", SERVICE],
                                      Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self._set_switch(False)
            return
        proc.wait_check_async(None, self._on_service_checked)

    def _on_service_checked(self, proc: Gio.Subprocess, res) -> None:
        try:
            proc.wait_check_finish(res)
            active = True
        except GLib.Error:
            active = False
        self._set_switch(active)

    def _set_switch(self, active: bool) -> None:
        self._syncing = True
        self._service.set_active(active)
        self._syncing = False
        self._service.set_sensitive(True)

    def _on_service_toggled(self, row, _p) -> None:
        if self._syncing:
            return
        verb = ["enable", "--now"] if row.get_active() else ["disable", "--now"]
        row.set_sensitive(False)
        try:
            proc = Gio.Subprocess.new(["systemctl", "--user", *verb, SERVICE], Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            self._toast(f"systemctl failed: {e.message}")
            self._refresh_service()
            return
        proc.communicate_utf8_async(None, None, self._on_service_done)

    def _on_service_done(self, proc: Gio.Subprocess, res) -> None:
        try:
            _ok, _out, err = proc.communicate_utf8_finish(res)
            if proc.get_exit_status() != 0:
                self._toast((err or "").strip() or "systemctl failed")
        except GLib.Error as e:
            self._toast(f"systemctl failed: {e.message}")
        self._refresh_service()

    # -- maintenance
    def _on_open_backups(self, _row) -> None:
        path = Path(BACKUP_DIR).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except (OSError, GLib.Error) as e:
            self._toast(f"Could not open {path}: {getattr(e, 'message', e)}")

    def _on_install_rule(self, _row) -> None:
        script = install_script()
        if not script.exists():
            self._toast(f"Installer not found at {script}")
            return
        self._access.set_sensitive(False)
        try:
            proc = Gio.Subprocess.new(["pkexec", str(script), "--udev-only"], Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            self._access.set_sensitive(True)
            self._toast(f"Could not start pkexec: {e.message}")
            return
        proc.communicate_utf8_async(None, None, self._on_rule_done)

    def _on_rule_done(self, proc: Gio.Subprocess, res) -> None:
        self._access.set_sensitive(True)
        try:
            _ok, _out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as e:
            self._toast(f"Permission setup failed: {e.message}")
            return
        if proc.get_exit_status() != 0:
            self._toast((err or "").strip() or "Permission setup was cancelled or failed")
            return
        self._toast("Device access rule installed")
        self._ctx.registry.poll_devices()


def settings_page(ctx: AppContext) -> SettingsPage:
    return SettingsPage(ctx)
