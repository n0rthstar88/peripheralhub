"""Displays page: drag-arrange canvas, per-monitor mode/scale/rotation, apply with 15 s auto-revert."""
from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from peripheralhub.displays.hypr import ApplyError, RevertController, read_monitors  # noqa: E402
from peripheralhub.displays.luaconf import UnsupportedConfig, update_monitors  # noqa: E402
from peripheralhub.displays.model import (  # noqa: E402
    SCALES, TRANSFORMS, Monitor, logical_size, mode_string, normalize, snap_position, validate_layout,
)

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

MONITORS_PATH = "~/.config/hypr/monitors.lua"
OMASETTINGS_PATH = "~/.config/hypr/omasettings.lua"
CANVAS_MARGIN = 24
SNAP_PX = 14
_MODE = re.compile(r"^(\d+)x(\d+)@(\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class Selection:
    mode: str
    scale: float
    transform: int


@dataclass(frozen=True)
class ViewMap:
    """Logical (Hyprland) coordinates <-> canvas pixels."""
    scale: float
    ox: float
    oy: float

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.scale, self.oy + y * self.scale

    def to_logical(self, cx: float, cy: float) -> tuple[float, float]:
        return (cx - self.ox) / self.scale, (cy - self.oy) / self.scale


def parse_mode(s: str) -> tuple[int, int, float]:
    m = _MODE.match(s.strip())
    if m is None:
        raise ValueError(f"bad mode {s!r}")
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


def fit_view(ms: list[Monitor], width: float, height: float, margin: float = CANVAS_MARGIN) -> ViewMap:
    """Scale the enabled monitors' bounding box to fit the canvas, centred."""
    enabled = [m for m in ms if not m.disabled]
    if not enabled:
        return ViewMap(1.0, 0.0, 0.0)
    x0 = min(m.x for m in enabled)
    y0 = min(m.y for m in enabled)
    x1 = max(m.x + logical_size(m)[0] for m in enabled)
    y1 = max(m.y + logical_size(m)[1] for m in enabled)
    bw, bh = max(x1 - x0, 1), max(y1 - y0, 1)
    aw, ah = max(width - 2 * margin, 1), max(height - 2 * margin, 1)
    s = min(aw / bw, ah / bh)
    return ViewMap(s, (width - bw * s) / 2 - x0 * s, (height - bh * s) / 2 - y0 * s)


def build_layout(ms: list[Monitor], selections: dict[str, Selection]) -> list[Monitor]:
    out = []
    for m in ms:
        sel = selections.get(m.name)
        if sel is None:
            out.append(m)
            continue
        w, h, r = parse_mode(sel.mode)
        out.append(replace(m, width=w, height=h, refresh=r, scale=sel.scale, transform=sel.transform))
    return out


def reattach(ms: list[Monitor], name: str) -> list[Monitor]:
    """After a size change (mode/scale/rotation) left `name` detached, snap it back to the nearest edges."""
    if not any(name in e and "not touching" in e for e in validate_layout(ms)):
        return ms
    m = next(o for o in ms if o.name == name)
    x, y = snap_position(m, ms, m.x, m.y, threshold=math.inf)
    return [replace(o, x=x, y=y) if o.name == name else o for o in ms]


def has_monitor_override(path: str) -> bool:
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            return "monitor" in f.read()
    except OSError:
        return False


def _hit(view: ViewMap, ms: list[Monitor], cx: float, cy: float) -> Monitor | None:
    for m in reversed(ms):
        if m.disabled:
            continue
        w, h = logical_size(m)
        x0, y0 = view.to_canvas(m.x, m.y)
        if x0 <= cx <= x0 + w * view.scale and y0 <= cy <= y0 + h * view.scale:
            return m
    return None


def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class DisplaysPage:
    def __init__(self, ctx: AppContext | None = None, monitors_path: str = MONITORS_PATH,
                 omasettings_path: str = OMASETTINGS_PATH, read=read_monitors) -> None:
        self._path = os.path.expanduser(monitors_path)
        self._omasettings = omasettings_path
        self._read = read
        self._original: list[Monitor] = []
        self._layout: list[Monitor] = []
        self._selected: str | None = None
        self._drag: tuple[str, int, int, ViewMap] | None = None  # name, start x/y, frozen view
        self._syncing = False
        self._ctrl: RevertController | None = None
        self._dialog: Adw.AlertDialog | None = None
        self._timer = 0
        self._unsupported = False

        self._toasts = Adw.ToastOverlay()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toasts.set_child(outer)

        self._oma_banner = Adw.Banner(title="OmaSettings also sets monitor options and may override these.")
        self._lua_banner = Adw.Banner(
            title="monitors.lua uses a form PeripheralHub won't edit. Change it by hand in ~/.config/hypr/monitors.lua.")
        self._revert_banner = Adw.Banner(button_label="Retry revert")
        self._revert_banner.connect("button-clicked", self._on_retry_revert)
        for b in (self._oma_banner, self._lua_banner, self._revert_banner):
            outer.append(b)

        body = Gtk.Box(spacing=18, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18, vexpand=True)
        outer.append(body)

        self._canvas = Gtk.DrawingArea(hexpand=True, vexpand=True, content_width=500, content_height=320)
        self._canvas.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self._canvas.add_controller(drag)
        frame = Gtk.Frame(child=self._canvas)
        body.append(frame)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=320)
        body.append(side)
        self._group = Adw.PreferencesGroup(title="Monitor")
        self._mode_row = Adw.ComboRow(title="Resolution")
        self._scale_row = Adw.ComboRow(title="Scale")
        self._rot_row = Adw.ComboRow(
            title="Rotation", model=Gtk.StringList.new([TRANSFORMS[k] for k in sorted(TRANSFORMS)]))
        for row in (self._mode_row, self._scale_row, self._rot_row):
            row.connect("notify::selected", self._on_row_changed)
            self._group.add(row)
        side.append(self._group)

        self._errors = Gtk.Label(wrap=True, xalign=0, visible=False)
        self._errors.add_css_class("error")
        side.append(self._errors)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, valign=Gtk.Align.END, vexpand=True)
        self._reset = Gtk.Button(label="Reset")
        self._reset.connect("clicked", lambda _b: self.reload())
        self._apply = Gtk.Button(label="Apply")
        self._apply.add_css_class("suggested-action")
        self._apply.connect("clicked", self._on_apply)
        buttons.append(self._reset)
        buttons.append(self._apply)
        side.append(buttons)

        self._root = self._toasts
        self._root.connect("realize", self._on_realize)
        self.reload()

    def widget(self) -> Gtk.Widget:
        return self._root

    def on_status(self, s: DeviceStatus) -> None:
        pass  # monitors are read from hyprctl, not from the registry

    # --- state ---------------------------------------------------------

    def reload(self) -> None:
        if self._ctrl is not None and self._ctrl.state == "pending":
            return
        try:
            self._original = self._read()
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self._original = []
            self._toast(f"Could not read monitors: {e}")
        self._layout = list(self._original)
        names = [m.name for m in self._layout if not m.disabled]
        if self._selected not in names:
            self._selected = names[0] if names else None
        self._oma_banner.set_revealed(has_monitor_override(self._omasettings))
        self._unsupported = self._check_unsupported()
        self._lua_banner.set_revealed(self._unsupported)
        self._sync_rows()
        self._changed()

    def _check_unsupported(self) -> bool:
        try:
            with open(self._path, encoding="utf-8", newline="") as f:
                update_monitors(f.read(), self._original)
        except UnsupportedConfig:
            return True
        except OSError:
            return False  # Keep reports an unreadable file
        return False

    def _current(self) -> Monitor | None:
        return next((m for m in self._layout if m.name == self._selected), None)

    def _changed(self) -> None:
        errors = validate_layout(self._layout) if self._layout else ["No monitors found"]
        self._errors.set_label("\n".join(errors))
        self._errors.set_visible(bool(errors))
        self._apply.set_sensitive(not errors and not self._unsupported)
        self._canvas.queue_draw()

    def _sync_rows(self) -> None:
        m = self._current()
        self._group.set_sensitive(m is not None)
        if m is None:
            return
        self._syncing = True
        try:
            self._group.set_title(m.name)
            self._group.set_description(m.description)
            cur = mode_string(m)
            self._modes = list(m.modes) if cur in m.modes else [cur, *m.modes]
            self._mode_row.set_model(Gtk.StringList.new(self._modes))
            self._mode_row.set_selected(self._modes.index(cur))
            self._scales = list(SCALES) if m.scale in SCALES else sorted([*SCALES, m.scale])
            self._scale_row.set_model(Gtk.StringList.new([f"{s:g}×" for s in self._scales]))
            self._scale_row.set_selected(self._scales.index(m.scale))
            self._rot_row.set_selected(sorted(TRANSFORMS).index(m.transform))
        finally:
            self._syncing = False

    def _on_row_changed(self, *_a) -> None:
        m = self._current()
        if self._syncing or m is None:
            return
        sel = Selection(self._modes[self._mode_row.get_selected()],
                        self._scales[self._scale_row.get_selected()],
                        sorted(TRANSFORMS)[self._rot_row.get_selected()])
        self._layout = reattach(build_layout(self._layout, {m.name: sel}), m.name)
        self._changed()

    # --- canvas --------------------------------------------------------

    def _view(self) -> ViewMap:
        if self._drag is not None:
            return self._drag[3]
        return fit_view(self._layout, self._canvas.get_width(), self._canvas.get_height())

    def _draw(self, _area, cr, width: int, height: int) -> None:
        fg = self._canvas.get_color()
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()
        view = self._view()
        for m in self._layout:
            if m.disabled:
                continue
            w, h = logical_size(m)
            x, y = view.to_canvas(m.x, m.y)
            sw, sh = w * view.scale, h * view.scale
            selected = m.name == self._selected
            _rounded_rect(cr, x + 2, y + 2, sw - 4, sh - 4, 10)
            if selected:
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.30)
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10)
            cr.fill_preserve()
            c = accent if selected else fg
            cr.set_source_rgba(c.red, c.green, c.blue, 0.9 if selected else 0.4)
            cr.set_line_width(2.5 if selected else 1.5)
            cr.stroke()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 1.0)
            self._label(cr, m.name, x + sw / 2, y + sh / 2 - 9, 15, bold=True)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
            self._label(cr, m.description or mode_string(m), x + sw / 2, y + sh / 2 + 11, 11, max_w=sw - 12)

    @staticmethod
    def _label(cr, text: str, cx: float, cy: float, size: float, bold: bool = False, max_w: float = 0) -> None:
        cr.select_font_face("Sans", 0, 1 if bold else 0)
        cr.set_font_size(size)
        if max_w > 0:
            while len(text) > 3 and cr.text_extents(text).width > max_w:
                text = text[:-2] + "…"
        e = cr.text_extents(text)
        cr.move_to(cx - e.width / 2 - e.x_bearing, cy - e.height / 2 - e.y_bearing)
        cr.show_text(text)

    def _on_drag_begin(self, _g, sx: float, sy: float) -> None:
        view = self._view()
        m = _hit(view, self._layout, sx, sy)
        if m is None:
            return
        if m.name != self._selected:
            self._selected = m.name
            self._sync_rows()
        self._drag = (m.name, m.x, m.y, view)
        self._canvas.queue_draw()

    def _on_drag_update(self, _g, dx: float, dy: float) -> None:
        if self._drag is None:
            return
        name, x0, y0, view = self._drag
        nx, ny = round(x0 + dx / view.scale), round(y0 + dy / view.scale)
        self._layout = [replace(m, x=nx, y=ny) if m.name == name else m for m in self._layout]
        self._canvas.queue_draw()

    def _on_drag_end(self, _g, _dx: float, _dy: float) -> None:
        if self._drag is None:
            return
        name = self._drag[0]
        self._drag = None
        m = next(m for m in self._layout if m.name == name)
        threshold = max(SNAP_PX / max(self._view().scale, 1e-6), 40)  # canvas px -> logical units
        x, y = snap_position(m, self._layout, m.x, m.y, threshold=threshold)
        self._layout = [replace(o, x=x, y=y) if o.name == name else o for o in self._layout]
        self._changed()

    # --- apply / keep / revert -----------------------------------------

    def _on_apply(self, _b) -> None:
        if self._ctrl is not None and self._ctrl.state in ("pending", "revert_failed"):
            return
        self._ctrl = RevertController(list(self._original), path=self._path)
        try:
            self._ctrl.start(normalize(self._layout))
        except ApplyError as e:
            self._after_revert(f"Could not apply: {e}")
            return
        self._show_dialog()

    def _show_dialog(self) -> None:
        d = Adw.AlertDialog(heading="Keep these display settings?", body=self._countdown_text(15))
        d.add_response("revert", "Revert")
        d.add_response("keep", "Keep")
        d.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("revert")
        d.set_close_response("revert")
        d.connect("response", self._on_response)
        self._dialog = d
        self._timer = GLib.timeout_add_seconds(1, self._tick)
        d.present(self._root)

    @staticmethod
    def _countdown_text(n: int) -> str:
        return f"Reverting in {n} s"

    def _tick(self) -> bool:
        ctrl = self._ctrl
        if ctrl is None or ctrl.state != "pending":
            self._timer = 0
            return GLib.SOURCE_REMOVE
        left = ctrl.tick()
        if ctrl.state != "pending":
            self._timer = 0
            self._close_dialog()
            self._after_revert("Display settings reverted")
            return GLib.SOURCE_REMOVE
        if self._dialog is not None:
            self._dialog.set_body(self._countdown_text(left))
        return GLib.SOURCE_CONTINUE

    def _close_dialog(self) -> None:
        d, self._dialog = self._dialog, None
        if d is not None:
            d.force_close()

    def _stop_timer(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _on_response(self, _d, response: str) -> None:
        self._dialog = None
        self._stop_timer()
        ctrl = self._ctrl
        if ctrl is None or ctrl.state != "pending":
            return
        if response == "keep":
            try:
                backup = ctrl.keep()
            except (OSError, UnsupportedConfig) as e:
                ctrl.cancel()
                if isinstance(e, UnsupportedConfig):
                    self._unsupported = True
                    self._lua_banner.set_revealed(True)
                self._after_revert(f"Could not save monitors.lua ({e}); display settings reverted")
                return
            self._toast(f"Saved. Backup: {backup}")
            self.reload()
        else:
            ctrl.cancel()
            self._after_revert("Display settings reverted")

    def cancel_pending(self) -> None:
        """Window closing or app quitting: never leave an unconfirmed layout behind."""
        self._stop_timer()
        if self._ctrl is not None and self._ctrl.state == "pending":
            self._ctrl.cancel()
        self._close_dialog()

    def _after_revert(self, message: str) -> None:
        ctrl = self._ctrl
        if ctrl is not None and ctrl.state == "revert_failed":
            self._revert_banner.set_title(f"Reverting the displays failed: {ctrl.last_error}")
            self._revert_banner.set_revealed(True)
            self._toast("Revert failed: use Retry revert")
            return
        self._revert_banner.set_revealed(False)
        self._toast(message)
        self.reload()

    def _on_retry_revert(self, _b) -> None:
        if self._ctrl is not None and self._ctrl.retry_revert():
            self._after_revert("Display settings reverted")
        elif self._ctrl is not None:
            self._revert_banner.set_title(f"Reverting the displays failed: {self._ctrl.last_error}")

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))

    def _on_realize(self, w: Gtk.Widget) -> None:
        root = w.get_root()
        if isinstance(root, Gtk.Window):
            root.connect("close-request", lambda *_a: (self.cancel_pending(), False)[1])
        app = Gio.Application.get_default()
        if app is not None:
            app.connect("shutdown", lambda *_a: self.cancel_pending())


def displays_page(ctx: AppContext) -> DisplaysPage:
    return DisplaysPage(ctx)
