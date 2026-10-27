from peripheralhub.core.settings import Settings


def test_settings_dotted_and_atomic(tmp_path):
    p = tmp_path / "sub" / "settings.json"
    s = Settings(str(p))
    assert s.get("battery.low_threshold", 20) == 20
    assert s.mtime() == 0.0
    s.set("battery.wd75", {"level": 94, "at": 1000.0})
    s.set("wd75.rgb", {"hue": 1})
    assert Settings(str(p)).get("battery.wd75") == {"level": 94, "at": 1000.0}
    assert Settings(str(p)).get("battery.wd75.level") == 94
    assert not list(p.parent.glob("*.tmp"))
    assert s.mtime() > 0


def test_settings_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{nope")
    assert Settings(str(p)).get("a", 5) == 5
