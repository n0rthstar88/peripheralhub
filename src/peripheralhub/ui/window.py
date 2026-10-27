"""Main window: device sidebar on the left, one page per device on the right."""
from __future__ import annotations

import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from peripheralhub.basilisk.device import Basilisk  # noqa: E402
from peripheralhub.core.registry import DeviceStatus, Registry  # noqa: E402
from peripheralhub.core.settings import Settings  # noqa: E402
from peripheralhub.ui.battery import BatteryWidget  # noqa: E402
from peripheralhub.ui.pages import kb_lighting  # noqa: E402,F401  (registers the Lighting tab)
from peripheralhub.ui.pages import kb_keymap  # noqa: E402,F401  (registers the Keymap tab)
from peripheralhub.ui.pages import kb_macros  # noqa: E402,F401  (registers the Macros tab)
from peripheralhub.ui.pages.kb_common import keyboard_page  # noqa: E402
from peripheralhub.ui.pages.mouse_dpi import mouse_page  # noqa: E402
from peripheralhub.wd75.device import Wd75  # noqa: E402


@dataclass
class AppContext:
    settings: Settings
    registry: Registry  # pages may call registry.refresh_keyboard()
    wd75: Wd75
    basilisk: Basilisk


class DevicePage(Protocol):
    def widget(self) -> Gtk.Widget: ...
    def on_status(self, s: DeviceStatus) -> None: ...


# (id, title, icon, has battery, hint shown while disconnected)
SIDEBAR = [
    ("wd75", "WD75 V2", "input-keyboard-symbolic", True, "Connect with cable or dongle"),
    ("basilisk", "Basilisk V3", "input-mouse-symbolic", False, "Plug in the mouse"),
    ("headset", "Arctis Nova 7P", "audio-headphones-symbolic", True, "Not detected"),
    ("displays", "Displays", "video-display-symbolic", False, ""),
]
SETTINGS_ROW = ("settings", "Settings", "emblem-system-symbolic", False, "")
_STATE_TEXT = {
    "no_permission": "Allow access",
    "asleep": "Asleep: press any key",
}
_HAS_BATTERY = {"wd75", "headset"}


def subtitle_for(s: DeviceStatus | None, hint: str) -> str:
    if s is None:
        return ""
    if s.state == "disconnected":
        return hint
    if s.state in _STATE_TEXT:
        return _STATE_TEXT[s.state]
    return s.connection or ("Connected" if s.state in ("connected", "ready") and s.id != "displays" else "")


class StubPage:
    """Placeholder until the device's real page task replaces it in PAGES."""

    def __init__(self, ctx: AppContext, device_id: str, title: str) -> None:
        self._id = device_id
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER,
                      valign=Gtk.Align.CENTER)
        heading = Gtk.Label(label=title)
        heading.add_css_class("title-1")
        soon = Gtk.Label(label="Coming soon")
        soon.add_css_class("dim-label")
        box.append(heading)
        box.append(soon)
        self._battery: BatteryWidget | None = None
        if device_id in _HAS_BATTERY:
            self._battery = BatteryWidget()
            self._battery.set_halign(Gtk.Align.CENTER)
            box.append(self._battery)
        self._box = box

    def widget(self) -> Gtk.Widget:
        return self._box

    def on_status(self, s: DeviceStatus) -> None:
        if self._battery is not None and s.id == self._id:
            self._battery.set_reading(s.battery, time.time())


def _stub_factory(device_id: str, title: str) -> Callable[[AppContext], DevicePage]:
    return lambda ctx: StubPage(ctx, device_id, title)


# Tasks 14-19 replace these entries with their real page factories.
PAGES: dict[str, Callable[[AppContext], DevicePage]] = {
    row[0]: _stub_factory(row[0], row[1]) for row in [*SIDEBAR, SETTINGS_ROW]
}
PAGES["wd75"] = keyboard_page
PAGES["basilisk"] = mouse_page


def safe(fn: Callable[[], object], what: str) -> bool:
    """Run fn for a GLib timer; never let an exception reach GTK. Always keeps the timer alive."""
    try:
        fn()
    except Exception:
        print(f"peripheralhub: {what} failed", file=sys.stderr)
        traceback.print_exc()
    return GLib.SOURCE_CONTINUE


class _Row(Gtk.ListBoxRow):
    def __init__(self, spec: tuple[str, str, str, bool, str]) -> None:
        super().__init__()
        self.device_id, title, icon, has_battery, self.hint = spec
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
        box.append(Gtk.Image.new_from_icon_name(icon))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self._title = Gtk.Label(label=title, xalign=0)
        self._sub = Gtk.Label(xalign=0, ellipsize=3)
        self._sub.set_visible(False)
        self._sub.add_css_class("caption")
        self._sub.add_css_class("dim-label")
        text.append(self._title)
        text.append(self._sub)
        box.append(text)
        self.battery: BatteryWidget | None = None
        if has_battery:
            self.battery = BatteryWidget(compact=True)
            box.append(self.battery)
        self.set_child(box)

    def update(self, s: DeviceStatus | None) -> None:
        sub = subtitle_for(s, self.hint)
        self._sub.set_label(sub)
        self._sub.set_visible(bool(sub))
        if s is None:
            return
        if s.state == "disconnected":
            self.add_css_class("dim-label")
        else:
            self.remove_css_class("dim-label")
        if self.battery is not None:
            self.battery.set_visible(s.battery is not None)
            self.battery.set_reading(s.battery, time.time())


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, ctx: AppContext) -> None:
        super().__init__(application=app, title="PeripheralHub", default_width=1100, default_height=720)
        self._ctx = ctx
        self._pages: dict[str, DevicePage] = {}
        self._nav: dict[str, Adw.NavigationPage] = {}
        self._rows: dict[str, _Row] = {}

        self._split = Adw.NavigationSplitView()
        self.set_content(self._split)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("navigation-sidebar")
        for spec in SIDEBAR:
            self._add_row(self._list, spec)
        self._pinned = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._pinned.add_css_class("navigation-sidebar")
        self._add_row(self._pinned, SETTINGS_ROW)
        self._list.connect("row-selected", self._on_selected, self._pinned)
        self._pinned.connect("row-selected", self._on_selected, self._list)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self._list)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(Gtk.Separator())
        bottom.append(self._pinned)
        view = Adw.ToolbarView(content=scroller)
        view.add_top_bar(Adw.HeaderBar(title_widget=Gtk.Label(label="PeripheralHub")))
        view.add_bottom_bar(bottom)
        side = Adw.NavigationPage.new(view, "PeripheralHub")
        self._split.set_sidebar(side)
        self._split.set_min_sidebar_width(250)
        self._split.set_max_sidebar_width(300)

        ctx.registry.subscribe(self._on_statuses)
        self._on_statuses(ctx.registry.statuses())
        self._list.select_row(self._rows["wd75"])

        safe(ctx.registry.poll_devices, "device poll")
        safe(ctx.registry.poll_batteries, "battery poll")
        GLib.timeout_add_seconds(2, safe, ctx.registry.poll_devices, "device poll")
        GLib.timeout_add_seconds(60, safe, ctx.registry.poll_batteries, "battery poll")

    def _add_row(self, lb: Gtk.ListBox, spec) -> None:
        row = _Row(spec)
        self._rows[spec[0]] = row
        lb.append(row)

    def _on_selected(self, lb: Gtk.ListBox, row: _Row | None, other: Gtk.ListBox) -> None:
        if row is None:
            return
        other.unselect_all()
        self._show(row.device_id)

    def _page(self, device_id: str) -> DevicePage:
        if device_id not in self._pages:
            page = PAGES[device_id](self._ctx)
            self._pages[device_id] = page
            for s in self._ctx.registry.statuses():
                if s.id == device_id:
                    self._safe_status(page, s)
        return self._pages[device_id]

    def _show(self, device_id: str) -> None:
        if device_id not in self._nav:
            page = self._page(device_id)
            content = page.widget()
            view = Adw.ToolbarView(content=content)
            header = Adw.HeaderBar()
            if isinstance(content, Adw.ViewStack):
                header.set_title_widget(Adw.ViewSwitcher(stack=content, policy=Adw.ViewSwitcherPolicy.WIDE))
            view.add_top_bar(header)
            title = next(r[1] for r in [*SIDEBAR, SETTINGS_ROW] if r[0] == device_id)
            self._nav[device_id] = Adw.NavigationPage.new(view, title)
        self._split.set_content(self._nav[device_id])
        self._split.set_show_content(True)

    @staticmethod
    def _safe_status(page: DevicePage, s: DeviceStatus) -> None:
        try:
            page.on_status(s)
        except Exception:
            print(f"peripheralhub: page for {s.id} failed on status", file=sys.stderr)
            traceback.print_exc()

    def _on_statuses(self, statuses: list[DeviceStatus]) -> None:
        try:
            for s in statuses:
                row = self._rows.get(s.id)
                if row is not None:
                    row.update(s)
                if s.id in self._pages:
                    self._safe_status(self._pages[s.id], s)
        except Exception:
            traceback.print_exc()
