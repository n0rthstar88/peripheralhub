"""Keyboard > Lighting: effect, brightness, speed and colour with live preview and Save."""
from __future__ import annotations

import colorsys
import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from peripheralhub.ui.battery import BatteryWidget  # noqa: E402
from peripheralhub.ui.pages.kb_common import KB_TABS, GatedView, to_state  # noqa: E402
from peripheralhub.wd75.device import Wd75State  # noqa: E402
from peripheralhub.wd75.effects import EFFECTS, effect_name  # noqa: E402
from peripheralhub.wd75.via import ViaError  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

DEBOUNCE_MS = 80
HEART_NOTE = ("Heart is a backlight pattern switched with Fn+H (colour Fn+]). "
              "You can move those to other keys on the Keymap page.")
# (name, hue, sat) in VIA units
SWATCHES = [("Red", 0, 255), ("Orange", 21, 255), ("Yellow", 43, 255), ("Green", 85, 255),
            ("Cyan", 128, 255), ("Blue", 170, 255), ("Purple", 191, 255), ("Pink", 213, 255),
            ("White", 0, 0)]


def rgb_to_via_hs(r: int, g: int, b: int) -> tuple[int, int]:
    h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return round(h * 255) % 256, round(s * 255)


def via_hs_to_rgb(h: int, s: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h / 255, s / 255, 1.0)
    return round(r * 255), round(g * 255), round(b * 255)


def _rgba(h: int, s: int) -> Gdk.RGBA:
    r, g, b = via_hs_to_rgb(h, s)
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r / 255, g / 255, b / 255, 1.0
    return c


class LightingPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._loading = False
        self._loaded = False
        self._dirty = False
        self._pending: dict[str, int] = {}
        self._timer = 0
        self._ids = sorted(EFFECTS)
        self._hue, self._sat = 0, 255
        self._note: Adw.PreferencesGroup | None = None

        self._battery = BatteryWidget()
        self._battery.set_halign(Gtk.Align.START)
        page = Adw.PreferencesPage()

        top = Adw.PreferencesGroup(title="Battery")
        top.add(self._battery)
        page.add(top)

        grp = Adw.PreferencesGroup(title="Lighting")
        self._effect = Adw.ComboRow(title="Effect")
        rename = Gtk.Button(label="Rename…", valign=Gtk.Align.CENTER)
        rename.connect("clicked", self._on_rename)
        self._effect.add_suffix(rename)
        self._fill_effects()
        self._effect.connect("notify::selected", self._on_effect)
        grp.add(self._effect)
        self._brightness = self._scale_row(grp, "Brightness", "brightness")
        self._speed = self._scale_row(grp, "Speed", "speed")
        page.add(grp)

        colour = Adw.PreferencesGroup(title="Colour")
        row = Adw.ActionRow(title="Colour")
        swatch_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        provider = Gtk.CssProvider()
        css = ""
        for i, (name, h, s) in enumerate(SWATCHES):
            r, g, b = via_hs_to_rgb(h, s)
            css += f".phub-sw{i} {{ background: rgb({r},{g},{b}); min-width: 24px; min-height: 24px; padding: 0; }}\n"
            btn = Gtk.Button(tooltip_text=name)
            btn.add_css_class("circular")
            btn.add_css_class(f"phub-sw{i}")
            btn.connect("clicked", self._on_swatch, h, s)
            swatch_box.append(btn)
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        row.add_suffix(swatch_box)
        self._picker = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        self._picker.set_rgba(_rgba(0, 255))
        self._picker.connect("notify::rgba", self._on_picked)
        row.add_suffix(self._picker)
        colour.add(row)
        page.add(colour)

        self._note = Adw.PreferencesGroup()
        note_row = Adw.ActionRow(title=HEART_NOTE, icon_name="dialog-information-symbolic")
        note_row.set_title_lines(0)
        self._note.add(note_row)
        self._note.set_visible(False)
        page.add(self._note)

        save = Adw.PreferencesGroup()
        srow = Adw.ActionRow(title="Save to keyboard", subtitle="Changes preview live and are lost on power-off until saved.")
        self._unsaved = Gtk.Label(label="Unsaved changes", visible=False, valign=Gtk.Align.CENTER)
        self._unsaved.add_css_class("warning")
        self._save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        self._save.add_css_class("suggested-action")
        self._save.connect("clicked", self._on_save)
        srow.add_suffix(self._unsaved)
        srow.add_suffix(self._save)
        save.add(srow)
        self._error = Gtk.Label(wrap=True, visible=False, xalign=0)
        self._error.add_css_class("error")
        save.add(self._error)
        page.add(save)

        self._gate = GatedView(ctx, page, self._resync)
        self._root = self._gate

    # -- construction helpers
    def _scale_row(self, grp: Adw.PreferencesGroup, title: str, key: str) -> Gtk.Scale:
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        scale.set_size_request(260, -1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_valign(Gtk.Align.CENTER)
        scale.connect("value-changed", lambda s: self._change(key, int(s.get_value())))
        row.add_suffix(scale)
        grp.add(row)
        return scale

    def _names(self) -> dict:
        return self._ctx.settings.get("wd75.effect_names", {}) or {}

    def _fill_effects(self, keep: int | None = None) -> None:
        self._loading = True
        names = self._names()
        self._effect.set_model(Gtk.StringList.new([effect_name(i, names) for i in self._ids]))
        if keep is not None and keep in self._ids:
            self._effect.set_selected(self._ids.index(keep))
        self._loading = False
        self._update_note()

    def _current_effect(self) -> int | None:
        sel = self._effect.get_selected()
        return self._ids[sel] if sel < len(self._ids) else None

    def _update_note(self) -> None:
        eid = self._current_effect()
        if self._note is not None:
            self._note.set_visible(eid is not None and "heart" in effect_name(eid, self._names()).lower())

    # -- DevicePage-like interface
    def widget(self) -> Gtk.Widget:
        return self._root

    def on_status(self, s: DeviceStatus) -> None:
        self._battery.set_reading(s.battery, time.time())
        state = to_state(s)
        self._gate.set_state(state, self._ctx.wd75.connection)
        if state is Wd75State.READY:
            if not self._loaded:
                self._load()
        else:
            self._loaded = False

    def _resync(self) -> None:
        """After Retry: re-apply the registry's view even if its status did not change."""
        self._loaded = False
        for s in self._ctx.registry.statuses():
            if s.id == "wd75":
                self.on_status(s)

    def _asleep(self) -> None:
        self._loaded = False
        self._gate.set_state(Wd75State.ASLEEP, self._ctx.wd75.connection)

    # -- device I/O
    def _load(self) -> None:
        try:
            rgb = self._ctx.wd75.via.get_rgb()
        except (ViaError, OSError, AttributeError):
            self._asleep()
            return
        self._loaded = True
        self._loading = True
        if rgb.effect in self._ids:
            self._effect.set_selected(self._ids.index(rgb.effect))
        self._brightness.set_value(rgb.brightness)
        self._speed.set_value(rgb.speed)
        self._hue, self._sat = rgb.hue, rgb.saturation
        self._picker.set_rgba(_rgba(self._hue, self._sat))
        self._loading = False
        self._set_dirty(False)
        self._update_note()

    def _set_dirty(self, v: bool) -> None:
        self._dirty = v
        self._unsaved.set_visible(v)

    def _change(self, key: str, value: int) -> None:
        if self._loading:
            return
        self._pending[key] = value
        self._set_dirty(True)
        if not self._timer:
            self._timer = GLib.timeout_add(DEBOUNCE_MS, self._flush)

    def _on_effect(self, *_a) -> None:
        eid = self._current_effect()
        self._update_note()
        if eid is not None:
            self._change("effect", eid)

    def _on_swatch(self, _b, h: int, s: int) -> None:
        self._set_colour(h, s)
        self._loading = True
        self._picker.set_rgba(_rgba(h, s))
        self._loading = False

    def _on_picked(self, *_a) -> None:
        if self._loading:
            return
        c = self._picker.get_rgba()
        h, s = rgb_to_via_hs(round(c.red * 255), round(c.green * 255), round(c.blue * 255))
        self._set_colour(h, s)

    def _set_colour(self, h: int, s: int) -> None:
        self._hue, self._sat = h, s
        self._pending["hue"], self._pending["saturation"] = h, s
        self._set_dirty(True)
        if not self._timer:
            self._timer = GLib.timeout_add(DEBOUNCE_MS, self._flush)

    def _flush(self) -> bool:
        self._timer = 0
        changes, self._pending = self._pending, {}
        if not changes:
            return GLib.SOURCE_REMOVE
        try:
            self._ctx.wd75.apply_rgb(**changes)
        except (ViaError, OSError):
            self._asleep()
            return GLib.SOURCE_REMOVE
        eid = self._current_effect()
        # Ruling R3: the mouse "match keyboard colour" effect reads this.
        self._ctx.settings.set("wd75.rgb", {
            "hue": self._hue, "sat": self._sat,
            "brightness": int(self._brightness.get_value()),
            "effect": eid if eid is not None else 0,
            "speed": int(self._speed.get_value()),
        })
        return GLib.SOURCE_REMOVE

    def _on_save(self, _b) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
            self._flush()
            if self._gate.state is not Wd75State.READY:
                return
        try:
            self._ctx.wd75.save_rgb()
        except (ViaError, OSError):
            self._asleep()
            return
        self._error.set_visible(False)
        self._set_dirty(False)

    def _on_rename(self, _b) -> None:
        eid = self._current_effect()
        if eid is None:
            return
        entry = Gtk.Entry(text=effect_name(eid, self._names()), activates_default=True)
        dlg = Adw.AlertDialog(heading="Rename effect", body=f"Effect id {eid}")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")

        def done(_d, response: str) -> None:
            text = entry.get_text().strip()
            if response != "ok" or not text:
                return
            names = dict(self._names())
            names[str(eid)] = text
            self._ctx.settings.set("wd75.effect_names", names)
            self._fill_effects(keep=eid)

        dlg.connect("response", done)
        dlg.present(self._root.get_root())


KB_TABS.append(("lighting", "Lighting", "weather-clear-symbolic", lambda ctx: LightingPage(ctx)))
