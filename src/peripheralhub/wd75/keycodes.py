"""QMK/VIA (protocol 12) keycode catalog, labels, search and layer helpers."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

CATEGORIES: tuple[str, ...] = (
    "Basic", "Modifiers", "Navigation", "Function", "Media",
    "Layers", "Macros", "Lighting", "Womier", "Special",
)


@dataclass(frozen=True)
class Keycode:
    code: int
    name: str
    label: str
    category: str


# Range bases (QMK 0.19+ numbering as used by VIA protocol 12).
_MODS_END = 0x1FFF
_MODTAP = 0x2000
_LT = 0x4000
_TO, _MO, _DF, _TG, _OSL, _OSM, _TT = 0x5200, 0x5220, 0x5240, 0x5260, 0x5280, 0x52A0, 0x52C0
_MACRO = 0x7700
_WOMIER = 0x7E00
_LAYER_KINDS = {_TO: "TO", _MO: "MO", _DF: "DF", _TG: "TG", _OSL: "OSL", _TT: "TT"}
_DANGEROUS = frozenset({0x7C00, 0x7C01, 0x7C03})

_WOMIER_NAMES = (
    "Battery Query", "Bluetooth 1", "Bluetooth 2", "Bluetooth 3", "2.4GHz", "Win Lock",
    "RGB On", "RGB Off", "RGB Toggle", "RGB Mode", "RGB Hue", "RGB Brightness+",
    "RGB Brightness-", "RGB Speed+", "RGB Speed-", "Heart Toggle", "Heart Hue",
)


_WOMIER_IDS = ("BATT", "BT1", "BT2", "BT3", "2G4", "WINLK", "RGB_ON", "RGB_OFF", "RGB_TOG",
               "RGB_MODE", "RGB_HUE", "RGB_VAI", "RGB_VAD", "RGB_SPI", "RGB_SPD",
               "HEART_TOG", "HEART_HUE")


def _build() -> list[Keycode]:
    out: list[Keycode] = []

    def add(code: int, name: str, label: str, cat: str) -> None:
        out.append(Keycode(code, name, label, cat))

    add(0x0000, "KC_NO", "", "Special")
    add(0x0001, "KC_TRNS", "▽", "Special")
    for i in range(26):
        add(0x04 + i, f"KC_{chr(65 + i)}", chr(65 + i), "Basic")
    for i, d in enumerate("1234567890"):
        add(0x1E + i, f"KC_{d}", d, "Basic")
    for code, name, lab in [
        (0x2D, "KC_MINUS", "-"), (0x2E, "KC_EQUAL", "="), (0x2F, "KC_LBRC", "["),
        (0x30, "KC_RBRC", "]"), (0x31, "KC_BSLS", "\\"), (0x32, "KC_NUHS", "# (Non-US)"),
        (0x33, "KC_SCLN", ";"), (0x34, "KC_QUOT", "'"), (0x35, "KC_GRV", "`"),
        (0x36, "KC_COMM", ","), (0x37, "KC_DOT", "."), (0x38, "KC_SLSH", "/"),
        (0x64, "KC_NUBS", "\\ (Non-US)"),
    ]:
        add(code, name, lab, "Basic")
    for code, name, lab in [
        (0x28, "KC_ENT", "Enter"), (0x29, "KC_ESC", "Esc"), (0x2A, "KC_BSPC", "Backspace"),
        (0x2B, "KC_TAB", "Tab"), (0x2C, "KC_SPC", "Space"), (0x39, "KC_CAPS", "Caps Lock"),
        (0x46, "KC_PSCR", "Print Screen"), (0x47, "KC_SCRL", "Scroll Lock"),
        (0x48, "KC_PAUS", "Pause"), (0x49, "KC_INS", "Insert"), (0x4A, "KC_HOME", "Home"),
        (0x4B, "KC_PGUP", "Page Up"), (0x4C, "KC_DEL", "Delete"), (0x4D, "KC_END", "End"),
        (0x4E, "KC_PGDN", "Page Down"), (0x4F, "KC_RGHT", "→"), (0x50, "KC_LEFT", "←"),
        (0x51, "KC_DOWN", "↓"), (0x52, "KC_UP", "↑"), (0x65, "KC_APP", "Menu"),
    ]:
        add(code, name, lab, "Navigation")
    for i in range(12):
        add(0x3A + i, f"KC_F{i + 1}", f"F{i + 1}", "Function")
        add(0x68 + i, f"KC_F{i + 13}", f"F{i + 13}", "Function")
    for code, name, lab in [
        (0x53, "KC_NUM", "Num Lock"), (0x54, "KC_PSLS", "Num /"), (0x55, "KC_PAST", "Num *"),
        (0x56, "KC_PMNS", "Num -"), (0x57, "KC_PPLS", "Num +"), (0x58, "KC_PENT", "Num Enter"),
        (0x63, "KC_PDOT", "Num ."),
    ]:
        add(code, name, lab, "Basic")
    for i in range(9):
        add(0x59 + i, f"KC_P{i + 1}", f"Num {i + 1}", "Basic")
    add(0x62, "KC_P0", "Num 0", "Basic")
    for i, m in enumerate(["Ctrl", "Shift", "Alt", "GUI"]):
        add(0xE0 + i, f"KC_L{m.upper()}", f"L{m}", "Modifiers")
        add(0xE4 + i, f"KC_R{m.upper()}", f"R{m}", "Modifiers")
    for code, name, lab in [  # QMK consumer/system block
        (0xA5, "KC_PWR", "Power"), (0xA6, "KC_SLEP", "Sleep"), (0xA7, "KC_WAKE", "Wake"),
        (0xA8, "KC_MUTE", "Mute"), (0xA9, "KC_VOLU", "Volume Up"), (0xAA, "KC_VOLD", "Volume Down"),
        (0xAB, "KC_MNXT", "Next Track"), (0xAC, "KC_MPRV", "Previous Track"),
        (0xAD, "KC_MSTP", "Stop"), (0xAE, "KC_MPLY", "Play/Pause"),
        (0xAF, "KC_MSEL", "Media Select"), (0xB0, "KC_EJCT", "Eject"),
        (0xB1, "KC_MAIL", "Mail"), (0xB2, "KC_CALC", "Calculator"),
        (0xB3, "KC_MYCM", "My Computer"), (0xB4, "KC_WSCH", "Browser Search"),
        (0xB5, "KC_WHOM", "Browser Home"), (0xB6, "KC_WBAK", "Browser Back"),
        (0xB7, "KC_WFWD", "Browser Forward"), (0xB8, "KC_WSTP", "Browser Stop"),
        (0xB9, "KC_WREF", "Browser Refresh"), (0xBA, "KC_WFAV", "Browser Favorites"),
        (0xBB, "KC_MFFD", "Fast Forward"), (0xBC, "KC_MRWD", "Rewind"),
        (0xBD, "KC_BRIU", "Brightness Up"), (0xBE, "KC_BRID", "Brightness Down"),
        (0xBF, "KC_CPNL", "Control Panel"), (0xC0, "KC_ASST", "Assistant"),
        (0xC1, "KC_MCTL", "Mission Control"), (0xC2, "KC_LPAD", "Launchpad"),
    ]:
        add(code, name, lab, "Media")
    # Lighting: backlight, underglow / legacy RGB (0x7820+), RGB Matrix (0x7840+).
    bl = ["BL_ON", "BL_OFF", "BL_TOGG", "BL_DOWN", "BL_UP", "BL_STEP", "BL_BRTG"]
    rgb = ["RGB_TOG", "RGB_MOD", "RGB_RMOD", "RGB_HUI", "RGB_HUD", "RGB_SAI", "RGB_SAD",
           "RGB_VAI", "RGB_VAD", "RGB_SPI", "RGB_SPD"]
    rm = ["RM_ON", "RM_OFF", "RM_TOGG", "RM_NEXT", "RM_PREV", "RM_HUEU", "RM_HUED",
          "RM_SATU", "RM_SATD", "RM_VALU", "RM_VALD", "RM_SPDU", "RM_SPDD"]
    for i, lab in enumerate(["Backlight On", "Backlight Off", "Backlight Toggle",
                             "Backlight Down", "Backlight Up", "Backlight Step",
                             "Backlight Breathing"]):
        add(0x7800 + i, bl[i], lab, "Lighting")
    for i, lab in enumerate(["RGB Toggle", "RGB Mode Next", "RGB Mode Prev", "RGB Hue Up",
                             "RGB Hue Down", "RGB Sat Up", "RGB Sat Down",
                             "RGB Brightness Up", "RGB Brightness Down",
                             "RGB Speed Up", "RGB Speed Down"]):
        add(0x7820 + i, rgb[i], lab, "Lighting")
    for i, lab in enumerate(["RGB Matrix On", "RGB Matrix Off", "RGB Matrix Toggle",
                             "RGB Matrix Mode Next", "RGB Matrix Mode Prev",
                             "RGB Matrix Hue Up", "RGB Matrix Hue Down",
                             "RGB Matrix Sat Up", "RGB Matrix Sat Down",
                             "RGB Matrix Brightness Up", "RGB Matrix Brightness Down",
                             "RGB Matrix Speed Up", "RGB Matrix Speed Down"]):
        add(0x7840 + i, rm[i], lab, "Lighting")
    for n in range(8):
        for base, kind in _LAYER_KINDS.items():
            add(base | n, f"{kind}({n})", f"{kind}({n})", "Layers")
    for n in range(16):
        add(_MACRO + n, f"MACRO({n})", f"M{n}", "Macros")
    for i, lab in enumerate(_WOMIER_NAMES):
        add(_WOMIER + i, f"WOMIER_{_WOMIER_IDS[i]}", lab, "Womier")
    for code, name, lab in [
        (0x7C00, "QK_BOOT", "Bootloader"), (0x7C01, "QK_REBOOT", "Reboot"),
        (0x7C02, "DB_TOGG", "Debug Toggle"), (0x7C03, "EE_CLR", "Clear EEPROM"),
        (0x7C16, "QK_GESC", "Grave Esc"),
    ]:
        add(code, name, lab, "Special")
    return out


CATALOG: tuple[Keycode, ...] = tuple(_build())
_BY_CODE = {k.code: k for k in CATALOG}


def _mod_names(bits: int) -> str:
    side = "R" if bits & 0x10 else "L"
    names = [n for bit, n in ((1, "Ctrl"), (2, "Shift"), (4, "Alt"), (8, "GUI")) if bits & bit]
    return "+".join(side + n for n in names)


def _layer_name(n: int, layer_names: Sequence[str] | None) -> str | None:
    if layer_names is not None and 0 <= n < len(layer_names):
        return layer_names[n]
    return None


def label(code: int, layer_names: Sequence[str] | None = None) -> str:
    """Human-readable keycap text for any 16-bit keycode."""
    if code in _BY_CODE and not (layer_names and _is_layer_key(code)):
        return _BY_CODE[code].label
    if 0x0100 <= code <= _MODS_END:
        inner = label(code & 0xFF)
        return f"{_mod_names((code >> 8) & 0x1F)}+{inner}" if inner else _mod_names((code >> 8) & 0x1F)
    if _MODTAP <= code < _LT:
        return f"MT({_mod_names((code >> 8) & 0x1F)}, {label(code & 0xFF)})"
    if _LT <= code < 0x5000:
        n = (code >> 8) & 0x0F
        return f"LT({_layer_name(n, layer_names) or n}, {label(code & 0xFF)})"
    if _TO <= code <= 0x52DF and (code & 0xFFE0) in (*_LAYER_KINDS, _OSM):
        base, n = code & 0xFFE0, code & 0x1F
        if base == _OSM:
            return f"OSM({_mod_names(n)})"
        name = _layer_name(n, layer_names)
        if name is None:
            return f"{_LAYER_KINDS[base]}({n})"
        prefix = {_MO: "Fn", _TG: "Toggle", _TO: "Go to", _DF: "Default",
                  _OSL: "One-shot", _TT: "Tap-toggle"}[base]
        return f"{prefix} → {name}"
    if _MACRO <= code <= _MACRO + 0x7F:
        return f"M{code - _MACRO}"
    if _WOMIER <= code <= _WOMIER + 0x3F:
        return f"Womier 0x{code:04X} (unknown)"
    return f"0x{code:04X}"


def _is_layer_key(code: int) -> bool:
    return _TO <= code <= 0x52DF and (code & 0xFFE0) in _LAYER_KINDS


def search(query: str) -> list[Keycode]:
    q = query.strip().lower()
    return [k for k in CATALOG if q in k.name.lower() or q in k.label.lower()]


def layer_target(code: int) -> int | None:
    """Layer reached by a MO/TG/TO/TT/OSL/DF/LT keycode, else None."""
    if _LT <= code < 0x5000:
        return (code >> 8) & 0x0F
    if _is_layer_key(code):
        return code & 0x1F
    return None


def is_dangerous(code: int) -> bool:
    """Keycodes that can wipe settings or drop the board into its bootloader."""
    return code in _DANGEROUS
