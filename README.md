# PeripheralHub for Omarchy

A GTK4/libadwaita app for the desk setup:

- **Womier WD75 V2**: lighting (effects, colour, speed, brightness), keymap editor for all 5 layers, macro editor. It works by cable or the 2.4G dongle, using VIA protocol 12.
- **Razer Basilisk V3**: DPI, DPI stages, polling rate, brightness, and built-in effects, plus animated effects the background service drives (breathing, colour cycle, strip gradient, per-zone colours, match keyboard).
- **Displays**: drag-arrange the monitors, and change resolution/refresh, scale and rotation. Every change auto-reverts after 15 s unless you press Keep.
- **Batteries**: animated battery levels for the keyboard and the Arctis Nova 7P headset, plus a low-battery notification.

It also includes a small background service and a `phub` command-line tool.

## Install

```sh
./install.sh
```

It asks for your password once, to install the udev rule that lets your user talk to the keyboard and mouse. The rule is skipped if it's already there. The installer then puts `peripheralhub` and `phub` in `~/.local/bin`, adds the launcher entry and icon, and starts the `peripheralhub` user service. You can re-run it at any time, for example after pulling changes. Pin it in the dock yourself if you want it there.

The app itself never needs root. If the rule is missing, the device pages show an **Allow access** button that installs it via pkexec.

## Command line

```
phub status                          devices, connection, battery
phub battery                         battery levels only
phub snapshot OUT.json               save keymap, lighting and macros
phub restore-factory [--layer N] --yes   put factory keys back (all layers, or one)
phub mouse dpi [VALUE]               show or set DPI (100-26000)
```

## Recovery

- **Keyboard:** hold **Fn+Esc for 3 s** to factory-reset it in firmware. `phub restore-factory --yes` rewrites only keys that differ from the factory snapshot. Before the first write in each session, the app saves a full backup to `~/.local/share/peripheralhub/backups/wd75-<date>.json`. Settings → Keyboard backups opens that folder.
- **Displays:** each Keep backs up `~/.config/hypr/monitors.lua` as `monitors.lua.bak.<unix-time>` next to it. To undo, copy a backup back and run `hyprctl reload`. Only the `hl.monitor(...)` lines are edited, and everything else in the file is kept as-is.
- **Mouse:** settings are applied live and saved in `~/.config/peripheralhub/settings.json`. The service re-applies them whenever the mouse is plugged in.

## Known limits

- The keyboard's battery level is only live over **Bluetooth**, through UPower. On the dongle or cable the app shows the last known level with its age ("94% · 2 h ago"), and shows a charging animation on cable.
- Over Bluetooth the keyboard doesn't speak VIA, so lighting, keymap and macros need the cable or the dongle.
- After 5 minutes the keyboard sleeps and stops answering VIA. Press any key and the page comes back.
- The headset needs its dongle plugged straight into the PC. Docks may not pass it through to `headsetcontrol`.
- If `~/.config/hypr/omasettings.lua` sets monitor options, they load after `monitors.lua` and win. The Displays page warns about this.

## Development

```sh
python -m pytest -q
PYTHONPATH=src python -m peripheralhub          # app
PYTHONPATH=src python -m peripheralhub service  # service in the foreground
```
