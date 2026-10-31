from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from peripheralhub.basilisk.device import Basilisk  # noqa: E402
from peripheralhub.core.registry import BACKUP_DIR, Registry  # noqa: E402
from peripheralhub.core.settings import DEFAULT_PATH, Settings  # noqa: E402
from peripheralhub.core.extensions import hidden_ids, load_extensions  # noqa: E402
from peripheralhub.ui.window import AppContext, MainWindow  # noqa: E402
from peripheralhub.wd75.device import Wd75  # noqa: E402

APP_ID = "dev.hufflabs.PeripheralHub"


class PeripheralHubApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)

    def do_activate(self) -> None:
        win = self.props.active_window
        if win is None:
            settings = Settings(DEFAULT_PATH)
            wd75 = Wd75(str(Path(BACKUP_DIR).expanduser()))
            basilisk = Basilisk()
            ext = load_extensions()
            registry = Registry(settings, wd75=wd75, basilisk=basilisk, extras=ext.devices,
                                hidden=hidden_ids(settings, ext.devices))
            win = MainWindow(self, AppContext(settings, registry, wd75, basilisk, ext.errors))
        win.present()


def main() -> int:
    return PeripheralHubApp().run(sys.argv[:1])
