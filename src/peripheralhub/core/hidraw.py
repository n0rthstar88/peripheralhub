"""Sysfs hidraw discovery and raw hidraw device I/O."""
from __future__ import annotations

import fcntl
import os
import re
import select
from dataclasses import dataclass
from pathlib import Path

BUS_USB = 0x03
BUS_BLUETOOTH = 0x05

_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def _hidiocsfeature(length: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x06, length)


def _hidiocgfeature(length: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x07, length)


@dataclass(frozen=True)
class HidrawNode:
    path: str
    bus: int
    vid: int
    pid: int
    name: str
    interface: int | None
    descriptor: bytes


def _read_node(node_dir: Path, dev_root: str) -> HidrawNode | None:
    try:
        hid_dir = (node_dir / "device").resolve(strict=True)
        uevent = dict(
            line.split("=", 1) for line in (hid_dir / "uevent").read_text().splitlines() if "=" in line
        )
        bus_s, vid_s, pid_s = uevent["HID_ID"].split(":")
        descriptor = (hid_dir / "report_descriptor").read_bytes()
        interface: int | None = None
        try:
            interface = int((hid_dir.parent / "bInterfaceNumber").read_text().strip(), 16)
        except (OSError, ValueError):
            pass
        return HidrawNode(
            path=f"{dev_root.rstrip('/')}/{node_dir.name}",
            bus=int(bus_s, 16),
            vid=int(vid_s, 16),
            pid=int(pid_s, 16),
            name=uevent.get("HID_NAME", ""),
            interface=interface,
            descriptor=descriptor,
        )
    except (OSError, KeyError, ValueError):
        return None


def _num(p: Path) -> int:
    m = re.search(r"(\d+)$", p.name)
    return int(m.group(1)) if m else -1


def list_nodes(sysfs_root: str = "/sys/class/hidraw", dev_root: str = "/dev") -> list[HidrawNode]:
    try:
        entries = sorted(Path(sysfs_root).iterdir(), key=_num)
    except OSError:
        return []
    return [n for e in entries if (n := _read_node(e, dev_root)) is not None]


def find_nodes(
    vid: int,
    pid: int,
    *,
    descriptor_prefix: bytes | None = None,
    interface: int | None = None,
    bus: int | None = None,
    name: str | None = None,
    sysfs_root: str = "/sys/class/hidraw",
    dev_root: str = "/dev",
) -> list[HidrawNode]:
    return [
        n
        for n in list_nodes(sysfs_root, dev_root)
        if n.vid == vid
        and n.pid == pid
        and (descriptor_prefix is None or n.descriptor.startswith(descriptor_prefix))
        and (interface is None or n.interface == interface)
        and (bus is None or n.bus == bus)
        and (name is None or n.name == name)
    ]


class HidrawDevice:
    """Raw hidraw node handle. Raises OSError on I/O failure."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fd: int | None = os.open(path, os.O_RDWR)

    def __enter__(self) -> HidrawDevice:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _require_fd(self) -> int:
        if self._fd is None:
            raise OSError("device is closed")
        return self._fd

    def write(self, data: bytes) -> None:
        os.write(self._require_fd(), data)

    def read(self, timeout: float, size: int = 64) -> bytes | None:
        fd = self._require_fd()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        return os.read(fd, size)

    def get_feature(self, report_id: int, length: int) -> bytes:
        """Return the feature report payload without the report id byte."""
        buf = bytearray(length + 1)
        buf[0] = report_id
        fcntl.ioctl(self._require_fd(), _hidiocgfeature(len(buf)), buf, True)
        return bytes(buf[1:])

    def set_feature(self, report_id: int, payload: bytes) -> None:
        buf = bytearray([report_id]) + bytearray(payload)
        fcntl.ioctl(self._require_fd(), _hidiocsfeature(len(buf)), buf, True)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
