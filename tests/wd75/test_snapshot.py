from fake_via import FakeKeyboard

from peripheralhub.wd75.snapshot import (
    factory_snapshot, load_snapshot, read_snapshot, restore_plan, save_snapshot,
)
from peripheralhub.wd75.via import RgbState, ViaClient


def test_factory_snapshot_loads():
    s = factory_snapshot()
    assert s.layers == 5 and s.keymap[0][5][9] == 0x5221
    assert s.rgb == RgbState(191, 4, 0, 0, 255)


def test_snapshot_json_roundtrip(tmp_path):
    s = factory_snapshot()
    p = tmp_path / "s.json"
    save_snapshot(s, p)
    assert load_snapshot(p) == s
    assert '"0x5221"' in p.read_text()


def test_read_snapshot_from_fake_keyboard():
    f = factory_snapshot()
    kb = FakeKeyboard()
    for l in range(f.layers):
        for r in range(f.rows):
            for c in range(f.cols):
                kb.keymap[(l, r, c)] = f.keymap[l][r][c]
    kb.macro = bytearray(f.macro_buffer)
    kb.rgb = {1: [f.rgb.brightness, 0], 2: [f.rgb.effect, 0], 3: [f.rgb.speed, 0],
              4: [f.rgb.hue, f.rgb.saturation]}
    s = read_snapshot(ViaClient(kb))
    s.taken = f.taken
    assert s == f


def test_restore_plan_only_changed_keys_and_scoped():
    cur = factory_snapshot()
    cur.keymap[0][2][1] = 0x0004  # Q->A
    assert restore_plan(cur, factory_snapshot()) == [(0, 2, 1, 0x0014)]
    assert restore_plan(cur, factory_snapshot(), layers=[1]) == []
    assert restore_plan(cur, factory_snapshot(), keys=[(0, 2, 1)]) == [(0, 2, 1, 0x0014)]
    assert restore_plan(cur, factory_snapshot(), keys=[(0, 2, 2)]) == []
