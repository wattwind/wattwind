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


class _Chr:
    def __init__(self, value=b""):
        self.value = value
        self.writes = []

    async def write(self, data, response=False):
        self.writes.append(bytes(data))

    async def subscribe(self, notify=False, indicate=False):
        pass

    async def read(self, timeout_ms=None):
        return self.value


class _Svc:
    def __init__(self, uuid, chars):
        self.uuid = UUID(uuid)
        self.chars = chars

    async def characteristic(self, uuid):
        return self.chars.get(uuid.v)


class _Conn:
    def __init__(self, svcs):
        self.svcs = svcs

    async def services(self):
        for s in self.svcs:
            yield s


CORE_SVC = "00002100-5b1e-4347-b07c-97b514dae121"


def _core_conn(name):
    return _Conn([_Svc(0x1800, {0x2A00: _Chr(name)}),
                  _Svc(CORE_SVC, {"00002101-5b1e-4347-b07c-97b514dae121": _Chr(),
                                  "00002102-5b1e-4347-b07c-97b514dae121": _Chr()})])


def test_sensor_without_advertised_name_gets_its_device_name(ble):
    # The real CORE advertises no name (2026-11-08): the name is read from Generic Access after connecting.
    import asyncio
    bs, state, _ = ble
    bs._names[A] = ""
    link = bs.Link(_core_conn(b"CORE 12AB"), A)
    assert asyncio.run(link.setup()) == ["core"]
    assert bs._names[A] == "CORE 12AB"
    bs._claim("core", A)
    assert state.core_name == "CORE 12AB"


def test_core_heart_rate_input_cleared_on_connect(ble):
    # A CORE that got the fan's heart rate before a restart keeps the last bpm and says "receiving" (measured
    # 2026-11-08): clearing it on connect lets CORE say "none" again, so the fan starts sending the live value.
    import asyncio
    bs, _, _ = ble
    conn = _core_conn(b"CORE 12AB")
    link = bs.Link(conn, A)
    asyncio.run(link.setup())
    assert link.core_ctrl.writes == [b""] and not link.core_fwd


def test_saved_sensors_signal_is_kept(ble):
    bs, state, _ = ble
    bs._cfg["hr_addr"] = A
    state.uptime_s = 10
    bs._hear(B, -60)                                          # not a saved sensor: not kept
    bs._hear(A, -80)
    assert state.heard == {A: (-80, 10)}
    bs._cfg["hr_addr"] = B                                     # another strap chosen: the old one goes
    bs._hear(B, -61)
    assert state.heard == {B: (-61, 10)}


def test_core_raw_packet_and_advertising_kept_as_hex(ble):
    import types
    bs, state, _ = ble
    bs._cfg["core_addr"] = A
    link = bs.Link(None, A)
    bs._claim("core", A)
    pkt = bytes([0x37, 0x6E, 0x0E, 0xDC, 0x0D, 0, 0, 0x24, 0x4C, 0])
    link.on_core(pkt)
    assert state.core_raw == pkt.hex() and link.core_logged == 1
    bs._hear(A, -80, types.SimpleNamespace(adv_data=b"", resp_data=None))
    assert state.core_adv == ["020106", ""]


def test_advertised_name_is_kept(ble):
    import asyncio
    bs, _, _ = ble
    bs._names[A] = "Advertised"
    asyncio.run(bs.Link(_core_conn(b"Other"), A).setup())
    assert bs._names[A] == "Advertised"
