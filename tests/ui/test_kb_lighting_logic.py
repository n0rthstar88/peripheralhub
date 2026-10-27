import pytest

from peripheralhub.ui.pages.kb_common import status_banner
from peripheralhub.ui.pages.kb_lighting import rgb_to_via_hs, via_hs_to_rgb
from peripheralhub.wd75.device import Connection, Wd75State


def test_hs_conversion_roundtrip():
    assert rgb_to_via_hs(255, 0, 0) == (0, 255)
    r, g, b = via_hs_to_rgb(85, 255)
    assert g > r and g > b
    for h in (0, 40, 85, 130, 200):
        assert abs(rgb_to_via_hs(*via_hs_to_rgb(h, 255))[0] - h) <= 1
    assert rgb_to_via_hs(255, 255, 255)[1] == 0


@pytest.mark.parametrize("state,conn,expected", [
    (Wd75State.ASLEEP, Connection.DONGLE,
     ("Keyboard asleep", "Press any key on the keyboard, then try again.")),
    (Wd75State.NO_PERMISSION, Connection.USB,
     ("Allow access", "PeripheralHub needs a one-time permission to talk to your keyboard.")),
    (Wd75State.BLUETOOTH_ONLY, Connection.BLUETOOTH,
     ("Settings need the cable or 2.4G dongle", "Battery is live over Bluetooth.")),
    (Wd75State.DISCONNECTED, Connection.DISCONNECTED,
     ("Keyboard not connected", "Connect it with the cable or the 2.4G dongle.")),
    (Wd75State.READY, Connection.USB, None),
])
def test_banner_texts(state, conn, expected):
    assert status_banner(state, conn) == expected
