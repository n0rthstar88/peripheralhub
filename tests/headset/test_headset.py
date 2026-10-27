import json
import subprocess
from pathlib import Path

from peripheralhub.headset.device import parse_headsetcontrol, read_headset

FIXTURE = Path(__file__).parents[1] / "core" / "fixtures" / "headsetcontrol_battery.json"


def _doc(status, level=86):
    return json.dumps({"devices": [{"device": "SteelSeries Arctis Nova 7P",
                                    "battery": {"status": status, "level": level}}]})


def test_parse_real_fixture():
    r = parse_headsetcontrol(FIXTURE.read_text(), now=5.0)
    assert (r.level, r.charging, r.live, r.measured_at) == (82, False, True, 5.0)


def test_parse_available_and_charging():
    assert parse_headsetcontrol(_doc("BATTERY_AVAILABLE")).charging is False
    r = parse_headsetcontrol(_doc("BATTERY_CHARGING"))
    assert r.level == 86 and r.charging is True


def test_parse_unavailable_or_empty():
    assert parse_headsetcontrol(_doc("BATTERY_UNAVAILABLE", -1)) is None
    assert parse_headsetcontrol('{"devices": []}') is None
    assert parse_headsetcontrol("garbage") is None


def test_read_headset_runs_command_and_handles_failure():
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw["timeout"]))
        return subprocess.CompletedProcess(cmd, 0, stdout=FIXTURE.read_text())

    assert read_headset(run).level == 82
    assert calls == [(["headsetcontrol", "-b", "-o", "json"], 5)]

    def missing(cmd, **kw):
        raise FileNotFoundError

    assert read_headset(missing) is None
