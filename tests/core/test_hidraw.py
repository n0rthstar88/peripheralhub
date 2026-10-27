from peripheralhub.core.hidraw import BUS_BLUETOOTH, find_nodes, list_nodes

FF60 = bytes.fromhex("0660ff0961a101")
FF00 = bytes.fromhex("0600ff0901a101")


def test_list_nodes_parses_uevent_descriptor_and_interface(fake_sysfs):
    fake_sysfs.add("hidraw5", hid_id="0003:00008888:00002222", hid_name="Womier WD75 2.4G",
                   descriptor=bytes.fromhex("0660ff0961a101"), interface=1)
    [n] = list_nodes(fake_sysfs.root, "/dev")
    assert (n.path, n.bus, n.vid, n.pid, n.name, n.interface) == (
        "/dev/hidraw5", 0x03, 0x8888, 0x2222, "Womier WD75 2.4G", 1)
    assert n.descriptor.startswith(bytes.fromhex("0660ff0961"))


def _populate(s):
    s.add("hidraw5", hid_name="Womier WD75 2.4G", descriptor=FF60, interface=1)
    s.add("hidraw6", hid_name="Womier WD75 2.4G", descriptor=FF00, interface=4)
    s.add("hidraw7", hid_id="0003:00001532:00000099", hid_name="Razer Basilisk V3",
          descriptor=b"\x05\x0c\x09\x01", interface=3)
    s.add("hidraw8", hid_id="0005:00008888:00002222", hid_name="Womier WD75",
          descriptor=FF60, interface=None)


def test_find_nodes_filters_by_prefix_interface_bus_and_name(fake_sysfs):
    _populate(fake_sysfs)
    r = fake_sysfs.root
    got = find_nodes(0x8888, 0x2222, descriptor_prefix=FF60[:5], sysfs_root=r)
    assert {n.path for n in got} == {"/dev/hidraw5", "/dev/hidraw8"}
    [rz] = find_nodes(0x1532, 0x0099, interface=3, sysfs_root=r)
    assert rz.path == "/dev/hidraw7"
    [bt] = find_nodes(0x8888, 0x2222, bus=BUS_BLUETOOTH, sysfs_root=r)
    assert bt.path == "/dev/hidraw8" and bt.interface is None
    [d] = find_nodes(0x8888, 0x2222, name="Womier WD75 2.4G", descriptor_prefix=FF60[:5], sysfs_root=r)
    assert d.path == "/dev/hidraw5"
    only5 = find_nodes(0x8888, 0x2222, descriptor_prefix=FF60[:5], bus=0x03, sysfs_root=r)
    assert [n.path for n in only5] == ["/dev/hidraw5"]


def test_unreadable_node_is_skipped(fake_sysfs):
    fake_sysfs.add_broken("hidraw1")
    fake_sysfs.add("hidraw2", descriptor=FF60)
    assert [n.path for n in list_nodes(fake_sysfs.root, "/dev")] == ["/dev/hidraw2"]


def test_missing_sysfs_root_gives_empty_list(tmp_path):
    assert list_nodes(str(tmp_path / "nope"), "/dev") == []


def test_locked_excludes_other_open_files(tmp_path):
    import fcntl
    import os
    import pytest
    from peripheralhub.core.hidraw import HidrawDevice
    f = tmp_path / "node"
    f.write_bytes(b"")
    a = HidrawDevice(str(f))
    other = os.open(str(f), os.O_RDWR)
    try:
        with a.locked():
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released after the block
    finally:
        os.close(other)
        a.close()
