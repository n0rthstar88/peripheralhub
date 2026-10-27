from peripheralhub.wd75.layout import load_layout


def test_layout_has_84_keys_unique_positions():
    keys = load_layout()
    assert len(keys) == 84
    assert len({(k.row, k.col) for k in keys}) == 84


def test_space_and_esc_geometry():
    k = {(k.row, k.col): k for k in load_layout()}
    assert k[(0, 0)].x == 0 and k[(0, 0)].y == 0
    assert k[(5, 3)].w == 6.25 and k[(1, 13)].w == 2
