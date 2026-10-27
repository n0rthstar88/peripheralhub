"""Animated battery gauge: smooth fill, green/amber/red, sweeping band while charging."""
from __future__ import annotations

import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from peripheralhub.core.battery import BatteryReading, age_text, battery_color  # noqa: E402

COLORS = {
    "green": (0.20, 0.82, 0.48),
    "amber": (0.96, 0.76, 0.07),
    "red": (0.88, 0.11, 0.14),
}
SWEEP_SECONDS = 1.6
ANIM_MS = 600


def battery_view(r: BatteryReading | None, now: float) -> tuple[str, str, bool]:
    """Pure logic: (caption, colour name, charging animation on?)."""
    if r is None:
        return "No reading yet", "neutral", False
    charging = r.charging is True
    if r.level is None:
        return ("Charging", "green", True) if charging else ("No reading yet", "neutral", False)
    caption = f"{r.level}%"
    if not r.live:
        caption += f" · {age_text(max(0.0, now - r.measured_at))}"
    return caption, battery_color(r.level), charging


def _rounded(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class BatteryWidget(Gtk.DrawingArea):
    def __init__(self, compact: bool = False) -> None:
        super().__init__()
        self._compact = compact
        self._body_w, self._body_h = (30.0, 14.0) if compact else (56.0, 26.0)
        self._reading: BatteryReading | None = None
        self._colour = "neutral"
        self._charging = False
        self._phase = 0.0
        self._tick_id = 0
        self._timer_id = 0
        self._anim: Adw.TimedAnimation | None = None
        self._displayed = 0.0
        self.caption = "No reading yet"
        self.set_valign(Gtk.Align.CENTER)
        self.set_content_height(int(self._body_h) + 4)
        self.set_draw_func(self._draw)
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self._relayout()

    @property
    def displayed_level(self) -> float:
        return self._displayed

    def set_reading(self, r: BatteryReading | None, now: float) -> None:
        self._reading = r
        self.caption, self._colour, self._charging = battery_view(r, now)
        target = float(r.level) if r is not None and r.level is not None else 0.0
        if self._anim is not None:
            self._anim.pause()
        self._anim = Adw.TimedAnimation.new(
            self, self._displayed, target, ANIM_MS,
            Adw.CallbackAnimationTarget.new(self._on_value),
        )
        self._anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._anim.play()
        self._relayout()
        self._sync_tick()
        self.queue_draw()

    def _on_value(self, value: float) -> None:
        self._displayed = value
        self.queue_draw()

    def _layout(self) -> Pango.Layout:
        text = "" if self._compact and self._colour == "neutral" else self.caption
        layout = self.create_pango_layout(text)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        layout.set_attributes(attrs)
        return layout

    def _relayout(self) -> None:
        text_w = self._layout().get_pixel_size()[0]
        self.set_content_width(int(self._body_w + 6 + (8 + text_w if text_w else 0)))

    def _sync_tick(self) -> None:
        if self._charging and self.get_mapped() and not self._tick_id:
            self._tick_id = self.add_tick_callback(self._on_tick)
        elif not self._charging and self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0

    def _on_tick(self, _w, clock) -> bool:
        self._phase = (clock.get_frame_time() / 1e6 % SWEEP_SECONDS) / SWEEP_SECONDS
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _on_map(self, _w) -> None:
        self._sync_tick()
        # keep "2 h ago" honest without needing a new reading
        self._timer_id = GLib.timeout_add_seconds(30, self._refresh_caption)

    def _on_unmap(self, _w) -> None:
        if self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def _refresh_caption(self) -> bool:
        caption, colour, charging = battery_view(self._reading, time.time())
        if caption != self.caption:
            self.caption = caption
            self._relayout()
            self.queue_draw()
        self._colour, self._charging = colour, charging
        self._sync_tick()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, width: int, height: int) -> None:
        fg = self.get_color()
        bw, bh = self._body_w, self._body_h
        x, y = 1.0, (height - bh) / 2
        nub_w = 3.0
        # outline
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
        cr.set_line_width(1.5)
        _rounded(cr, x + 0.75, y + 0.75, bw - 1.5, bh - 1.5, bh * 0.28)
        cr.stroke()
        # nub
        nh = bh * 0.4
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.55)
        _rounded(cr, x + bw, y + (bh - nh) / 2, nub_w, nh, 1.5)
        cr.fill()
        # fill
        inset = 3.0
        iw, ih = bw - 2 * inset, bh - 2 * inset
        fill_w = max(0.0, min(100.0, self._displayed) / 100.0 * iw)
        rgb = COLORS.get(self._colour)
        if rgb is not None and fill_w > 0.5:
            cr.save()
            _rounded(cr, x + inset, y + inset, fill_w, ih, ih * 0.3)
            cr.clip_preserve()
            cr.set_source_rgb(*rgb)
            cr.fill()
            if self._charging:
                band = max(iw * 0.35, 8.0)
                bx = x + inset - band + self._phase * (fill_w + band)
                cr.rectangle(bx, y, band, bh)
                cr.clip()
                import cairo
                grad = cairo.LinearGradient(bx, 0, bx + band, 0)
                grad.add_color_stop_rgba(0, 1, 1, 1, 0)
                grad.add_color_stop_rgba(0.5, 1, 1, 1, 0.55)
                grad.add_color_stop_rgba(1, 1, 1, 1, 0)
                cr.set_source(grad)
                cr.paint()
            cr.restore()
        if self._charging:
            self._draw_bolt(cr, x + bw / 2, y + bh / 2, bh)
        # caption
        layout = self._layout()
        tw, th = layout.get_pixel_size()
        cr.move_to(x + bw + nub_w + 8, (height - th) / 2)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
        PangoCairo.show_layout(cr, layout)

    @staticmethod
    def _draw_bolt(cr, cx: float, cy: float, h: float) -> None:
        s = h * 0.62
        pts = [(0.15, -0.5), (-0.3, 0.1), (0.0, 0.1), (-0.15, 0.5), (0.3, -0.1), (0.0, -0.1)]
        cr.new_path()
        for i, (px, py) in enumerate(pts):
            (cr.move_to if i == 0 else cr.line_to)(cx + px * s, cy + py * s)
        cr.close_path()
        cr.set_source_rgba(0.1, 0.1, 0.1, 0.85)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(0.8)
        cr.stroke()
