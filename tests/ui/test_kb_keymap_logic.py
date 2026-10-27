from peripheralhub.ui.pages.kb_keymap import UndoStack, needs_last_fn_warning
from peripheralhub.wd75.keycodes import is_dangerous, search
from peripheralhub.wd75.snapshot import factory_snapshot


def test_last_fn_warning():
    km = factory_snapshot().keymap
    assert needs_last_fn_warning(km, 0, 5, 9, 0x0004)
    assert not needs_last_fn_warning(km, 0, 2, 1, 0x0004)
    assert not needs_last_fn_warning(km, 0, 5, 9, 0x5221)  # replaced by the same layer key


def test_undo_stack():
    u = UndoStack()
    u.push(0, 1, 1, 0x04, 0x05)
    u.push(0, 2, 2, 0x06, 0x07)
    assert u.undo() == (0, 2, 2, 0x06)
    assert u.undo() == (0, 1, 1, 0x04)
    assert u.undo() is None


def test_picker_names_and_dangerous_reboot():
    assert search("RGB_TOG") and search("RM_TOGG")
    assert is_dangerous(0x7C01)
