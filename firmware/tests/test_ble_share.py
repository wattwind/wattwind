"""Heart rate sharing (ble_share.py) with stand-in bluetooth / aioble modules, and its hooks in ble_sensors."""
import asyncio
import importlib
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


class FakeChar:
    def __init__(self, svc, uuid, read=False, notify=False, initial=None):
        self.uuid, self.read, self.notify, self.initial = uuid, read, notify, initial
        self.writes = []
        svc.chars.append(self)

    def write(self, data, send_update=False):
        self.writes.append((data, send_update))


class FakeService:
    def __init__(self, uuid):
        self.uuid = uuid
        self.chars = []


class FakeConn:
    def __init__(self, addr="11:22:33:44:55:66"):
        self.device = types.SimpleNamespace(addr_hex=lambda: addr)
        self.connected = True
        self.disconnects = 0

    def is_connected(self):
        return self.connected

    async def disconnect(self):
        self.disconnects += 1
        self.connected = False


class Radio:
    """aioble stand-in: advertise() hands out the queued connections, else times out."""
    def __init__(self):
        self.queue = []
        self.adverts = []
        self.registered = []
        self.stops = 0
        self.config = {}
        self.core = types.SimpleNamespace(ble=types.SimpleNamespace(gap_advertise=self.gap_advertise))

    def gap_advertise(self, interval_us, *a, **k):
        assert interval_us is None
        self.stops += 1

    async def advertise(self, interval_us, name=None, services=None, appearance=0, timeout_ms=None):
        self.adverts.append({"interval": interval_us, "name": name, "services": services, "appearance": appearance,
                             "timeout": timeout_ms})
        if self.queue:
            return self.queue.pop(0)
        await self.mod.asyncio.sleep(timeout_ms / 1000)    # nobody connects within the time
        raise asyncio.TimeoutError()

    def register_services(self, *svcs):
        self.registered.extend(svcs)


@pytest.fixture
def share(monkeypatch):
    radio = Radio()
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(UUID=UUID))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(
        DeviceDisconnectedError=Exception, Service=FakeService, Characteristic=FakeChar,
        register_services=radio.register_services, advertise=radio.advertise, core=radio.core,
        config=lambda **kw: radio.config.update(kw)))
    if not hasattr(time, "ticks_ms"):
        monkeypatch.setattr(time, "ticks_ms", lambda: int(time.monotonic() * 1000), raising=False)
        monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    import config
    import state
    importlib.reload(state)
    for m in ("ble_share", "ble_sensors"):
        sys.modules.pop(m, None)
    import ble_share
    monkeypatch.setattr(ble_share, "adv_name", lambda: "WattWind-1A2B HR")
    radio.mod = ble_share
    cfg = dict(config.DEFAULTS)
    return ble_share, state, radio, cfg


def drive(bs, cfg, steps):
    """Run bs.run(cfg) with instant sleeps; steps is a list of callables, one called before each sleep."""
    real_sleep = asyncio.sleep
    todo = list(steps)

    async def fast_sleep(_s):
        if not todo:
            raise asyncio.CancelledError()
        todo.pop(0)()
        await real_sleep(0)

    async def main():
        bs.asyncio = types.SimpleNamespace(sleep=fast_sleep, TimeoutError=asyncio.TimeoutError)
        try:
            await bs.run(cfg)
        except asyncio.CancelledError:
            pass
        finally:
            bs.asyncio = asyncio

    asyncio.run(main())


def test_is_share_names(share):
    ble_share = share[0]
    assert ble_share.is_share("WattWind-1A2B HR") and ble_share.is_share("WattWind HR")
    for name in ("", None, "HRM-Pro:123456", "WattWind-1A2B", "Polar H10 HR", "wattwind HR"):
        assert not ble_share.is_share(name)


def test_name_fits_one_advertising_packet():
    # flags (3) + 16-bit service list (4) + name (2 + len) + appearance (4) must stay within 31 bytes
    assert 3 + 4 + 2 + len("WattWind-1A2B HR") + 4 < 31


def test_off_by_default_never_advertises(share):
    bs, state, radio, cfg = share
    assert cfg["hr_share"] is False
    drive(bs, cfg, [lambda: None] * 3)
    assert radio.adverts == [] and radio.registered == [] and state.share == "off" and radio.stops == 0


def test_follower_never_shares(share):
    bs, state, radio, cfg = share
    cfg.update(hr_share=True, follow_id="WattWind-1111")
    assert not bs.enabled(cfg)
    drive(bs, cfg, [lambda: None] * 3)
    assert radio.adverts == []


def test_update_coming_in_pauses_advertising(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    state.update_until_s = state.uptime_s + 60
    drive(bs, cfg, [lambda: None] * 3)
    assert radio.adverts == [] and state.share == "off"


def test_advertises_as_heart_rate_sensor(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    calls = []
    drive(bs, cfg, [lambda: calls.append(state.share)] * 2)   # nobody connects: advertising restarts
    assert len(radio.adverts) == 3 and calls == ["waiting", "waiting"]
    a = radio.adverts[0]
    assert a["name"] == "WattWind-1A2B HR" and a["services"] == [UUID(0x180D)] and a["appearance"] == 0x0341
    assert a["timeout"] == bs.ADV_RECHECK_MS
    assert radio.config == {"gap_name": "WattWind-1A2B HR"}     # the name apps show after connecting
    svc = radio.registered[0]
    assert svc.uuid == UUID(0x180D)
    hr, loc = svc.chars
    assert hr.uuid == UUID(0x2A37) and hr.notify and loc.uuid == UUID(0x2A38) and loc.initial == b"\x01"


def test_services_registered_once(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    radio.queue = [FakeConn(), FakeConn()]
    conns = list(radio.queue)

    def drop(i):
        def f():
            conns[i].connected = False
        return f
    drive(bs, cfg, [drop(0), drop(1)])
    assert len(radio.registered) == 1 and len(radio.adverts) >= 2


def test_connected_receiver_gets_fresh_readings_then_waits_again(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    conn = FakeConn()
    radio.queue = [conn]
    seen = []

    def connected():
        seen.append(state.share)
        bs.send(b"\x10\x8c\x00\x03")              # 140 bpm with one beat time
        bs.send(bytearray(b"\x00\x8d"))

    def gone():
        conn.connected = False
    drive(bs, cfg, [connected, gone])
    assert seen == ["connected"]
    hr = radio.registered[0].chars[0]
    assert hr.writes == [(b"\x10\x8c\x00\x03", True), (b"\x00\x8d", True)]
    assert state.share_sent == 2
    assert state.share == "waiting" and bs._conn is None
    bs.send(b"\x00\x90")                           # nobody connected: nothing written
    assert len(hr.writes) == 2


def test_switched_off_while_connected_disconnects(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    conn = FakeConn()
    radio.queue = [conn]

    def off():
        cfg["hr_share"] = False
    drive(bs, cfg, [off] + [lambda: None] * 8)
    assert conn.disconnects == 1 and state.share == "off" and bs._conn is None
    # BTstack restarts advertising when a connection ends: stopped again for a few seconds
    assert radio.stops == bs.STOP_PASSES
    bs.send(b"\x00\x90")
    assert radio.registered[0].chars[0].writes == []


def test_send_without_registration_or_setting_is_harmless(share):
    bs, state, radio, cfg = share
    bs.send(b"\x00\x90")                 # never registered
    bs._cfg = cfg
    bs._hr_ch = FakeChar(FakeService(UUID(0x180D)), UUID(0x2A37), notify=True)
    bs._conn = FakeConn()
    bs.send(b"\x00\x90")                 # setting off
    assert bs._hr_ch.writes == []


def test_send_error_does_not_raise(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    bs._cfg = cfg
    bs._conn = FakeConn()

    class Broken:
        def write(self, data, send_update=False):
            raise OSError(-128)
    bs._hr_ch = Broken()
    bs.send(b"\x00\x90")                 # must not raise into the strap's notification handler


# ---- hooks in ble_sensors -------------------------------------------------------------------------------------------

A = "aa:bb:cc:dd:ee:01"


@pytest.fixture
def sensors(share, monkeypatch):
    bs_share, state, radio, cfg = share
    import config
    monkeypatch.setattr(config, "save", lambda c: None)
    import ble_sensors
    ble_sensors._cfg = cfg
    sent = []
    monkeypatch.setattr(bs_share, "send", lambda d: sent.append(bytes(d)))
    return ble_sensors, state, sent


def test_strap_readings_are_passed_on(sensors):
    bsn, state, sent = sensors
    link = bsn.Link(None, A)
    link.roles = ["hr"]
    bsn._claim("hr", A)
    link.on_hr(bytes([0, 151]))
    assert state.hr == 151 and sent == [bytes([0, 151])]


def test_strap_not_worn_is_not_passed_on(sensors):
    bsn, state, sent = sensors
    link = bsn.Link(None, A)
    link.roles = ["hr"]
    bsn._claim("hr", A)
    link.on_hr(bytes([0x04, 80]))          # contact supported, not detected
    assert state.hr is None and sent == []


def test_other_strap_not_passed_on(sensors):
    bsn, state, sent = sensors
    link = bsn.Link(None, A)
    link.roles = ["hr"]                    # this link doesn't own the hr role
    link.on_hr(bytes([0, 151]))
    assert sent == []


class Result:
    def __init__(self, addr, name, uuids):
        self.device = types.SimpleNamespace(addr_hex=lambda: addr)
        self._name, self._uuids, self.rssi = name, uuids, -60

    def name(self):
        return self._name

    def services(self):
        return iter(self._uuids)


class Scan:
    def __init__(self, results):
        self.results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        self.it = iter(self.results)
        return self

    async def __anext__(self):
        try:
            return next(self.it)
        except StopIteration:
            raise StopAsyncIteration


def test_a_fan_sharing_heart_rate_is_never_taken_as_strap(sensors, monkeypatch):
    bsn, state, _ = sensors
    results = [Result("aa:bb:cc:dd:ee:09", "WattWind-77AA HR", [UUID(0x180D)]),
               Result(A, "HRM-Pro", [UUID(0x180D)])]
    monkeypatch.setattr(bsn.aioble, "scan", lambda *a, **k: Scan(results), raising=False)
    dev = asyncio.run(bsn._find())
    assert dev.addr_hex() == A
    results.pop()                          # only the other fan around: nothing taken
    assert asyncio.run(bsn._find()) is None
    found = asyncio.run(bsn.scan_nearby())
    assert found == []                     # and not listed as a sensor to choose


def test_switched_off_while_waiting_stops_advertising(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True

    def off():
        cfg["hr_share"] = False
    drive(bs, cfg, [off] + [lambda: None] * 8)     # first sleep = the advertising timeout
    assert state.share == "off" and radio.stops == bs.STOP_PASSES


def test_firmware_update_stops_advertising_then_resumes(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True

    def update():
        state.update_until_s = state.uptime_s + 60

    def done():
        state.update_until_s = 0
    drive(bs, cfg, [update] + [lambda: None] * 6 + [done, lambda: None])
    assert radio.stops == bs.STOP_PASSES and state.share == "waiting"
    assert len(radio.adverts) == 3              # 1 before the update, 2 after (one timed out)
