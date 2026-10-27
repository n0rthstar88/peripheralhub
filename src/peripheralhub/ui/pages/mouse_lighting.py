"""Basilisk > Lighting: brightness, built-in effects, and effects animated by the background service."""
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from peripheralhub.basilisk.device import Basilisk  # noqa: E402
from peripheralhub.basilisk.effects import HOST_EFFECTS  # noqa: E402
from peripheralhub.ui.pages.mouse_dpi import DEBOUNCE_MS, DEVICE_ERRORS, MouseGate, recheck  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

SERVICE = "peripheralhub"
RGB = tuple[int, int, int]
# fields each effect exposes: (key, kind, label, default)
_C, _P = "color", "period"
FIELDS: dict[str, list[tuple[str, str, str, object]]] = {
    "static": [(_C, "color", "Colour", (0, 255, 0))],
    "breathing": [(_C, "color", "Colour", (0, 255, 0)), (_P, "period", "Period (seconds)", 4.0)],
    "color_cycle": [(_P, "period", "Period (seconds)", 8.0)],
    "strip_gradient": [(_C, "color", "From", (255, 0, 0)), ("color2", "color", "To", (0, 0, 255)),
                       (_P, "period", "Period (seconds)", 6.0)],
    "zones_static": [("logo", "color", "Logo", (255, 0, 0)), ("wheel", "color", "Scroll wheel", (0, 255, 0)),
                     ("strip", "color", "Strip", (0, 0, 255))],
}


def effect_params(name: str, values: dict, wd75_rgb: dict | None) -> dict:
    """Settings-ready params (JSON-friendly lists) for an effect from the current widget values."""
    def c(k: str) -> list[int]:
        return list(values[k])

    if name == "static":
        return {"color": c("color")}
    if name == "breathing":
        return {"color": c("color"), "period": values["period"]}
    if name == "color_cycle":
        return {"period": values["period"]}
    if name == "strip_gradient":
        return {"colors": [c("color"), c("color2")], "period": values["period"]}
    if name == "zones_static":
        return {"zone_colors": {z: c(z) for z in ("logo", "wheel", "strip")}}
    if name == "match_keyboard":
        rgb = wd75_rgb or {}
        return {"hue": rgb.get("hue", 0), "sat": rgb.get("sat", 255)}
    return {}


def _rgba(rgb: RGB) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0
    return c


def _rgb(c: Gdk.RGBA) -> RGB:
    return round(c.red * 255), round(c.green * 255), round(c.blue * 255)


class LightingPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._loading = False
        self._loaded = False
        self._timer = 0
        self._pending: set[str] = set()
        self._current = "spectrum"
        self._radios: dict[str, Gtk.CheckButton] = {}
        self._values: dict[str, object] = {}
        self._field_rows: dict[str, Adw.ActionRow] = {}
        self._field_effect: dict[str, str] = {}

        page = Adw.PreferencesPage()
        self._banner = Adw.Banner(title="The background service is not running; animated effects need it.",
                                  button_label="Start background service", revealed=False)
        self._banner.connect("button-clicked", self._on_start_service)
        self._svc_error = Gtk.Label(wrap=True, visible=False, xalign=0, margin_start=12, margin_end=12)
        self._svc_error.add_css_class("error")

        bright = Adw.PreferencesGroup(title="Brightness")
        row = Adw.ActionRow(title="Brightness")
        self._brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self._brightness.set_size_request(260, -1)
        self._brightness.set_draw_value(True)
        self._brightness.set_value_pos(Gtk.PositionType.RIGHT)
        self._brightness.set_valign(Gtk.Align.CENTER)
        self._brightness.connect("value-changed", lambda *_: self._queue("brightness"))
        row.add_suffix(self._brightness)
        bright.add(row)
        page.add(bright)

        built = Adw.PreferencesGroup(title="Built-in")
        for name in Basilisk.EFFECTS:
            built.add(self._effect_row(name, name.capitalize(), None))
        page.add(built)

        host = Adw.PreferencesGroup(title="Animated by PeripheralHub")
        for name in HOST_EFFECTS:
            host.add(self._effect_row(name, name.replace("_", " ").capitalize(), "runs in the background service"))
        page.add(host)

        self._params = Adw.PreferencesGroup(title="Effect settings")
        for effect, fields in FIELDS.items():
            for key, kind, label, default in fields:
                fid = f"{effect}.{key}"
                self._values[fid] = default
                self._field_rows[fid] = self._field_row(fid, kind, label, default)
                self._field_effect[fid] = effect
                self._params.add(self._field_rows[fid])
        self._match_note = Adw.ActionRow(title="Uses the colour last applied on the keyboard Lighting page")
        self._params.add(self._match_note)
        page.add(self._params)

        self._error = Gtk.Label(wrap=True, visible=False, xalign=0, margin_start=12, margin_end=12)
        self._error.add_css_class("error")
        eg = Adw.PreferencesGroup()
        eg.add(self._error)
        page.add(eg)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top.append(self._banner)
        top.append(self._svc_error)
        top.append(Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=page))
        self._gate = MouseGate(ctx, top)
        self._gate.connect("unmap", lambda _w: self._cancel_pending())
        self._gate.connect("map", lambda _w: self._check_service())
        self._show_fields()

    # -- construction
    def _effect_row(self, name: str, title: str, subtitle: str | None) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle or "", activatable=True)
        radio = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        if self._radios:
            radio.set_group(next(iter(self._radios.values())))
        radio.connect("toggled", self._on_radio, name)
        row.add_prefix(radio)
        row.set_activatable_widget(radio)
        self._radios[name] = radio
        return row

    def _field_row(self, fid: str, kind: str, label: str, default) -> Adw.ActionRow:
        row = Adw.ActionRow(title=label)
        if kind == "color":
            w = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
            w.set_rgba(_rgba(default))
            w.connect("notify::rgba", lambda b, _p: self._set_field(fid, _rgb(b.get_rgba())))
        else:
            w = Gtk.SpinButton.new_with_range(0.5, 60.0, 0.5)
            w.set_valign(Gtk.Align.CENTER)
            w.set_value(default)
            w.connect("value-changed", lambda b: self._set_field(fid, b.get_value()))
        row.add_suffix(w)
        row._widget = w  # type: ignore[attr-defined]
        return row

    def _show_fields(self) -> None:
        for fid, row in self._field_rows.items():
            row.set_visible(self._field_effect[fid] == self._current)
        self._match_note.set_visible(self._current == "match_keyboard")
        self._params.set_visible(self._current in FIELDS or self._current == "match_keyboard")

    # -- DevicePage-like interface
    def widget(self) -> Gtk.Widget:
        return self._gate

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

    # -- load / write
    def _load(self) -> None:
        try:
            level = self._ctx.basilisk.brightness()
        except DEVICE_ERRORS as e:
            self._fail(e)
            return
        self._loaded = True
        self._error.set_visible(False)
        saved = self._ctx.settings.get("mouse.effect") or {}
        name = saved.get("name") if saved.get("name") in self._radios else "spectrum"
        self._loading = True
        self._brightness.set_value(level)
        self._restore_params(name, saved.get("params") or {})
        self._current = name
        self._radios[name].set_active(True)
        self._loading = False
        self._show_fields()

    def _restore_params(self, name: str, params: dict) -> None:
        flat: dict[str, object] = {}
        if "colors" in params and len(params["colors"]) == 2:
            flat["color"], flat["color2"] = params["colors"]
        flat.update(params.get("zone_colors", {}))
        flat.update({k: v for k, v in params.items() if k in ("color", "period")})
        for key, kind, _l, _d in FIELDS.get(name, []):
            if key not in flat:
                continue
            fid = f"{name}.{key}"
            w = self._field_rows[fid]._widget  # type: ignore[attr-defined]
            if kind == "color":
                self._values[fid] = tuple(flat[key])
                w.set_rgba(_rgba(self._values[fid]))
            else:
                self._values[fid] = float(flat[key])
                w.set_value(self._values[fid])

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
        try:
            if "brightness" in todo:
                v = int(self._brightness.get_value())
                self._ctx.basilisk.set_brightness(v)
                self._ctx.settings.set("mouse.brightness", v)
            if "effect" in todo:
                self._apply_effect()
        except DEVICE_ERRORS as e:
            self._fail(e)
            return GLib.SOURCE_REMOVE
        self._error.set_visible(False)
        return GLib.SOURCE_REMOVE

    def _values_for(self, name: str) -> dict:
        out = {}
        for key, _k, _l, _d in FIELDS.get(name, []):
            out[key] = self._values[f"{name}.{key}"]
        return out

    def _apply_effect(self) -> None:
        name = self._current
        params = effect_params(name, self._values_for(name), self._ctx.settings.get("wd75.rgb"))
        if name in Basilisk.EFFECTS:
            kwargs = {"color": tuple(params["color"])} if "color" in params else {}
            self._ctx.basilisk.apply_effect(name, **kwargs)
            self._ctx.settings.set("mouse.effect", {"kind": "firmware", "name": name, "params": params})
        else:
            # the background service picks this up and drives the mouse
            self._ctx.settings.set("mouse.effect", {"kind": "host", "name": name, "params": params})
            self._check_service()

    def _on_radio(self, radio: Gtk.CheckButton, name: str) -> None:
        if self._loading or not radio.get_active():
            return
        self._current = name
        self._show_fields()
        self._queue("effect")

    def _set_field(self, fid: str, value) -> None:
        self._values[fid] = value
        if not self._loading and self._field_effect[fid] == self._current:
            self._queue("effect")

    # -- background service
    def _check_service(self) -> None:
        try:
            proc = Gio.Subprocess.new(["systemctl", "--user", "is-active", SERVICE],
                                      Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self._banner.set_revealed(True)
            return
        proc.wait_check_async(None, self._on_service_checked)

    def _on_service_checked(self, proc: Gio.Subprocess, res) -> None:
        try:
            proc.wait_check_finish(res)
            active = True
        except GLib.Error:
            active = False
        self._banner.set_revealed(not active)

    def _on_start_service(self, _b) -> None:
        self._svc_error.set_visible(False)
        try:
            proc = Gio.Subprocess.new(["systemctl", "--user", "enable", "--now", SERVICE],
                                      Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as e:
            self._svc_fail(e.message)
            return
        proc.communicate_utf8_async(None, None, self._on_service_started)

    def _on_service_started(self, proc: Gio.Subprocess, res) -> None:
        try:
            _ok, _out, err = proc.communicate_utf8_finish(res)
        except GLib.Error as e:
            self._svc_fail(e.message)
            return
        if proc.get_exit_status() != 0:
            self._svc_fail((err or "").strip() or "systemctl failed.")
            return
        self._check_service()

    def _svc_fail(self, text: str) -> None:
        self._svc_error.set_label(f"Could not start the background service: {text}")
        self._svc_error.set_visible(True)
