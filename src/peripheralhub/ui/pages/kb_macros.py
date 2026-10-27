"""Keyboard > Macros: edit the 16 stored macros as steps, record typing, and watch the storage meter."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from peripheralhub.ui.battery import BatteryWidget  # noqa: E402
from peripheralhub.ui.keymap_hid import evdev_to_hid  # noqa: E402
from peripheralhub.ui.pages.kb_common import KB_TABS, GatedView, to_state  # noqa: E402
from peripheralhub.wd75.device import Wd75State  # noqa: E402
from peripheralhub.wd75.keycodes import CATALOG, label  # noqa: E402
from peripheralhub.wd75.macros import (  # noqa: E402
    Delay, Down, MacroBufferFull, Step, Tap, Text, Up, decode_buffer, encode_buffer, encoded_size,
)
from peripheralhub.wd75.via import ViaError  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

GAP_MS = 50  # recorded pauses longer than this become a Wait step
HINT = "Assign a macro to a key on the Keymap page (Macros category)."
EXPERIMENTAL = "Experimental: keycodes above 0xFF are not verified on the firmware."
_BASIC = [k for k in CATALOG if 0 < k.code <= 0xFF]


def validate_text(text: str) -> str | None:
    """None when every character can be typed by the macro engine (printable ASCII, newline, tab)."""
    bad = sorted({c for c in text if not (0x20 <= ord(c) <= 0x7E or c in "\n\t")})
    if not bad:
        return None
    shown = ", ".join(repr(c)[1:-1] if ord(c) < 0x20 or c == "\x7f" else c for c in bad[:5])
    return f"Can't be typed by the keyboard: {shown}"


def validate_delay(text: str) -> str | None:
    t = text.strip()
    if not t.isascii() or not t.isdigit() or int(t) <= 0 or t != text:
        return "Enter a whole number of milliseconds greater than 0."
    return None


def describe(step: Step) -> str:
    if isinstance(step, Text):
        shown = step.text.replace("\n", "↵").replace("\t", "⇥")
        return f'Type "{shown}"'
    if isinstance(step, Tap):
        return f"Tap {label(step.keycode)}"
    if isinstance(step, Down):
        return f"Hold {label(step.keycode)}"
    if isinstance(step, Up):
        return f"Release {label(step.keycode)}"
    if isinstance(step, Delay):
        return f"Wait {step.ms} ms"
    return "Unknown step"


@dataclass
class Item:
    """An editable step; `draft` holds a Wait entry's text while it is not a valid number."""
    step: Step
    draft: str | None = None

    def error(self) -> str | None:
        if isinstance(self.step, Text):
            return validate_text(self.step.text)
        if isinstance(self.step, Delay):
            return validate_delay(self.draft if self.draft is not None else str(self.step.ms))
        return None


class Recorder:
    """Turns timestamped key events into steps: press+release with nothing between is a Tap."""

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self._held: set[int] = set()
        self._last = 0
        self._started = False

    def _gap(self, t_ms: int) -> None:
        if self._started and t_ms - self._last > GAP_MS:
            self.steps.append(Delay(t_ms - self._last))
        self._started = True

    def event(self, hid: int, pressed: bool, t_ms: int) -> None:
        if pressed:
            if hid in self._held:
                return  # auto-repeat
            self._gap(t_ms)
            self._held.add(hid)
            self.steps.append(Down(hid))
        else:
            if hid not in self._held:
                return
            self._gap(t_ms)
            self._held.discard(hid)
            if self.steps and self.steps[-1] == Down(hid):
                self.steps[-1] = Tap(hid)
            else:
                self.steps.append(Up(hid))
        self._last = t_ms

    def finish(self, t_ms: int) -> list[Step]:
        for hid in sorted(self._held):
            self.steps.append(Up(hid))
        self._held.clear()
        return self.steps


def _clear(box: Gtk.Widget) -> None:
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class MacrosPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._loaded = False
        self._dirty = False
        self._busy = False
        self._size = 1048
        self._count = 16
        self._items: list[list[Item]] = [[] for _ in range(16)]
        self._sel = 0
        self._rec: Recorder | None = None
        self._rec_ctl = None
        self._rec_win = None
        self._loading = False

        self._battery = BatteryWidget()
        self._battery.set_halign(Gtk.Align.START)
        self._battery.set_margin_top(12)
        self._battery.set_margin_start(12)

        self._slots = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._slots.add_css_class("navigation-sidebar")
        self._slots.connect("row-selected", self._on_slot)
        self._slot_rows: list[Adw.ActionRow] = []
        for i in range(16):
            row = Adw.ActionRow(title=f"M{i}", subtitle="Empty")
            row.set_subtitle_lines(1)
            self._slots.append(row)
            self._slot_rows.append(row)
        side = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, width_request=230)
        side.set_child(self._slots)

        self._steps = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._empty = Gtk.Label(label="No steps yet. Add one below or press Record.", margin_top=12, margin_bottom=12)
        self._empty.add_css_class("dim-label")
        self._steps.set_placeholder(self._empty)
        steps_scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        steps_scroll.set_child(self._steps)

        add = Gtk.Box(spacing=6)
        for text, factory in (("Text", lambda: Text("")), ("Tap", lambda: Tap(0x04)),
                              ("Hold", lambda: Down(0x04)), ("Release", lambda: Up(0x04)),
                              ("Wait", lambda: Delay(100))):
            b = Gtk.Button(label=f"+ {text}")
            b.connect("clicked", self._on_add, factory)
            add.append(b)
        self._record = Gtk.ToggleButton(label="Record", halign=Gtk.Align.END, hexpand=True)
        self._record.connect("toggled", self._on_record)
        add.append(self._record)

        self._meter = Gtk.LevelBar(min_value=0, max_value=1048, hexpand=True, valign=Gtk.Align.CENTER)
        self._meter.add_offset_value("low", 0.7 * 1048)
        self._meter.add_offset_value("high", 0.9 * 1048)
        self._meter.add_offset_value("full", 1048)
        self._meter_label = Gtk.Label(xalign=0)
        self._save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        self._save.add_css_class("suggested-action")
        self._save.connect("clicked", self._on_save)
        self._unsaved = Gtk.Label(label="Unsaved changes", visible=False)
        self._unsaved.add_css_class("warning")
        foot = Gtk.Box(spacing=12)
        foot.append(self._meter_label)
        foot.append(self._meter)
        foot.append(self._unsaved)
        foot.append(self._save)
        self._error = Gtk.Label(wrap=True, visible=False, xalign=0)
        self._error.add_css_class("error")
        hint = Gtk.Label(label=HINT, xalign=0, wrap=True)
        hint.add_css_class("dim-label")

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True,
                        margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self._title = Gtk.Label(xalign=0)
        self._title.add_css_class("title-3")
        for w in (self._title, steps_scroll, add, foot, self._error, hint):
            right.append(w)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.append(side)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(right)

        self._gate = GatedView(ctx, content, self._resync)
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.append(self._battery)
        self._root.append(self._gate)
        self._root.connect("unrealize", lambda _w: self._stop_recording())
        self._root.connect("unmap", lambda _w: self._stop_recording())
        self._slots.select_row(self._slot_rows[0])
        self._rebuild()

    # -- DevicePage-like interface
    def widget(self) -> Gtk.Widget:
        return self._root

    def on_status(self, s: DeviceStatus) -> None:
        self._battery.set_reading(s.battery, time.time())
        state = to_state(s)
        self._gate.set_state(state, self._ctx.wd75.connection)
        if state is not Wd75State.READY:
            self._stop_recording()
        if state is Wd75State.READY:
            if not self._loaded:
                self._load()
        else:
            self._loaded = False
        self._sync()

    def _resync(self) -> None:
        self._loaded = False
        for s in self._ctx.registry.statuses():
            if s.id == "wd75":
                self.on_status(s)

    def _asleep(self) -> None:
        self._stop_recording()
        self._loaded = False
        self._gate.set_state(Wd75State.ASLEEP, self._ctx.wd75.connection)
        self._sync()

    # -- device I/O
    def _load(self) -> None:
        if self._dirty:
            self._loaded = True  # keep unsaved edits across a reconnect
            return
        try:
            via = self._ctx.wd75.via
            self._count = via.macro_count()
            self._size = via.macro_buffer_size()
            buf = via.read_macro_buffer()
        except (ViaError, OSError, AttributeError):
            self._asleep()
            return
        macros = decode_buffer(buf, self._count)
        self._items = [[Item(s) for s in m] for m in macros]
        self._items += [[] for _ in range(16 - len(self._items))]
        self._loaded = True
        self._meter.set_max_value(self._size)
        self._rebuild()

    def _macros(self) -> list[list[Step]]:
        return [[i.step for i in m] for m in self._items[:self._count]]

    def _on_save(self, _b) -> None:
        if not self._can_save():
            return
        self._stop_recording()
        try:
            buf = encode_buffer(self._macros(), self._size)
        except (MacroBufferFull, ValueError) as e:
            self._show_error(str(e))
            return
        self._busy = True
        try:
            self._ctx.wd75.write_macros(buf)
        except (ViaError, OSError):
            self._busy = False
            self._asleep()  # a timed-out write is never retried automatically
            return
        self._busy = False
        self._error.set_visible(False)
        self._dirty = False
        self._sync()

    def _show_error(self, text: str) -> None:
        self._error.set_label(text)
        self._error.set_visible(True)

    # -- state
    def _used(self) -> int:
        return encoded_size(self._macros())

    def _has_errors(self) -> bool:
        return any(i.error() for m in self._items for i in m)

    def _can_save(self) -> bool:
        return (self._dirty and self._gate.state is Wd75State.READY and not self._busy
                and not self._has_errors() and self._used() <= self._size)

    def _mark(self) -> None:
        self._dirty = True
        self._sync()

    def _sync(self) -> None:
        used = self._used()
        self._meter.set_value(min(used, self._size))
        over = used > self._size
        self._meter_label.set_label(f"{used} / {self._size} bytes" + (" (full)" if over else ""))
        if over:
            self._meter_label.add_css_class("error")
        else:
            self._meter_label.remove_css_class("error")
        self._unsaved.set_visible(self._dirty)
        self._save.set_sensitive(self._can_save())
        for i, row in enumerate(self._slot_rows):
            row.set_subtitle(GLib.markup_escape_text(self._preview(i)))

    def _preview(self, i: int) -> str:
        steps = self._items[i]
        if not steps:
            return "Empty"
        text = ", ".join(describe(s.step) for s in steps[:3])
        return text + ("…" if len(steps) > 3 else "")

    # -- step list
    def _cur(self) -> list[Item]:
        return self._items[self._sel]

    def _on_slot(self, _lb, row) -> None:
        if row is None or self._loading:
            return
        self._stop_recording()
        self._sel = self._slot_rows.index(row)
        self._rebuild()

    def _rebuild(self) -> None:
        self._loading = True
        self._title.set_label(f"M{self._sel}")
        _clear(self._steps)
        items = self._cur()
        for idx, item in enumerate(items):
            self._steps.append(self._row(idx, item, len(items)))
        if items:
            self._steps.add_css_class("boxed-list")
        else:
            self._steps.remove_css_class("boxed-list")
        self._loading = False
        self._sync()

    def _row(self, idx: int, item: Item, n: int) -> Gtk.Widget:
        step = item.step
        row = Adw.ActionRow(title={Text: "Type text", Tap: "Tap", Down: "Hold", Up: "Release",
                                   Delay: "Wait (ms)"}.get(type(step), "Unknown step (kept)"))
        note = Gtk.Label(xalign=0, wrap=True, visible=False)
        note.add_css_class("error")
        if isinstance(step, Text):
            tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, width_request=280,
                              top_margin=6, bottom_margin=6, left_margin=6, right_margin=6)
            tv.get_buffer().set_text(step.text)
            tv.get_buffer().connect("changed", self._on_text, item, note)
            frame = Gtk.Frame(valign=Gtk.Align.CENTER)
            frame.set_child(tv)
            row.add_suffix(frame)
        elif isinstance(step, Delay):
            ent = Gtk.Entry(text=item.draft if item.draft is not None else str(step.ms),
                            valign=Gtk.Align.CENTER, width_chars=8, input_purpose=Gtk.InputPurpose.DIGITS)
            ent.connect("changed", self._on_delay, item, note)
            row.add_suffix(ent)
        elif isinstance(step, (Tap, Down, Up)):
            row.add_suffix(self._key_picker(item, row))
            if step.keycode > 0xFF:
                row.set_subtitle(EXPERIMENTAL)
        else:
            row.set_subtitle(f"{len(step.data)} byte(s) preserved as-is")
        self._show_note(item, note)
        if isinstance(step, (Text, Delay)):
            row.add_suffix(note)
        for icon, delta, tip in (("go-up-symbolic", -1, "Move up"), ("go-down-symbolic", 1, "Move down")):
            b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tip)
            b.add_css_class("flat")
            b.set_sensitive(0 <= idx + delta < n)
            b.connect("clicked", self._on_move, idx, delta)
            row.add_suffix(b)
        rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove step")
        rm.add_css_class("flat")
        rm.connect("clicked", self._on_remove, idx)
        row.add_suffix(rm)
        return row

    def _show_note(self, item: Item, note: Gtk.Label) -> None:
        err = item.error()
        note.set_label(err or "")
        note.set_visible(bool(err))

    def _key_picker(self, item: Item, row: Adw.ActionRow) -> Gtk.Widget:
        code = item.step.keycode
        labels = [k.label or k.name for k in _BASIC]
        codes = [k.code for k in _BASIC]
        if code not in codes:
            codes.append(code)
            labels.append(label(code))
        dd = Gtk.DropDown(model=Gtk.StringList.new(labels), enable_search=True, valign=Gtk.Align.CENTER)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        dd.set_selected(codes.index(code))

        def changed(d, _p) -> None:
            if self._loading:
                return
            new = codes[d.get_selected()]
            item.step = type(item.step)(new)
            row.set_subtitle(EXPERIMENTAL if new > 0xFF else "")
            self._mark()

        dd.connect("notify::selected", changed)
        return dd

    def _on_text(self, buf: Gtk.TextBuffer, item: Item, note: Gtk.Label) -> None:
        if self._loading:
            return
        item.step = Text(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
        self._show_note(item, note)
        self._mark()

    def _on_delay(self, ent: Gtk.Entry, item: Item, note: Gtk.Label) -> None:
        if self._loading:
            return
        text = ent.get_text()
        item.draft = text
        if validate_delay(text) is None:
            item.step = Delay(int(text))
            item.draft = None
        self._show_note(item, note)
        self._mark()

    def _on_add(self, _b, factory) -> None:
        self._cur().append(Item(factory()))
        self._mark()
        self._rebuild()

    def _on_remove(self, _b, idx: int) -> None:
        del self._cur()[idx]
        self._mark()
        self._rebuild()

    def _on_move(self, _b, idx: int, delta: int) -> None:
        items = self._cur()
        items[idx], items[idx + delta] = items[idx + delta], items[idx]
        self._mark()
        self._rebuild()

    # -- recording
    def _on_record(self, btn: Gtk.ToggleButton) -> None:
        if btn.get_active():
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        win = self._root.get_root()
        if self._rec is not None:
            return
        if win is None:
            self._record.set_active(False)
            return
        self._rec = Recorder()
        ctl = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        ctl.connect("key-pressed", self._on_key, True)
        ctl.connect("key-released", self._on_key, False)
        win.add_controller(ctl)
        self._rec_ctl, self._rec_win = ctl, win
        self._record.set_label("Stop recording")

    def _on_key(self, _ctl, *args) -> bool:
        _keyval, keycode, _state, pressed = args
        hid = evdev_to_hid(keycode - 8)
        if self._rec is None or hid is None or not self._root.get_mapped():
            return False
        self._rec.event(hid, pressed, GLib.get_monotonic_time() // 1000)
        return True

    def _stop_recording(self) -> None:
        rec, self._rec = self._rec, None
        if self._rec_win is not None and self._rec_ctl is not None:
            self._rec_win.remove_controller(self._rec_ctl)
        self._rec_ctl = self._rec_win = None
        if self._record.get_active():
            self._record.set_active(False)
        self._record.set_label("Record")
        if rec is None:
            return
        steps = rec.finish(GLib.get_monotonic_time() // 1000)
        if steps:
            self._cur().extend(Item(s) for s in steps)
            self._mark()
            self._rebuild()


KB_TABS.append(("macros", "Macros", "media-record-symbolic", lambda ctx: MacrosPage(ctx)))
