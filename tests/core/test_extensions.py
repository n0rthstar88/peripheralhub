import time

from peripheralhub import cli
from peripheralhub.core.battery import BatteryReading
from peripheralhub.core.extensions import (
    ConfigDevice,
    Extensions,
    Peripheral,
    hidden_ids,
    load_extensions,
    run_command,
    udev_rules,
)
from peripheralhub.core.registry import Registry
from peripheralhub.core.settings import Settings


def write(root, kind, name, text):
    folder = root / kind
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(text)
    return path


def fake_usb(root, vid, pid):
    dev = root / "1-1"
    dev.mkdir()
    (dev / "idVendor").write_text(f"{vid}\n")
    (dev / "idProduct").write_text(f"{pid}\n")


def test_bad_toml_is_reported_and_good_devices_still_load(tmp_path):
    write(tmp_path, "devices", "good.toml", 'title = "Pad"\nicon = "input-gaming-symbolic"\n'
                                            '[[actions]]\nlabel = "Profile"\ncommand = "true"\n')
    write(tmp_path, "devices", "broken.toml", "title = ")
    write(tmp_path, "devices", "clash.toml", 'id = "wd75"\ntitle = "Fake keyboard"\n')
    write(tmp_path, "devices", "bad-icon.toml", 'title = "Pad"\nicon = 5\n')
    ext = load_extensions(tmp_path, env={})
    assert [(d.id, d.title, d.actions[0].label) for d in ext.devices] == [("good", "Pad", "Profile")]
    assert sorted(e.path.name for e in ext.errors) == ["bad-icon.toml", "broken.toml", "clash.toml"]


def test_usb_detection_reports_connected_only_when_the_id_is_present(tmp_path):
    fake_usb(tmp_path, "046d", "c548")
    present = ConfigDevice.from_toml({"title": "A", "detect": {"usb": ["046D:C548"]}}, "a", usb_root=tmp_path)
    absent = ConfigDevice.from_toml({"title": "B", "detect": {"usb": ["1234:5678"]}}, "b", usb_root=tmp_path)
    assert present.poll() == "connected"
    assert absent.poll() == "disconnected"


def test_battery_command_reads_level_and_failures_read_as_no_battery():
    def device(cmd):
        return ConfigDevice.from_toml({"title": "A", "battery": {"command": cmd}}, "a")

    ok = device("echo '87% charging'")
    assert (ok.read_battery().level, ok.read_battery().charging) == (87, True)
    assert ok.poll() == "connected"
    assert device("echo '87% discharging'").read_battery().charging is False
    assert device("echo 'Arctis Nova 7P 54%'").read_battery().level == 54
    assert device("echo 42").read_battery().level == 42
    for bad in ("exit 1", "echo nothing", "echo 900"):
        failed = device(bad)
        assert failed.read_battery() is None
        assert failed.poll() == "disconnected"


def test_a_hung_command_pipeline_is_killed_at_the_timeout():
    start = time.monotonic()
    result = run_command("sleep 30 | cat", timeout=0.2)
    assert not result.ok
    assert time.monotonic() - start < 5


def test_plugin_registers_a_device_and_a_broken_plugin_adds_nothing(tmp_path):
    write(tmp_path, "plugins", "good.py", "from peripheralhub.plugin import Peripheral\n"
                                          "class Pad(Peripheral):\n    id = 'pad'\n    title = 'Pad'\n"
                                          "def register(api):\n    api.add_device(Pad())\n")
    write(tmp_path, "plugins", "broken.py", "from peripheralhub.plugin import Peripheral\n"
                                            "class Half(Peripheral):\n    id = 'half'\n    title = 'Half'\n"
                                            "def register(api):\n    api.add_device(Half())\n    raise SystemExit(1)\n")
    ext = load_extensions(tmp_path, env={})
    assert [d.id for d in ext.devices] == ["pad"]
    assert [e.path.name for e in ext.errors] == ["broken.py"]


def test_files_other_users_could_edit_are_refused(tmp_path):
    marker = tmp_path / "ran"
    path = write(tmp_path, "plugins", "shared.py", f"open({str(marker)!r}, 'w').close()\ndef register(api): pass\n")
    path.chmod(0o666)
    ext = load_extensions(tmp_path, env={})
    assert not marker.exists()
    assert "writable" in ext.errors[0].message


def test_safe_mode_loads_nothing(tmp_path):
    marker = tmp_path / "ran"
    write(tmp_path, "plugins", "p.py", f"open({str(marker)!r}, 'w').close()\ndef register(api): pass\n")
    write(tmp_path, "devices", "d.toml", 'title = "Pad"\n')
    ext = load_extensions(tmp_path, env={"PERIPHERALHUB_SAFE_MODE": "1"})
    assert ext.devices == [] and ext.errors == [] and not marker.exists()


class _Crashes(Peripheral):
    id, title = "crash", "Crash"

    def poll(self):
        raise RuntimeError("boom")


class _Works(Peripheral):
    id, title, has_battery = "works", "Works", True

    def poll(self):
        return "connected"

    def read_battery(self):
        return BatteryReading(50, False, True, 1.0)


class _Untouched:
    node_path, busy, connection, state = None, False, None, "disconnected"

    def __getattr__(self, name):
        raise AssertionError(f"hidden device was touched: {name}")


def test_registry_isolates_a_crashing_device_and_never_polls_hidden_ones(tmp_path):
    reg = Registry(Settings(str(tmp_path / "s.json")), wd75=_Untouched(), basilisk=_Untouched(),
                   headset_reader=lambda: None, upower_reader=lambda: None,
                   extras=[_Crashes(), _Works()], hidden={"wd75", "basilisk"})
    reg.poll_devices()
    reg.poll_batteries()
    statuses = {s.id: s for s in reg.statuses()}
    assert set(statuses) == {"headset", "displays", "crash", "works"}
    assert statuses["crash"].state == "disconnected"
    assert (statuses["works"].state, statuses["works"].battery.level) == ("connected", 50)


def test_hidden_ids_combine_settings_replacements_and_the_desktop(tmp_path):
    class Sway(Peripheral):
        id, title, replaces = "sway", "Displays", "headset"

    settings = Settings(str(tmp_path / "s.json"))
    settings.set("devices.hidden", ["basilisk"])
    assert hidden_ids(settings, [Sway()], env={"HYPRLAND_INSTANCE_SIGNATURE": "x"}) == {"basilisk", "headset"}
    assert hidden_ids(settings, [], env={}) == {"basilisk", "displays"}


def test_cli_lists_devices_and_errors_and_prints_udev_rules(tmp_path, capsys):
    good = ConfigDevice.from_toml({"title": "Pad", "detect": {"usb": ["046d:c548"]}}, "pad")
    write(tmp_path, "devices", "broken.toml", "title = ")
    errors = load_extensions(tmp_path, env={}).errors
    ext = Extensions([good], errors)
    assert cli.main(["devices"], extensions=ext) == 1
    out = capsys.readouterr().out
    assert "pad" in out and "Pad" in out and "broken.toml" in out
    assert cli.main(["devices", "--udev-rule"], extensions=ext) == 0
    rule = capsys.readouterr().out
    assert rule == udev_rules([good])
    assert 'ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c548", TAG+="uaccess"' in rule
