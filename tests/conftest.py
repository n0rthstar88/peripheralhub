from __future__ import annotations

from pathlib import Path

import pytest


class FakeSysfs:
    def __init__(self, tmp_path: Path) -> None:
        self.base = tmp_path
        self.root = str(tmp_path / "class" / "hidraw")
        Path(self.root).mkdir(parents=True)
        self._n = 0

    def add(
        self,
        name: str,
        hid_id: str = "0003:00008888:00002222",
        hid_name: str = "Womier WD75",
        descriptor: bytes = b"\x06\x60\xff\x09\x61\xa1\x01",
        interface: int | None = 1,
    ) -> None:
        self._n += 1
        iface_dir = self.base / "devices" / f"usb{self._n}" / f"{self._n}-1:1.{interface or 0}"
        hid_dir = iface_dir / f"{hid_id}.{self._n:04d}"
        hid_dir.mkdir(parents=True)
        (hid_dir / "uevent").write_text(
            f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME={hid_name}\nHID_PHYS=x\n"
        )
        (hid_dir / "report_descriptor").write_bytes(descriptor)
        if interface is not None:
            (iface_dir / "bInterfaceNumber").write_text(f"{interface:02d}\n")
        node = Path(self.root) / name
        node.mkdir()
        (node / "device").symlink_to(hid_dir)

    def add_broken(self, name: str) -> None:
        """A hidraw node whose device dir has no uevent."""
        hid_dir = self.base / "devices" / "broken"
        hid_dir.mkdir(parents=True, exist_ok=True)
        node = Path(self.root) / name
        node.mkdir()
        (node / "device").symlink_to(hid_dir)


@pytest.fixture
def fake_sysfs(tmp_path: Path) -> FakeSysfs:
    return FakeSysfs(tmp_path)
