"""Keyboard > Keymap: a clickable 84-key board; picking a keycode writes it immediately."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from peripheralhub.ui.battery import BatteryWidget  # noqa: E402
from peripheralhub.ui.pages.kb_common import KB_TABS, GatedView, to_state  # noqa: E402
from peripheralhub.ui.pages.kb_lighting import via_hs_to_rgb  # noqa: E402
from peripheralhub.wd75.device import Wd75State  # noqa: E402
from peripheralhub.wd75.keycodes import (  # noqa: E402
    CATALOG, CATEGORIES, is_dangerous, label, layer_target, search,
)
from peripheralhub.wd75.layout import load_layout  # noqa: E402
from peripheralhub.wd75.snapshot import Snapshot, factory_snapshot, restore_plan  # noqa: E402
from peripheralhub.wd75.via import ViaError  # noqa: E402

if TYPE_CHECKING:
    from peripheralhub.core.registry import DeviceStatus
    from peripheralhub.ui.window import AppContext

BASE_LAYERS = (0, 2)
DEFAULT_LAYER_NAMES = ["Windows", "Windows Fn", "Mac", "Mac Fn", "Layer 5"]
LAYERS, ROWS, COLS = 5, 6, 16
PX_PER_UNIT = 52
GAP = 3
SOLID_COLOR_EFFECT = 1  # "Solid Color" in Womier's V1 naming
# (display name, QMK base). LT also carries a tap key.
_LAYER_KINDS = (("MO (hold)", 0x5220), ("TG (toggle)", 0x5260), ("TO (go to)", 0x5200),
                ("TT (tap-toggle)", 0x52C0), ("OSL (one-shot)", 0x5280), ("DF (default)", 0x5240),
                ("LT (hold / tap key)", 0x4000))
_BASIC_BY_NAME = {k.name: k.code for k in CATALOG if k.code <= 0xFF}
_CSS = """
.phub-key { padding: 0 2px; min-width: 0; min-height: 0; font-size: 10px; }
.phub-key.dim { opacity: 0.45; }
.phub-key.sel { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
"""


class UndoStack:
    def __init__(self) -> None:
        self._items: list[tuple[int, int, int, int, int]] = []

    def push(self, layer: int, row: int, col: int, old: int, new: int) -> None:
        self._items.append((layer, row, col, old, new))

    def undo(self) -> tuple[int, int, int, int] | None:
        """The write (layer, row, col, code) that restores the most recent edit."""
        if not self._items:
            return None
        layer, row, col, old, _new = self._items.pop()
        return layer, row, col, old

    def peek(self) -> tuple[int, int, int, int] | None:
        if not self._items:
            return None
        layer, row, col, old, _new = self._items[-1]
        return layer, row, col, old

    def drop(self) -> None:
        if self._items:
            self._items.pop()

    def clear(self) -> None:
        self._items.clear()

    def __bool__(self) -> bool:
        return bool(self._items)


def undo_last(stack: UndoStack, write) -> bool:
    """Run the newest undo write; the entry is only dropped when the write succeeded."""
    w = stack.peek()
    if w is None or not write(*w):
        return False
    stack.drop()
    return True


def needs_last_fn_warning(keymap, layer: int, row: int, col: int, new_code: int) -> bool:
    """True when the old code reaches a layer and no other base-layer key (layers 0 and 2) reaches it."""
    target = layer_target(keymap[layer][row][col])
    if target is None or layer_target(new_code) == target:
        return False
    for base in BASE_LAYERS:
        for r, line in enumerate(keymap[base]):
            for c, code in enumerate(line):
                if (base, r, c) != (layer, row, col) and layer_target(code) == target:
                    return False
    return True


def key_tint(rgb: dict | None) -> tuple[int, int, int] | None:
    """Colour for keycap tint: only a Solid Color effect has a single known colour."""
    if rgb and rgb.get("effect") == SOLID_COLOR_EFFECT:
        return via_hs_to_rgb(int(rgb.get("hue", 0)), int(rgb.get("sat", 0)))
    return None


class KeymapPage:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self._layout = load_layout()
        self._km: list[list[list[int]]] | None = None
        self._layer = 0
        self._sel: tuple[int, int] | None = None
        self._undo = UndoStack()
        self._buttons: dict[tuple[int, int], Gtk.Button] = {}
        self._last_width = -1
        self._units_w = max(k.x + k.w for k in self._layout)
        self._units_h = max(k.y + k.h for k in self._layout)
        self._css = Gtk.CssProvider()
        self._tint_css = Gtk.CssProvider()
        self._css.load_from_string(_CSS)
        for p, prio in ((self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION),
                        (self._tint_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)):
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), p, prio)

        self._battery = BatteryWidget()
        self._battery.set_halign(Gtk.Align.START)
        self._battery.set_margin_top(12)
        self._battery.set_margin_start(12)

        # header
        self._layer_dd = Gtk.DropDown(valign=Gtk.Align.CENTER)
        self._fill_layers()
        self._layer_dd.connect("notify::selected", self._on_layer)
        rename = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Rename layer", valign=Gtk.Align.CENTER)
        rename.connect("clicked", self._on_rename)
        self._undo_btn = Gtk.Button(label="Undo", valign=Gtk.Align.CENTER, sensitive=False)
        self._undo_btn.connect("clicked", self._on_undo)
        self._restore_menu = Gio.Menu()
        self._restore_menu.append("This key", "kmap.restore-key")
        self._restore_menu.append("This layer", "kmap.restore-layer")
        self._restore_menu.append("Whole keyboard", "kmap.restore-all")
        restore = Gtk.MenuButton(label="Restore defaults", menu_model=self._restore_menu, valign=Gtk.Align.CENTER)
        more_menu = Gio.Menu()
        more_menu.append("Erase to firmware defaults (VIA reset)", "kmap.erase")
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=more_menu, valign=Gtk.Align.CENTER,
                              tooltip_text="More")
        header = Gtk.Box(spacing=8, margin_top=12, margin_start=12, margin_end=12)
        header.append(Gtk.Label(label="Layer"))
        header.append(self._layer_dd)
        header.append(rename)
        header.append(Gtk.Box(hexpand=True))
        header.append(self._undo_btn)
        header.append(restore)
        header.append(more)

        self._actions = Gio.SimpleActionGroup()
        for name, fn in (("restore-key", lambda *_: self._confirm_restore("key")),
                         ("restore-layer", lambda *_: self._confirm_restore("layer")),
                         ("restore-all", lambda *_: self._confirm_restore("all")),
                         ("erase", lambda *_: self._confirm_erase())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", fn)
            self._actions.add_action(act)
        self._key_action = self._actions.lookup_action("restore-key")
        self._key_action.set_enabled(False)

        # board
        self._fixed = Gtk.Fixed()
        self._scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                            vscrollbar_policy=Gtk.PolicyType.NEVER,
                                            margin_start=12, margin_end=12, margin_top=12)
        self._scroller.set_child(self._fixed)
        self._scroller.add_tick_callback(self._on_tick)
        for k in self._layout:
            b = Gtk.Button()
            b.add_css_class("phub-key")
            b.set_child(Gtk.Label(ellipsize=3, wrap=True, lines=2, max_width_chars=8, justify=Gtk.Justification.CENTER))
            b.connect("clicked", self._on_key, k.row, k.col)
            self._fixed.put(b, 0, 0)
            self._buttons[(k.row, k.col)] = b

        self._hint = Gtk.Label(label="Click a key to change it. Changes are written to the keyboard immediately.",
                               xalign=0, margin_start=12, margin_top=8)
        self._hint.add_css_class("dim-label")
        self._error = Gtk.Label(wrap=True, visible=False, xalign=0, margin_start=12, margin_top=8)
        self._error.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for w in (header, self._scroller, self._hint, self._error):
            content.append(w)
        self._pick_pop = self._build_picker()
        self._gate = GatedView(ctx, content, self._resync)
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.insert_action_group("kmap", self._actions)
        self._root.append(self._battery)
        self._root.append(self._gate)
        self._rescale(800)

    # -- helpers
    def _names(self) -> list[str]:
        names = list(self._ctx.settings.get("wd75.layer_names", None) or DEFAULT_LAYER_NAMES)
        return (names + DEFAULT_LAYER_NAMES[len(names):])[:LAYERS]

    def _fill_layers(self) -> None:
        sel = self._layer
        self._layer_dd.set_model(Gtk.StringList.new(self._names()))
        self._layer_dd.set_selected(sel)

    def widget(self) -> Gtk.Widget:
        return self._root

    def widget_root(self):
        return self._root.get_root()

    def on_status(self, s: DeviceStatus) -> None:
        self._battery.set_reading(s.battery, time.time())
        state = to_state(s)
        self._gate.set_state(state, self._ctx.wd75.connection)
        if state is Wd75State.READY:
            if self._km is None:
                self._load()
        else:
            self._km = None
            self._undo_btn.set_sensitive(False)

    def _resync(self) -> None:
        self._km = None
        for s in self._ctx.registry.statuses():
            if s.id == "wd75":
                self.on_status(s)

    def _asleep(self) -> None:
        self._km = None
        self._undo_btn.set_sensitive(False)
        self._pick_pop.popdown()
        self._gate.set_state(Wd75State.ASLEEP, self._ctx.wd75.connection)

    def _fail(self, e: Exception) -> None:
        """A timed-out or failed write is never retried blindly: show the banner, user retries."""
        self._asleep()

    # -- board drawing
    def _on_tick(self, _w, _clock) -> bool:
        w = self._scroller.get_width()
        if w and w != self._last_width:
            self._rescale(w)
        return GLib.SOURCE_CONTINUE

    def _rescale(self, avail: int) -> None:
        self._last_width = avail
        unit = max(18.0, min(float(PX_PER_UNIT), (avail - 4) / self._units_w))
        for k in self._layout:
            b = self._buttons[(k.row, k.col)]
            b.set_size_request(max(1, round(k.w * unit - GAP)), max(1, round(k.h * unit - GAP)))
            self._fixed.move(b, round(k.x * unit), round(k.y * unit))
        self._scroller.set_min_content_height(round(self._units_h * unit))

    def _refresh_keys(self) -> None:
        names = self._names()
        for (r, c), b in self._buttons.items():
            code = self._km[self._layer][r][c] if self._km else 0
            lab = b.get_child()
            lab.set_label(label(code, names))
            b.set_tooltip_text(f"0x{code:04X}")
            (b.add_css_class if code == 0x0001 else b.remove_css_class)("dim")
            (b.add_css_class if self._sel == (r, c) else b.remove_css_class)("sel")
        self._update_tint()
        self._undo_btn.set_sensitive(bool(self._undo) and self._km is not None)

    def _update_tint(self) -> None:
        tint = key_tint(self._ctx.settings.get("wd75.rgb", None))
        if tint is None:
            css = ".phub-key { background-image: none; }"
        else:
            r, g, b = tint
            css = (f".phub-key {{ background-image: linear-gradient(rgba({r},{g},{b},0.28), "
                   f"rgba({r},{g},{b},0.28)); }}")
        self._tint_css.load_from_string(css)

    # -- device I/O
    def _load(self) -> None:
        try:
            km = self._ctx.wd75.via.read_keymap(LAYERS, ROWS, COLS)
        except (ViaError, OSError, AttributeError):
            self._asleep()
            return
        self._km = km
        self._error.set_visible(False)
        self._refresh_keys()

    def _write(self, layer: int, row: int, col: int, code: int, *, record: bool = True) -> bool:
        if self._km is None:
            return False
        old = self._km[layer][row][col]
        try:
            self._ctx.wd75.write_keycode(layer, row, col, code)
        except (ViaError, OSError) as e:
            self._fail(e)
            return False
        self._km[layer][row][col] = code
        if record:
            self._undo.push(layer, row, col, old, code)
        self._refresh_keys()
        return True

    def _on_undo(self, _b) -> None:
        w = self._undo.peek()
        if w is None or self._km is None:
            return
        if undo_last(self._undo, lambda *a: self._write(*a, record=False)):
            self._layer = w[0]
            self._layer_dd.set_selected(w[0])
            self._refresh_keys()

    # -- events
    def _on_layer(self, *_a) -> None:
        self._layer = self._layer_dd.get_selected()
        self._refresh_keys()

    def _on_key(self, btn: Gtk.Button, row: int, col: int) -> None:
        if self._km is None:
            return
        self._sel = (row, col)
        self._key_action.set_enabled(True)
        self._refresh_keys()
        self._pick_pop.popdown()
        self._pick_pop.unparent()
        self._pick_pop.set_parent(btn)
        self._search.set_text("")
        self._pick_pop.popup()

    def _on_rename(self, _b) -> None:
        names = self._names()
        entry = Gtk.Entry(text=names[self._layer], activates_default=True)
        dlg = Adw.AlertDialog(heading="Rename layer", body=f"Layer {self._layer}")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")

        def done(_d, response: str) -> None:
            text = entry.get_text().strip()
            if response != "ok" or not text:
                return
            names[self._layer] = text
            self._ctx.settings.set("wd75.layer_names", names)
            self._fill_layers()
            self._refresh_keys()

        dlg.connect("response", done)
        dlg.present(self._root.get_root())

    # -- picker
    def _code_button(self, code: int, text: str, tip: str) -> Gtk.Button:
        b = Gtk.Button(label=text or "(none)", tooltip_text=tip)
        b.connect("clicked", lambda _b: self._choose(code))
        return b

    def _flow(self, codes) -> Gtk.ScrolledWindow:
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=2,
                           max_children_per_line=6, homogeneous=True, valign=Gtk.Align.START, row_spacing=4, column_spacing=4,
                           margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        names = self._names()
        for k in codes:
            flow.append(self._code_button(k.code, label(k.code, names) if k.category == "Layers" else k.label,
                                          f"{k.name}  0x{k.code:04X}"))
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(flow)
        return sw

    def _build_picker(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        self._stack = Gtk.Stack(hexpand=True)
        for cat in CATEGORIES:
            self._stack.add_titled(self._flow([k for k in CATALOG if k.category == cat]), cat, cat)
        self._stack.add_titled(self._layer_builder(), "Layer key", "Layer key")
        self._results = Gtk.Box()
        self._stack.add_named(self._results, "__search")
        self._cat_before_search = "Basic"
        sidebar = Gtk.StackSidebar(stack=self._stack, vexpand=True)
        sidebar.set_size_request(130, -1)
        self._search = Gtk.SearchEntry(placeholder_text="Search keycodes (e.g. RGB_TOG, volume)")
        self._search.connect("search-changed", self._on_search)
        body = Gtk.Box(vexpand=True)
        body.append(sidebar)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self._stack)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_bottom=8,
                      margin_start=8, margin_end=8)
        box.set_size_request(620, 360)
        box.append(self._search)
        box.append(body)
        pop.set_child(box)
        return pop

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        q = entry.get_text()
        cur = self._stack.get_visible_child_name()
        if not q.strip():
            if cur == "__search":
                self._stack.set_visible_child_name(self._cat_before_search)
            return
        if cur != "__search":
            self._cat_before_search = cur or "Basic"
        old = self._stack.get_child_by_name("__search")
        self._stack.remove(old)
        self._results = self._flow(search(q)[:120])
        self._stack.add_named(self._results, "__search")
        self._stack.set_visible_child_name("__search")

    def _layer_builder(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_start=12, margin_end=12)
        self._kind = Gtk.DropDown(model=Gtk.StringList.new([n for n, _b in _LAYER_KINDS]))
        self._lspin = Gtk.SpinButton.new_with_range(0, LAYERS - 1, 1)
        self._tap = Gtk.Entry(text="KC_SPC", placeholder_text="Tap key, e.g. KC_SPC")
        self._tap_err = Gtk.Label(xalign=0, visible=False)
        self._tap_err.add_css_class("error")
        apply_btn = Gtk.Button(label="Use this key", halign=Gtk.Align.START)
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_layer_apply)
        for caption, w in (("Kind", self._kind), ("Layer", self._lspin), ("Tap key (LT only)", self._tap)):
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label=caption, xalign=0, width_chars=16)
            row.append(lbl)
            row.append(w)
            box.append(row)
        box.append(self._tap_err)
        box.append(apply_btn)
        return box

    def _on_layer_apply(self, _b) -> None:
        base = _LAYER_KINDS[self._kind.get_selected()][1]
        n = int(self._lspin.get_value())
        if base == 0x4000:
            tap = _BASIC_BY_NAME.get(self._tap.get_text().strip().upper())
            if tap is None:
                self._tap_err.set_label("Unknown tap key. Use a basic key name such as KC_SPC.")
                self._tap_err.set_visible(True)
                return
            self._tap_err.set_visible(False)
            self._choose(base | (n << 8) | tap)
        else:
            self._choose(base | n)

    def _choose(self, code: int) -> None:
        if self._sel is None or self._km is None:
            return
        row, col = self._sel
        layer = self._layer
        self._pick_pop.popdown()
        warnings = []
        if is_dangerous(code):
            warnings.append(f"{label(code)} can wipe keyboard settings or put it into its bootloader.")
        if needs_last_fn_warning(self._km, layer, row, col, code):
            warnings.append("This is the only key that reaches that layer from the base layers. "
                            "Without it you may not be able to reach those keys (you can still Undo or restore).")
        if not warnings:
            self._write(layer, row, col, code)
            return
        self._confirm("Change this key?", "\n\n".join(warnings), "Change key", True,
                      lambda: self._write(layer, row, col, code))

    # -- confirmation dialogs
    def _confirm(self, heading: str, body: str, ok_label: str, destructive: bool, on_ok) -> None:
        dlg = Adw.AlertDialog(heading=heading, body=body)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", ok_label)
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                    else Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: on_ok() if r == "ok" else None)
        dlg.present(self._root.get_root())

    def _current_snapshot(self) -> Snapshot | None:
        try:
            km = self._ctx.wd75.via.read_keymap(LAYERS, ROWS, COLS)
        except (ViaError, OSError, AttributeError) as e:
            self._fail(e)
            return None
        f = factory_snapshot()
        return Snapshot(LAYERS, ROWS, COLS, km, f.macro_buffer, f.rgb, "")

    def _confirm_restore(self, scope: str) -> None:
        if self._km is None:
            return
        kw: dict = {}
        if scope == "key":
            if self._sel is None:
                return
            kw["keys"] = [(self._layer, *self._sel)]
            what = "this key"
        elif scope == "layer":
            kw["layers"] = [self._layer]
            what = f"layer \"{self._names()[self._layer]}\""
        else:
            what = "the whole keyboard"
        target = factory_snapshot()
        cur = self._current_snapshot()
        if cur is None:
            return
        n = len(restore_plan(cur, target, **kw))
        if n == 0:
            self._confirm("Nothing to restore", f"{what.capitalize()} already matches the factory keymap.",
                          "OK", False, lambda: None)
            return

        def go() -> None:
            try:
                self._ctx.wd75.restore(target, **kw)
            except (ViaError, OSError) as e:
                self._fail(e)
                return
            self._undo.clear()
            self._load()

        self._confirm("Restore factory keymap?",
                      f"{n} key{'s' if n != 1 else ''} on {what} will be set back to the factory keymap. "
                      "A backup of the current keymap is saved first.", "Restore", True, go)

    def _confirm_erase(self) -> None:
        if self._km is None:
            return

        def go() -> None:
            wd = self._ctx.wd75
            try:
                wd.reset_keymap()
            except (ViaError, OSError, AttributeError) as e:
                self._fail(e)
                return
            self._undo.clear()
            self._load()

        self._confirm("Erase to firmware defaults?",
                      "This resets every layer to the keymap compiled into the firmware (VIA reset). "
                      "It may differ from the factory keymap Womier shipped. A backup is saved first.",
                      "Erase keymap", True, go)


KB_TABS.append(("keymap", "Keymap", "input-keyboard-symbolic", lambda ctx: KeymapPage(ctx)))
