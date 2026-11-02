"""Role logic of ble_sensors.py with stand-in bluetooth / aioble modules."""
import struct
import sys
import time
import types

import pytest


class UUID:
    def __init__(self, v):
        self.v = v

    def __eq__(self, other):
        return isinstance(other, UUID) and self.v == other.v

    def __hash__(self):
        return hash(self.v)


@pytest.fixture
def ble(monkeypatch):
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(UUID=UUID))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(DeviceDisconnectedError=Exception))
    if not hasattr(time, "ticks_ms"):
        monkeypatch.setattr(time, "ticks_ms", lambda: int(time.monotonic() * 1000), raising=False)
        monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    import importlib
    import config
    import state
    importlib.reload(state)
    sys.modules.pop("ble_sensors", None)
    import ble_sensors as bs
    saved = []
    monkeypatch.setattr(config, "save", lambda c: saved.append(dict(c)))
    bs._cfg = dict(config.DEFAULTS)
    return bs, state, saved


A = "aa:bb:cc:dd:ee:01"
B = "aa:bb:cc:dd:ee:02"


def test_offers(ble):
    bs, _, _ = ble
    assert bs._offers([UUID(0x180D), UUID(0x1818), UUID(0x1826)]) == ["hr", "power"]
    assert bs._offers([UUID(0x1826)]) == ["power"]
    assert bs._offers([UUID(0x1816)]) == []


def test_first_found_is_saved_then_only_that_one(ble):
    bs, state, saved = ble
    assert bs._may_take("hr", A)
    bs._claim("hr", A)
    assert bs._cfg["hr_addr"] == A and saved and state.hr_connected
    bs._release("hr", A)
    assert not state.hr_connected
    assert bs._may_take("hr", A) and not bs._may_take("hr", B)


def test_saved_address_respected(ble):
    bs, _, _ = ble
    bs._cfg["power_addr"] = B
    assert not bs._may_take("power", A) and bs._may_take("power", B)


def test_one_device_both_roles_cp_and_ftms(ble):
    # Like the simulator: CP without crank data + FTMS with cadence.
    bs, state, _ = ble
    link = bs.Link(None, A)
    link.has_cp = True
    link.roles = ["hr", "power"]
    for r in link.roles:
        bs._claim(r, A)
    link.on_hr(bytes([0, 151]))
    link.on_cp(struct.pack("<Hh", 0, 240))
    bike = struct.pack("<HHHh", 0x0044, 0, 176, 999)     # FTMS power must not override CP
    link.on_bike(bike)
    assert (state.hr, state.power, state.cadence) == (151, 240, 88)


def test_ftms_only_gives_power(ble):
    bs, state, _ = ble
    link = bs.Link(None, A)
    bs._claim("power", A)
    link.on_bike(struct.pack("<HHHh", 0x0044, 0, 180, 205))
    assert (state.power, state.cadence) == (205, 90)


def test_released_role_ignores_data(ble):
    bs, state, _ = ble
    link = bs.Link(None, A)
    bs._claim("hr", A)
    bs._release("hr", A)
    link.on_hr(bytes([0, 99]))
    assert state.hr is None


def test_release_by_other_link_is_ignored(ble):
    bs, state, _ = ble
    bs._claim("hr", A)
    bs._release("hr", B)
    assert state.hr_connected and bs._owner["hr"] == A


def _linked(bs, roles):
    link = bs.Link(None, A)
    link.roles = list(roles)
    for r in roles:
        bs._claim(r, A)
    return link


def test_review_keeps_link_while_choice_unchanged(ble):
    bs, _, _ = ble
    link = _linked(bs, ["hr", "power"])
    assert not bs._review(link) and link.roles == ["hr", "power"]


def test_forget_disconnects_whole_link(ble):
    # Forget power on a device serving both roles: drop the link so both are re-checked.
    bs, _, _ = ble
    link = _linked(bs, ["hr", "power"])
    bs._cfg["power_addr"] = ""
    assert bs._review(link)


def test_other_sensor_chosen_drops_only_that_role(ble):
    bs, state, _ = ble
    link = _linked(bs, ["hr", "power"])
    bs._cfg["power_addr"] = B
    assert not bs._review(link)
    assert link.roles == ["hr"] and bs._owner["power"] is None and state.hr_connected


def test_other_sensor_chosen_for_only_role_disconnects(ble):
    bs, _, _ = ble
    link = _linked(bs, ["hr"])
    bs._cfg["hr_addr"] = B
    assert bs._review(link) and link.roles == []


def test_first_found_never_takes_another_riders_strap(ble):
    import config
    import profiles
    bs, _, _ = ble
    profiles.ensure(bs._cfg)
    profiles.add(bs._cfg, "Anna", config.DEFAULTS)
    bs._cfg["hr_addr"] = B                               # Anna's strap
    profiles.sync(bs._cfg)
    profiles.activate(bs._cfg, 0)                        # Rider 1 has no strap yet
    assert not bs._may_take("hr", B)                     # Anna's strap is not taken over by Rider 1
    assert bs._may_take("hr", A)                         # an unknown strap is
