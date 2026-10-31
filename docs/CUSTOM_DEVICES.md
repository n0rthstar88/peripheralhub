# Custom devices and plugins

You can add peripherals to PeripheralHub without changing the app's code. Put a file in your config folder, then restart the app and the background service:

```sh
systemctl --user restart peripheralhub
```

| Folder | What goes in it | Good for |
|---|---|---|
| `~/.config/peripheralhub/devices/` | `.toml` device files | Showing status and battery, and running commands from buttons |
| `~/.config/peripheralhub/plugins/` | `.py` plugins | Your own page, or talking to a device directly |

Start with a device file, because it needs no programming. Ready-to-copy samples are in [`examples/`](../examples).

Run `phub devices` to see what loaded. It prints an error for any file it couldn't load, and those errors also appear under Settings → Devices. A bad file never stops the app or your other devices.

## Device files

```toml
title = "Wireless Mouse"               # required
icon = "input-mouse-symbolic"          # optional, any icon name from your theme
hint = "Plug in the receiver"          # optional, shown while disconnected
# id = "my-mouse"                      # optional, defaults to the file name
# replaces = "displays"                # optional, see "Other desktops" below

[detect]                               # optional
usb = ["046d:c548"]                    # connected when any of these USB ids is present (see lsusb)
# command = "my-check"                 # or connected when this command exits 0

[battery]                              # optional
command = "my-battery-tool"            # see below

[[actions]]                            # optional and repeatable: one button per action
label = "Gaming profile"
command = "my-tool --profile gaming"
```

How each part behaves:

- **Connected or not:** USB ids are checked every 2 seconds. Commands are checked every 60 seconds, so status from a command can take up to a minute to change. A device with no `[detect]` and no `[battery]` always shows as available.
- **Battery command:** it must exit 0 and print a percentage somewhere (`Level: 54%`), or print only a number (`54`). If the output contains the word `charging`, the device shows as charging. Readings feed the low-battery notification too.
- **Commands:** they run through `sh`, as your user. Detect and battery commands are stopped after 5 seconds, and action buttons after 30.

Device files never write to hardware themselves. They only run the commands you give them, so anything an action does to a device is down to the tool you call, such as OpenRGB or Solaar.

## Plugins

A plugin is a Python file with a `register(api)` function:

```python
from peripheralhub.plugin import Peripheral, battery_reading


class MyPad(Peripheral):
    id = "my-pad"              # required
    title = "My Pad"           # required
    icon = "input-gaming-symbolic"
    has_battery = True
    usb = ("1234:5678",)       # lets `phub devices --udev-rule` include it

    def poll(self):
        """Every 2 s, on the UI thread, so keep it fast."""
        return "connected"     # or "disconnected" or "available"

    def read_battery(self):
        """Every 60 s, on a worker thread. Slow work belongs here."""
        return battery_reading(80, charging=False)

    def page(self, ctx):
        """Your own page: an object with widget() and on_status(status). None uses the standard page."""
        return None

    def background(self):
        """Every 2 s, in the background service only."""


def register(api):
    api.add_device(MyPad())
```

`actions` works like it does in device files, using `Action(label, command)` from `peripheralhub.plugin`, which also provides `run_command` and `usb_present`. Both the app and the service load your plugin, so two copies can run at once. If they share a device, your plugin has to handle that itself.

**Direct device access:** if your plugin opens a hidraw device, your user needs permission. `phub devices --udev-rule` prints a rule for the USB ids your custom devices declare. Save it to its own file so `install.sh` won't overwrite it:

```sh
phub devices --udev-rule | sudo tee /etc/udev/rules.d/71-peripheralhub-custom.rules
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
```

Check the printed rule first, because it gives any logged-in user's session access to those devices.

## Safety

**Plugins and device files run with your full user permissions, so only install ones you trust and have read.** A plugin can also write to hardware, and a bad write can break a device. PeripheralHub's protections for the built-in keyboard, such as the VIA command allowlist and automatic backups, don't apply to plugin code. See the [hardware safety rules](../CONTRIBUTING.md#hardware-safety).

- **Permissions check:** files that other users can edit, or that sit in a folder other users can edit, are refused.
- **Failures are contained:** if a device raises an error while being polled, it shows as disconnected and the app keeps running. A plugin that hangs while it loads can still hold up startup.
- **Safe mode:** to start with no custom devices or plugins, use `PERIPHERALHUB_SAFE_MODE=1 peripheralhub`. Remove or fix the bad file from there. The background service loads them separately, so stop it first if a plugin is causing trouble: `systemctl --user stop peripheralhub`.

## Hiding built-in devices

Turn off any device you don't own under Settings → Devices, then restart the app and the service. A hidden device isn't shown, and the app and service don't talk to it.

## Other desktops and platforms

- **Other Linux desktops:** the built-in Displays page needs Hyprland and hides itself on other desktops. To put your own in its place, set `replaces = "displays"` in a device file or plugin, for example with buttons that call your compositor's tools. `replaces` works for any built-in device.
- **Other commands:** device files can use whatever tools your system has, so they aren't tied to UPower or `headsetcontrol`.
- **Other operating systems:** not supported yet. The app itself uses Linux-only features (hidraw, sysfs) at startup, so running on macOS or Windows would still need changes to the app's code.
