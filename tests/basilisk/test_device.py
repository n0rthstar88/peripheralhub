import pytest

from peripheralhub.basilisk import protocol as p
from peripheralhub.basilisk.device import Basilisk, RazerError, transact
from peripheralhub.core.hidraw import HidrawNode

NODE = HidrawNode("/dev/hidraw3", 0x03, 0x1532, 0x0099, "Razer Basilisk V3", 3, b"")


class FakeHid:
    def __init__(self, statuses=(p.OK,), args=b"", fail=None):
        self.statuses = list(statuses)
        self.args = args
        self.fail = fail
        self.sent: list[bytes] = []
        self.closed = False

    def set_feature(self, report_id, payload):
        if self.fail:
            raise self.fail
        assert report_id == 0 and len(payload) == 90
        self.sent.append(bytes(payload))

    def get_feature(self, report_id, length):
        assert length == 90
        buf = bytearray(self.sent[-1])
        buf[0] = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        buf[8 : 8 + len(self.args)] = self.args
        return bytes(buf)

    def close(self):
        self.closed = True


def mouse(hid):
    m = Basilisk(node_lister=lambda: [NODE], opener=lambda path: hid, sleep=lambda s: None)
    assert m.open()
    return m


def test_transact_retries_busy_then_ok():
    hid = FakeHid(statuses=[p.BUSY, p.OK])
    assert transact(hid, p.get_poll(), sleep=lambda s: None).status == p.OK
    assert len(hid.sent) == 2


def test_transact_gives_up_after_three_busy():
    hid = FakeHid(statuses=[p.BUSY])
    with pytest.raises(RazerError, match="BUSY"):
        transact(hid, p.get_poll(), sleep=lambda s: None)
    assert len(hid.sent) == 3


@pytest.mark.parametrize("status", [p.FAIL, p.TIMEOUT, p.UNSUPPORTED])
def test_error_statuses_raise(status):
    with pytest.raises(RazerError):
        transact(FakeHid(statuses=[status]), p.get_poll(), sleep=lambda s: None)


def test_oserror_becomes_razer_error():
    with pytest.raises(RazerError):
        transact(FakeHid(fail=OSError(19, "No such device")), p.get_poll(), sleep=lambda s: None)


def test_oserror_marks_disconnected():
    hid = FakeHid()
    m = mouse(hid)
    hid.fail = OSError(5, "EIO")
    with pytest.raises(RazerError):
        m.poll()
    assert m.state == "disconnected" and hid.closed


def test_basilisk_no_permission():
    def deny(path):
        raise PermissionError(path)

    m = Basilisk(node_lister=lambda: [NODE], opener=deny)
    with pytest.raises(PermissionError):
        m.open()
    assert m.state == "no_permission"


def test_basilisk_absent():
    m = Basilisk(node_lister=lambda: [])
    assert m.open() is False and m.state == "disconnected"


def test_reads_parse_replies():
    assert mouse(FakeHid(args=bytes([1, 0x06, 0x40, 0x03, 0x20]))).dpi() == (1600, 800)
    assert mouse(FakeHid(args=bytes([0x02]))).poll() == 500
    assert mouse(FakeHid(args=bytes([1, 1, 77]))).brightness() == 77
    stages = bytes([1, 2, 2, 1, 0x01, 0x90, 0x01, 0x90, 0, 0, 2, 0x03, 0x20, 0x03, 0x20, 0, 0])
    assert mouse(FakeHid(args=stages)).stages() == ([400, 800], 2)


def test_brightness_read_uses_per_led_getter():
    hid = FakeHid(args=bytes([1, 1, 5]))
    mouse(hid).brightness()
    assert hid.sent[0][8:10] == bytes([1, p.SCROLL_LED])


def test_apply_effect_and_frame():
    hid = FakeHid()
    m = mouse(hid)
    m.apply_effect("static", color=(1, 2, 3))
    assert hid.sent[-1] == p.effect_static(1, 2, 3)
    m.send_frame([(1, 2, 3)] * m.MATRIX_COLS)
    assert hid.sent[-2] == p.custom_frame(0, 0, [(1, 2, 3)] * 11) and hid.sent[-1] == p.effect_custom()
    with pytest.raises(ValueError):
        m.apply_effect("disco")
    with pytest.raises(ValueError):
        m.send_frame([(0, 0, 0)])


def test_matrix_and_zones_pinned():
    # MATRIX_COLS is OpenRazer's RazerBasiliskV3.MATRIX_DIMS = [1, 11].
    # ZONES is PROVISIONAL (not yet mapped on hardware with the user).
    assert Basilisk.MATRIX_COLS == 11
    assert Basilisk.ZONES == {"logo": range(0, 1), "wheel": range(1, 2), "strip": range(2, 11)}
    assert Basilisk.EFFECTS == ("off", "static", "spectrum", "wave")
