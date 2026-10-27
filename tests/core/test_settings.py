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


def test_two_instances_merge_instead_of_clobbering(tmp_path):
    import os
    from peripheralhub.core.settings import Settings
    p = str(tmp_path / "s.json")
    app, svc = Settings(p), Settings(p)
    app.set("mouse.dpi", 800)
    os.utime(p, (1e9, 2e9))
    svc.set("battery.wd75", {"level": 50, "at": 1.0})
    fresh = Settings(p)
    assert fresh.get("mouse.dpi") == 800 and fresh.get("battery.wd75.level") == 50


def test_reload_picks_up_external_change(tmp_path):
    from peripheralhub.core.settings import Settings
    p = str(tmp_path / "s.json")
    a, b = Settings(p), Settings(p)
    b.set("x", 1)
    assert a.get("x") is None
    a.reload()
    assert a.get("x") == 1
