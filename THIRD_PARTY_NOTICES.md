# Third-party notices

PeripheralHub for Omarchy is licensed under GPL-3.0-or-later (see [LICENSE](LICENSE)), except for the data files listed under "Bundled files" below.

## Bundled files

### Womier WD75 V2 keyboard definition

- **Files:** `src/peripheralhub/wd75/data/WD75_V2.json`
- **Source:** Womier's VIA keyboard definition for the WD75 V2.
- **License:** Womier did not publish a license with this file. It remains Womier's and is **not** covered by this project's GPL license. It is included only so the app can work with that keyboard.

If you are the rights holder and want it removed, please open an issue.

### WD75 factory snapshot

- **Files:** `src/peripheralhub/wd75/data/factory-snapshot.json`, `tests/data/factory-snapshot.json`
- **Source:** a read-out of the factory keymap and lighting values from a WD75 V2, used to restore defaults. Its keymap reflects the keyboard's firmware defaults, which may belong to Womier.

## Works this project is based on

### PeripheralHub for Windows

- **Author:** Chad Fiaschetti ([@chad-fiaschetti](https://github.com/chad-fiaschetti))
- **Use:** this project is a Linux port and extension of the original C#/WPF app. Its concept and feature design, and parts of its VIA logic such as the macro buffer format, come from that app. Used with the author's permission. None of its source files are included here.

### OpenRazer

- **Project:** <https://github.com/openrazer/openrazer>
- **License:** GPL-2.0-or-later
- **Use:** `src/peripheralhub/basilisk/` follows OpenRazer's documented Razer report layouts and device values, as recorded in `protocol.py`. No OpenRazer files are included, and its kernel driver isn't required. This project is under GPL-3.0-or-later in part so that it stays compatible with OpenRazer's license.

### QMK and VIA

- **Projects:** <https://github.com/qmk/qmk_firmware>, <https://github.com/the-via>
- **Use:** the keycode ranges and VIA protocol commands are implemented so the app can talk to keyboards running this firmware. No QMK or VIA source files are included.

## Runtime dependencies (not bundled)

These are installed separately and keep their own licenses. Check each project for its current terms.

| Component | Used for |
|---|---|
| Python | Runtime |
| GTK 4, libadwaita, PyGObject | User interface |
| Hyprland | Monitor control, through `hyprctl` |
| UPower | Bluetooth keyboard battery |
| libnotify (`notify-send`) | Low-battery notifications |
| [HeadsetControl](https://github.com/Sapd/HeadsetControl) (optional) | Headset battery |

## Trademarks

Womier, Razer, Basilisk, SteelSeries, Arctis, Omarchy, and Hyprland are the property of their respective owners. This project isn't affiliated with or endorsed by any of them.
