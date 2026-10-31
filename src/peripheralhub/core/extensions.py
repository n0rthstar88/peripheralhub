"""Custom peripherals: TOML device files and Python plugins from the user's config folder.

Device files can only detect a device and run the user's own commands; they never write to hardware
themselves. Plugins are ordinary Python running with the user's permissions.
"""
from __future__ import annotations

import importlib.util
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.settings import Settings

CONFIG_DIR = "~/.config/peripheralhub"
SAFE_MODE_ENV = "PERIPHERALHUB_SAFE_MODE"
USB_ROOT = "/sys/bus/usb/devices"
DEFAULT_ICON = "input-gaming-symbolic"
COMMAND_TIMEOUT = 5.0
BUILTIN_IDS = frozenset({"wd75", "basilisk", "headset", "displays", "settings"})

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_USB_ID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
_PERCENT = re.compile(r"(?<![\d.])(\d{1,3})\s*%")
_CHARGING = re.compile(r"(?<!not )\bcharging\b", re.IGNORECASE)


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    output: str


@dataclass(frozen=True)
class Action:
    label: str
    command: str


def run_command(command: str, timeout: float = COMMAND_TIMEOUT) -> CommandResult:
    """Run a shell command; on timeout, kill its whole process group so a pipeline can't hold the pipes open."""
    try:
        proc = subprocess.Popen(["sh", "-c", command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
    except OSError as e:
        return CommandResult(False, str(e))
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return CommandResult(False, f"timed out after {timeout:g} s")
    return CommandResult(proc.returncode == 0, output.strip())


def usb_present(ids: Iterable[str], root: str | Path = USB_ROOT) -> bool:
    wanted = set(ids)
    for dev in Path(root).glob("*"):
        try:
            found = f"{(dev / 'idVendor').read_text().strip()}:{(dev / 'idProduct').read_text().strip()}"
        except OSError:
            continue
        if found.lower() in wanted:
            return True
    return False


def battery_reading(level: int, charging: bool | None = None) -> BatteryReading:
    """A live reading taken now, for plugins to return from read_battery()."""
    return BatteryReading(level, charging, True, time.time())


def parse_battery(text: str) -> BatteryReading | None:
    """A level from "54%" anywhere in the text, or from text that is only a number."""
    match = _PERCENT.search(text)
    level = match.group(1) if match else text.strip()
    if not level.isdecimal() or int(level) > 100:
        return None
    return battery_reading(int(level), bool(_CHARGING.search(text)))


class Peripheral:
    """A device in the app. Subclass it in a plugin; only id and title are required."""

    id = ""
    title = ""
    icon = DEFAULT_ICON
    hint = "Not connected"
    has_battery = False
    usb: tuple[str, ...] = ()  # "vvvv:pppp" ids, for `phub devices --udev-rule`
    replaces: str | None = None  # a built-in device id this one takes the place of
    actions: tuple[Action, ...] = ()
    source = ""

    def poll(self) -> str:
        """Called every 2 s on the UI thread, so keep it fast: "connected", "disconnected" or "available"."""
        return "available"

    def read_battery(self) -> BatteryReading | None:
        """Called every 60 s on a worker thread, so slow work belongs here."""
        return None

    def page(self, ctx) -> object | None:
        """Return an object with widget() and on_status(), or None for the standard device page."""
        return None

    def background(self) -> None:
        """Called every 2 s in the background service only."""


class ConfigDevice(Peripheral):
    """A device described by a TOML file."""

    def __init__(self, device_id: str, title: str, *, icon: str = DEFAULT_ICON, hint: str = "Not connected",
                 usb: tuple[str, ...] = (), detect_command: str | None = None, battery_command: str | None = None,
                 actions: tuple[Action, ...] = (), replaces: str | None = None, usb_root: str | Path = USB_ROOT) -> None:
        self.id, self.title, self.icon, self.hint = device_id, title, icon, hint
        self.usb, self.actions, self.replaces = usb, actions, replaces
        self.has_battery = battery_command is not None
        self._detect_command, self._battery_command, self._usb_root = detect_command, battery_command, usb_root
        self._commands_say_connected = False

    @classmethod
    def from_toml(cls, data: Mapping, fallback_id: str, usb_root: str | Path = USB_ROOT) -> ConfigDevice:
        device_id = data.get("id", fallback_id)
        if not isinstance(device_id, str) or not _ID.match(device_id):
            raise ValueError(f"id {device_id!r} must use lowercase letters, numbers, - and _")
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        detect, battery = data.get("detect", {}), data.get("battery", {})
        for key, value in (("icon", data.get("icon")), ("hint", data.get("hint")), ("replaces", data.get("replaces")),
                           ("detect.command", detect.get("command")), ("battery.command", battery.get("command"))):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be text")
        usb = tuple(str(u).lower() for u in detect.get("usb", ()))
        for u in usb:
            if not _USB_ID.match(u):
                raise ValueError(f"USB id {u!r} must look like 046d:c548")
        actions = tuple(Action(_text(a, "label"), _text(a, "command")) for a in data.get("actions", ()))
        return cls(device_id, title, icon=data.get("icon", DEFAULT_ICON), hint=data.get("hint", "Not connected"),
                   usb=usb, detect_command=detect.get("command"), battery_command=battery.get("command"),
                   actions=actions, replaces=data.get("replaces"), usb_root=usb_root)

    def _usb_connected(self) -> bool:
        return usb_present(self.usb, self._usb_root)

    def poll(self) -> str:
        if self.usb and not self._usb_connected():
            return "disconnected"
        if self._detect_command is None and self._battery_command is None:
            return "connected" if self.usb else "available"
        if self.usb and self._detect_command is None:
            return "connected"
        return "connected" if self._commands_say_connected else "disconnected"

    def read_battery(self) -> BatteryReading | None:
        if self.usb and not self._usb_connected():
            self._commands_say_connected = False
            return None
        if self._detect_command is not None:
            self._commands_say_connected = run_command(self._detect_command).ok
            if not self._commands_say_connected:
                return None
        if self._battery_command is None:
            return None
        result = run_command(self._battery_command)
        reading = parse_battery(result.output) if result.ok else None
        if self._detect_command is None:
            self._commands_say_connected = reading is not None
        return reading


def _text(table: Mapping, key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"each action needs a {key}")
    return value


@dataclass(frozen=True)
class LoadError:
    path: Path
    message: str


@dataclass
class Extensions:
    devices: list[Peripheral] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)


class PluginApi:
    """What a plugin's register(api) receives."""

    def __init__(self) -> None:
        self.devices: list[Peripheral] = []

    def add_device(self, device: Peripheral) -> None:
        self.devices.append(device)


def _unsafe_reason(path: Path) -> str | None:
    for target in (path, path.parent):
        st = target.stat()
        if st.st_uid != os.getuid():
            return f"{target} belongs to another user"
        if st.st_mode & 0o022:
            return f"{target} is writable by other users"
    return None


def _load_device_file(path: Path) -> list[Peripheral]:
    return [ConfigDevice.from_toml(tomllib.loads(path.read_text()), path.stem.lower())]


def _load_plugin(path: Path) -> list[Peripheral]:
    name = f"peripheralhub_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    api = PluginApi()
    module.register(api)
    return api.devices


def _check(device: Peripheral, taken: set[str]) -> None:
    if not isinstance(device, Peripheral):
        raise ValueError("add_device needs a Peripheral")
    if not _ID.match(device.id or "") or not device.title:
        raise ValueError(f"device {device.id!r} needs a valid id and a title")
    if device.id in BUILTIN_IDS:
        raise ValueError(f"id {device.id!r} is a built-in device; use replaces = {device.id!r} with a new id")
    if device.id in taken:
        raise ValueError(f"id {device.id!r} is already in use")
    if device.replaces is not None and device.replaces not in BUILTIN_IDS - {"settings"}:
        raise ValueError(f"replaces {device.replaces!r} is not a built-in device")


def load_extensions(config_dir: str | Path = CONFIG_DIR, env: Mapping[str, str] = os.environ) -> Extensions:
    """Load what's there and report the rest: one bad file never stops the app or the other files."""
    ext = Extensions()
    if env.get(SAFE_MODE_ENV):
        return ext
    root = Path(config_dir).expanduser()
    taken: set[str] = set()
    sources = [(path, _load_device_file) for path in sorted((root / "devices").glob("*.toml"))]
    sources += [(path, _load_plugin) for path in sorted((root / "plugins").glob("*.py"))]
    for path, load in sources:
        try:
            if reason := _unsafe_reason(path):
                raise ValueError(f"refused: {reason}")
            devices = load(path)
            ids = set(taken)
            for device in devices:
                _check(device, ids)
                ids.add(device.id)
        except (Exception, SystemExit) as e:
            ext.errors.append(LoadError(path, str(e) or type(e).__name__))
            continue
        taken = ids
        for device in devices:
            device.source = path.name
        ext.devices.extend(devices)
    return ext


def hidden_ids(settings: Settings, devices: Iterable[Peripheral], env: Mapping[str, str] = os.environ) -> set[str]:
    hidden = settings.get("devices.hidden", [])
    result = {h for h in hidden if isinstance(h, str)} if isinstance(hidden, list) else set()
    result |= {d.replaces for d in devices if d.replaces}
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        result.add("displays")  # the built-in Displays page only knows Hyprland
    return result


def udev_rules(devices: Iterable[Peripheral]) -> str:
    """Rules giving the logged-in user hidraw access, for plugins that talk to a device directly."""
    ids = sorted({u for d in devices for u in d.usb if _USB_ID.match(u)})
    lines = [f'KERNEL=="hidraw*", ATTRS{{idVendor}}=="{u[:4]}", ATTRS{{idProduct}}=="{u[5:]}", TAG+="uaccess"'
             for u in ids]
    return "".join(f"{line}\n" for line in lines)
