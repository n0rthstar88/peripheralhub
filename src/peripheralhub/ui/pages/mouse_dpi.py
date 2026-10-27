"""Basilisk page: a ViewStack with DPI and Lighting tabs, plus the DPI tab and the shared state gate."""
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from peripheralhub.basilisk.device import RazerError  # noqa: E402
from peripheralhub.ui.pages.kb_common import install_script  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

DEBOUNCE_MS = 80
DPI_MIN, DPI_MAX, DPI_STEP = 100, 26000, 50
MAX_STAGES = 5
POLL_RATES = (125, 500, 1000)
DEVICE_ERRORS = (RazerError, OSError, ValueError)


def clamp_dpi(v: int) -> int:
    """Clamp to 100-26000 and round to the nearest 50 (halves round up)."""
    v = max(DPI_MIN, min(DPI_MAX, int(v)))
    return max(DPI_MIN, min(DPI_MAX, int(v / DPI_STEP + 0.5) * DPI_STEP))


def validate_stages(values: list[int]) -> list[int]:
    if not 1 <= len(values) <= MAX_STAGES:
        raise ValueError(f"need 1-{MAX_STAGES} DPI stages, got {len(values)}")
    return [clamp_dpi(v) for v in values]


class MouseGate(Gtk.Stack):
    """Shows `content` when the mouse is ready; otherwise a permission or not-connected banner."""

    def __init__(self, ctx: AppContext, content: Gtk.Widget) -> None:
        super().__init__(vexpand=True)
        self._ctx = ctx
        self.state = "disconnected"
        self.add_named(content, "content")
        self._status = Adw.StatusPage(icon_name="input-mouse-symbolic")
        self._error = Gtk.Label(wrap=True, visible=False, margin_top=6)
        self._error.add_css_class("error")
        self._allow = Gtk.Button(label="Allow", halign=Gtk.Align.CENTER)
        self._allow.add_css_class("suggested-action")
        self._allow.add_css_class("pill")
        self._allow.connect("clicked", self._on_allow)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._allow)
        box.append(self._error)
        self._status.set_child(box)
        self.add_named(self._status, "banner")
        self.set_state("disconnected")

    def set_state(self, state: str) -> None:
        self.state = state
        if state == "ready":
            self.set_visible_child_name("content")
            return
        if state == "no_permission":
            self._status.set_title("Allow access")
            self._status.set_description("PeripheralHub needs a one-time permission to talk to your mouse.")
        else:
            self._status.set_title("Mouse not connected")
            self._status.set_description("Plug in the Basilisk V3.")
        self._allow.set_visible(state == "no_permission")
        self._error.set_visible(False)
        self.set_visible_child_name("banner")

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
        recheck(self._ctx)

    def _show_error(self, text: str) -> None:
        self._error.set_label(text)
        self._error.set_visible(True)


def recheck(ctx: AppContext) -> None:
    """Re-read device presence; the registry notifies the pages if the state changed."""
    try:
        ctx.registry.poll_devices()
    except Exception:  # a failed re-check must never crash the UI
        pass


class DpiPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._loading = False
        self._loaded = False
        self._timer = 0
        self._pending: set[str] = set()
        self._values: list[int] = [800]
        self._active = 1  # 1-based
        self._radios: list[Gtk.CheckButton] = []

        page = Adw.PreferencesPage()
        cur = Adw.PreferencesGroup(title="Sensitivity")
        adj = Gtk.Adjustment(value=800, lower=DPI_MIN, upper=DPI_MAX, step_increment=DPI_STEP, page_increment=500)
        self._dpi = Adw.SpinRow(title="Current DPI", adjustment=adj)
        self._dpi.connect("notify::value", lambda *_: self._queue("dpi"))
        cur.add(self._dpi)
        self._poll = Adw.ComboRow(title="Polling rate", model=Gtk.StringList.new([f"{h} Hz" for h in POLL_RATES]))
        self._poll.connect("notify::selected", lambda *_: self._queue("poll"))
        cur.add(self._poll)
        page.add(cur)

        self._stage_group = Adw.PreferencesGroup(
            title="DPI stages", description="The DPI button on the mouse cycles through these. Select the active one.")
        self._add = Gtk.Button(label="Add stage", valign=Gtk.Align.CENTER)
        self._add.connect("clicked", self._on_add)
        self._stage_group.set_header_suffix(self._add)
        self._stage_rows: list[Adw.SpinRow] = []
        page.add(self._stage_group)

        self._error = Gtk.Label(wrap=True, visible=False, xalign=0, margin_start=12, margin_end=12)
        self._error.add_css_class("error")
        err_group = Adw.PreferencesGroup()
        err_group.add(self._error)
        page.add(err_group)

        self._gate = MouseGate(ctx, page)
        self._root = self._gate
        self._root.connect("unmap", lambda _w: self._cancel_pending())
        self._build_stage_rows()

    # -- DevicePage-like interface
    def widget(self) -> Gtk.Widget:
        return self._root

    def on_status(self, s: DeviceStatus) -> None:
        if s.id != "basilisk":
            return
        self._gate.set_state(s.state)
        if s.state != "ready":
            self._cancel_pending()
            self._loaded = False
        elif not self._loaded:
            self._load()

    def _cancel_pending(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._pending = set()

    def _fail(self, e: Exception) -> None:
        self._cancel_pending()
        self._loaded = False
        self._error.set_label(f"Mouse error: {e}")
        self._error.set_visible(True)
        recheck(self._ctx)
        self._gate.set_state(self._ctx.basilisk.state)

    # -- stage rows
    def _build_stage_rows(self) -> None:
        for row in self._stage_rows:
            self._stage_group.remove(row)
        self._stage_rows, self._radios = [], []
        self._loading = True
        for i, v in enumerate(self._values):
            adj = Gtk.Adjustment(value=v, lower=DPI_MIN, upper=DPI_MAX, step_increment=DPI_STEP, page_increment=500)
            row = Adw.SpinRow(title=f"Stage {i + 1}", adjustment=adj)
            radio = Gtk.CheckButton(tooltip_text="Active stage", active=(i + 1 == self._active))
            if self._radios:
                radio.set_group(self._radios[0])
            radio.connect("toggled", self._on_radio, i + 1)
            row.add_prefix(radio)
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove stage",
                            sensitive=len(self._values) > 1)
            rm.add_css_class("flat")
            rm.connect("clicked", self._on_remove, i)
            row.add_suffix(rm)
            row.connect("notify::value", self._on_stage_value, i)
            self._radios.append(radio)
            self._stage_rows.append(row)
            self._stage_group.add(row)
        self._add.set_sensitive(len(self._values) < MAX_STAGES)
        self._loading = False

    def _on_radio(self, radio: Gtk.CheckButton, idx: int) -> None:
        if self._loading or not radio.get_active():
            return
        self._active = idx
        self._queue("stages")

    def _on_stage_value(self, row: Adw.SpinRow, _p, i: int) -> None:
        if self._loading:
            return
        self._values[i] = clamp_dpi(int(row.get_value()))
        self._queue("stages")

    def _on_add(self, _b) -> None:
        if len(self._values) >= MAX_STAGES:
            return
        self._values.append(clamp_dpi(self._values[-1]))
        self._build_stage_rows()
        self._queue("stages")

    def _on_remove(self, _b, i: int) -> None:
        if len(self._values) <= 1:
            return
        del self._values[i]
        self._active = min(self._active, len(self._values))
        self._build_stage_rows()
        self._queue("stages")

    # -- device I/O
    def _load(self) -> None:
        b = self._ctx.basilisk
        try:
            x, _y = b.dpi()
            values, active = b.stages()
            hz = b.poll()
        except DEVICE_ERRORS as e:
            self._fail(e)
            return
        self._loaded = True
        self._error.set_visible(False)
        self._values, self._active = values or [x], max(1, min(active, len(values) or 1))
        self._build_stage_rows()
        self._loading = True
        self._dpi.set_value(x)
        if hz in POLL_RATES:
            self._poll.set_selected(POLL_RATES.index(hz))
        self._loading = False

    def _queue(self, key: str) -> None:
        if self._loading or self._gate.state != "ready":
            return
        self._pending.add(key)
        if not self._timer:
            self._timer = GLib.timeout_add(DEBOUNCE_MS, self._flush)

    def _flush(self) -> bool:
        self._timer = 0
        todo, self._pending = self._pending, set()
        if not todo or self._gate.state != "ready":
            return GLib.SOURCE_REMOVE
        b, st = self._ctx.basilisk, self._ctx.settings
        try:
            if "stages" in todo:
                values = validate_stages(self._values)
                b.set_stages(values, self._active)
                st.set("mouse.stages", {"values": values, "active": self._active})
                # the firmware switches to the active stage's DPI
                x, _y = b.dpi()
                self._loading = True
                self._dpi.set_value(x)
                self._loading = False
                st.set("mouse.dpi", x)
            if "dpi" in todo and "stages" not in todo:
                v = clamp_dpi(int(self._dpi.get_value()))
                b.set_dpi(v)
                st.set("mouse.dpi", v)
            if "poll" in todo:
                hz = POLL_RATES[self._poll.get_selected()]
                b.set_poll(hz)
                st.set("mouse.poll", hz)
        except DEVICE_ERRORS as e:
            self._fail(e)
            return GLib.SOURCE_REMOVE
        self._error.set_visible(False)
        return GLib.SOURCE_REMOVE


class MousePage:
    """The Basilisk device page: an Adw.ViewStack with DPI and Lighting children."""

    def __init__(self, ctx: AppContext) -> None:
        from peripheralhub.ui.pages.mouse_lighting import LightingPage  # avoid a circular import

        self._stack = Adw.ViewStack()
        self._subs = [DpiPage(ctx), LightingPage(ctx)]
        self._stack.add_titled_with_icon(self._subs[0].widget(), "dpi", "DPI", "input-mouse-symbolic")
        self._stack.add_titled_with_icon(self._subs[1].widget(), "lighting", "Lighting", "weather-clear-symbolic")

    def widget(self) -> Gtk.Widget:
        return self._stack

    def on_status(self, s: DeviceStatus) -> None:
        for sub in self._subs:
            sub.on_status(s)


def mouse_page(ctx: AppContext) -> MousePage:
    return MousePage(ctx)
