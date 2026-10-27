import pytest
from fake_via import FakeKeyboard

from peripheralhub.core.hidraw import HidrawNode
from peripheralhub.wd75.device import Connection, Wd75, Wd75State, detect_connection
from peripheralhub.wd75.effects import EFFECTS, effect_name
from peripheralhub.wd75.snapshot import load_snapshot
from peripheralhub.wd75.via import RgbState, ViaTimeout

VIA_DESC = b"\x06\x60\xff\x09\x61\xa1\x01"


def node(path="/dev/hidraw1", name="Womier WD75", bus=0x03, desc=VIA_DESC, pid=0x2222):
    return HidrawNode(path, bus, 0x8888, pid, name, 1, desc)


def test_detect_dongle_cable_bluetooth(fake_sysfs):
    from peripheralhub.core.hidraw import list_nodes

    fake_sysfs.add("hidraw0", hid_name="Womier WD75 2.4G")
    conn, n = detect_connection(list_nodes(fake_sysfs.root, "/dev"))
    assert (conn, n.path) == (Connection.DONGLE, "/dev/hidraw0")

    fake_sysfs.add("hidraw1", hid_name="Womier WD75")
    conn, n = detect_connection(list_nodes(fake_sysfs.root, "/dev"))
    assert (conn, n.path) == (Connection.USB, "/dev/hidraw1")


def test_detect_real_vendor_prefixed_names():
    d = node("/dev/hidraw6", name="Womier Womier WD75 2.4G")
    c = node("/dev/hidraw9", name="Womier Womier WD75")
    assert detect_connection([d]) == (Connection.DONGLE, d)
    assert detect_connection([d, c]) == (Connection.USB, c)


def test_detect_bluetooth_and_none():
    conn, n = detect_connection([node(bus=0x05, name="WD75")])
    assert conn == Connection.BLUETOOTH and n is None
    assert detect_connection([]) == (Connection.DISCONNECTED, None)


def test_detect_ignores_dongle_vendor_interface_and_other_devices():
    nodes = [
        node(name="Womier WD75 2.4G", desc=b"\x06\x00\xff\x09\x01"),
        node(name="Other", pid=0x1111),
    ]
    assert detect_connection(nodes) == (Connection.DISCONNECTED, None)


def make(tmp_path, kb=None, nodes=None, factory=None):
    kb = kb or FakeKeyboard()
    return kb, Wd75(
        str(tmp_path / "backups"),
        transport_factory=factory or (lambda path: kb),
        node_lister=lambda: nodes if nodes is not None else [node(name="Womier WD75 2.4G")],
    )


def test_state_ready_and_backup_written_once(tmp_path):
    kb, wd = make(tmp_path)
    kb.keymap[(0, 0, 0)] = 0x0029
    assert wd.refresh() == Wd75State.READY
    assert wd.connection == Connection.DONGLE
    wd.write_keycode(0, 0, 0, 0x0004)
    wd.write_keycode(0, 0, 1, 0x0005)
    files = list((tmp_path / "backups").iterdir())
    assert len(files) == 1 and files[0].name.startswith("wd75-") and files[0].suffix == ".json"
    assert load_snapshot(files[0]).keymap[0][0][0] == 0x0029
    assert wd.ensure_backup() == str(files[0])
    assert kb.keymap[(0, 0, 0)] == 0x0004


def test_backup_is_atomic_no_tmp_left(tmp_path):
    _, wd = make(tmp_path)
    wd.refresh()
    wd.ensure_backup()
    assert all(not p.name.endswith(".tmp") for p in (tmp_path / "backups").iterdir())


def test_apply_rgb_previews_and_keeps_other_color_component(tmp_path):
    kb, wd = make(tmp_path)
    wd.refresh()
    wd.apply_rgb(brightness=100, effect=3, hue=10)
    assert wd.via.get_rgb() == RgbState(100, 3, 0, 10, 255)
    assert not any(p[0] == 0x09 for p in kb.sent)
    wd.apply_rgb(saturation=50, speed=2)
    assert wd.via.get_rgb() == RgbState(100, 3, 2, 10, 50)
    with pytest.raises(TypeError):
        wd.apply_rgb(bogus=1)


def test_save_rgb_sends_0x09_and_backs_up(tmp_path):
    kb, wd = make(tmp_path)
    wd.refresh()
    wd.save_rgb()
    assert any(p[0] == 0x09 for p in kb.sent)
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_write_macros_and_restore(tmp_path):
    kb, wd = make(tmp_path)
    wd.refresh()
    target = wd.take_snapshot()
    wd.write_keycode(0, 1, 1, 0x0004)
    wd.write_keycode(1, 2, 2, 0x0005)
    assert wd.restore(target, layers=[0]) == 1
    assert kb.keymap[(0, 1, 1)] == 0 and kb.keymap[(1, 2, 2)] == 0x0005
    wd.write_macros(b"\x01\x02")
    assert bytes(kb.macro[:2]) == b"\x01\x02"


def test_write_without_device_raises(tmp_path):
    from peripheralhub.wd75.via import ViaError

    _, wd = make(tmp_path, nodes=[])
    assert wd.refresh() == Wd75State.DISCONNECTED
    with pytest.raises(ViaError):
        wd.write_keycode(0, 0, 0, 1)


class Sleeper:
    def exchange(self, packet):
        raise ViaTimeout("asleep")


def test_state_asleep_when_via_times_out(tmp_path):
    _, wd = make(tmp_path, factory=lambda path: Sleeper())
    assert wd.refresh() == Wd75State.ASLEEP
    assert wd.via is None


def test_state_no_permission(tmp_path):
    def deny(path):
        raise PermissionError(path)

    _, wd = make(tmp_path, factory=deny)
    assert wd.refresh() == Wd75State.NO_PERMISSION


def test_bluetooth_only(tmp_path):
    _, wd = make(tmp_path, nodes=[node(bus=0x05)])
    assert wd.refresh() == Wd75State.BLUETOOTH_ONLY
    assert wd.via is None and wd.connection == Connection.BLUETOOTH


def test_effect_name_fallback_and_override():
    assert effect_name(99) == "Effect 99"
    assert effect_name(4, {"4": "Rainbow"}) == "Rainbow"


def test_effects_table_matches_probed_ids():
    assert set(EFFECTS) == set(range(1, 18))


def test_probe_backs_up_first_previews_only_and_restores(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "probe", Path(__file__).parent.parent.parent / "tools" / "wd75_probe_effects.py")
    probe_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe_mod)

    kb, wd = make(tmp_path)
    wd.refresh()
    orig, valid, ok, err = probe_mod.probe(wd, delay=0)
    assert err is None and ok and orig == 4
    assert len(list((tmp_path / "backups").iterdir())) == 1
    assert not any(p[0] == 0x09 for p in kb.sent)
    assert kb.rgb[2][0] == 4
    first_write = next(i for i, p in enumerate(kb.sent) if p[0] == 0x07)
    assert any(p[0] == 0x12 for p in kb.sent[:first_write])  # backup read precedes writes


def test_reset_keymap_backs_up_first_is_busy_and_sends_once(tmp_path):
    kb, wd = make(tmp_path)
    wd.refresh()
    seen = {}
    orig = kb.exchange

    def spy(packet):
        if packet[0] == 0x06:
            seen["busy"] = wd.busy
            seen["backups"] = len(list((tmp_path / "backups").glob("wd75-*.json")))
        return orig(packet)

    kb.exchange = spy
    wd.reset_keymap()
    assert seen == {"busy": True, "backups": 1}
    assert [p for p in kb.sent if p[0] == 0x06] == [b"\x06" + bytes(31)]
    assert not wd.busy
