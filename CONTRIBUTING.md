# Contributing

Issues and pull requests are welcome. This is a small project built around one desk setup, so please open an issue before starting anything large, such as support for a new device.

## Setup

You need the dependencies from the [README](README.md#install), plus `pytest`.

```sh
python -m pytest -q
PYTHONPATH=src python -m peripheralhub
```

The tests don't need any hardware attached.

## Pull requests

- Add or update tests for behaviour changes, and make sure the suite passes.
- Keep each pull request to one change.
- Say what you tested on real hardware, and on which device and Omarchy version.

## Hardware safety

A bad write can leave someone's keyboard or monitor setup in a broken state, so these rules apply to every change:

- Keep VIA traffic on the command allowlist. Never send VIA's erase or bootloader-jump commands, and never write to the keyboard's vendor `0xFF00` interface.
- Back up before writing to a device, and keep display changes on the auto-revert path.
- Never require root at runtime. Device access comes from the udev rule.
- Don't probe unknown commands against hardware from the app or from tests.

## Licensing

By submitting a contribution, you agree that it is licensed under the project's license, [GPL-3.0-or-later](LICENSE). Only submit work you have the right to contribute, and list any third-party material in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Don't add vendor manuals, firmware, or other files you can't redistribute.

## Privacy

Before attaching logs, fixtures or screenshots, remove device serial numbers, Bluetooth addresses, home directory paths and macro contents.
