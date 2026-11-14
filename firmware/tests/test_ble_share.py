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
        self.uuid, self.read, self.can_notify, self.initial = uuid, read, notify, initial
        self.writes = []
        self.notified = []                  # (conn, data): what each receiver got
        svc.chars.append(self)

    def write(self, data, send_update=False):
        self.writes.append((data, send_update))

    def notify(self, conn, data=None):
        if not conn.connected:
            raise OSError(-128)             # like BTstack for a link that is gone
        self.notified.append((conn, data))


class FakeService:
    def __init__(self, uuid):
        self.uuid = uuid
        self.chars = []


class FakeConn:
    _next = 64

    def __init__(self, addr="11:22:33:44:55:66"):
        self.device = types.SimpleNamespace(addr_hex=lambda: addr)
        self.connected = True
        self.disconnects = 0
        FakeConn._next += 1
        self._conn_handle = FakeConn._next

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

    async def fast_sleep_ms(_ms):
        await real_sleep(0)                 # short pauses don't use up a step

    async def main():
        bs.asyncio = types.SimpleNamespace(sleep=fast_sleep, sleep_ms=fast_sleep_ms, create_task=asyncio.create_task,
                                           TimeoutError=asyncio.TimeoutError)
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
    assert hr.uuid == UUID(0x2A37) and hr.can_notify and loc.uuid == UUID(0x2A38) and loc.initial == b"\x01"


def test_services_registered_once(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    radio.queue = [FakeConn(), FakeConn()]
    conns = list(radio.queue)

    def tick():
        for c in conns:
            if c._conn_handle in bs._rx:
                c.connected = False         # each receiver leaves right after connecting
    drive(bs, cfg, [tick] * 30)
    assert len(radio.registered) == 1 and len(radio.adverts) >= 2


def test_connected_receiver_gets_fresh_readings_then_waits_again(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    conn = FakeConn()
    radio.queue = [conn]
    seen = []

    def tick():
        if bs._rx and not seen:
            seen.append(state.share)
            bs.send(b"\x10\x8c\x00\x03")      # 140 bpm with one beat time
            bs.send(bytearray(b"\x00\x8d"))
        elif seen and conn.connected:
            conn.connected = False
    drive(bs, cfg, [tick] * 20)
    assert seen == ["connected"]
    hr = radio.registered[0].chars[0]
    assert hr.writes == [(b"\x10\x8c\x00\x03", False), (b"\x00\x8d", False)]   # stored, not sent to every link
    assert hr.notified == [(conn, b"\x10\x8c\x00\x03"), (conn, b"\x00\x8d")]      # sent to the receiver
    assert state.share_sent == 2
    assert state.share == "waiting" and bs._rx == {} and state.share_receivers == 0
    bs.send(b"\x00\x90")                           # nobody connected: nothing sent
    assert len(hr.notified) == 2


def test_switched_off_while_connected_disconnects(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    conn = FakeConn()
    radio.queue = [conn]

    def tick():
        if bs._rx:
            cfg["hr_share"] = False
    drive(bs, cfg, [tick] * 20)
    assert conn.disconnects == 1 and state.share == "off" and bs._rx == {}
    # BTstack restarts advertising when a connection ends: stopped again for a few seconds
    assert radio.stops == bs.STOP_PASSES
    bs.send(b"\x00\x90")
    assert radio.registered[0].chars[0].notified == []


def test_send_without_registration_or_setting_is_harmless(share):
    bs, state, radio, cfg = share
    bs.send(b"\x00\x90")                 # never registered
    bs._cfg = cfg
    bs._hr_ch = FakeChar(FakeService(UUID(0x180D)), UUID(0x2A37), notify=True)
    c = FakeConn()
    bs._rx = {c._conn_handle: {"conn": c, "addr": "x", "sent": 0, "paired": False}}
    bs.send(b"\x00\x90")                 # setting off
    assert bs._hr_ch.writes == [] and bs._hr_ch.notified == []
    bs._rx = {}


def test_send_error_does_not_raise(share):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    bs._cfg = cfg
    c = FakeConn()
    bs._rx = {c._conn_handle: {"conn": c, "addr": "x", "sent": 0, "paired": False}}

    class Broken:
        def write(self, data, send_update=False):
            raise OSError(-128)

        def notify(self, conn, data=None):
            raise OSError(-128)
    bs._hr_ch = Broken()
    bs.send(b"\x00\x90")                 # must not raise into the strap's notification handler
    bs._rx = {}


# ---- several receivers ----------------------------------------------------------------------------------------------


def test_one_receiver_on_every_micropython_file(share, monkeypatch):
    """Option A (2026-11-07): with 2+ receivers the radio refuses sensor reconnects (TEST-REPORT-conn.md part 2)."""
    bs = share[0]
    import mpbuild
    assert bs.MAX_RECEIVERS == 1
    for n in (1, 2, 99):
        monkeypatch.setattr(mpbuild, "number", lambda text=None, n=n: n)
        assert bs.max_receivers() == 1


def test_no_receiver_when_the_older_file_has_strap_trainer_and_core(share, monkeypatch):
    """The older file has 3 connections: strap + trainer + CORE leave none (the page says so)."""
    bs, state = share[0], share[1]
    import mpbuild
    monkeypatch.setattr(mpbuild, "number", lambda text=None: 1)
    assert bs.max_receivers({"core_addr": ""}) == 1
    assert bs.max_receivers({"core_addr": "aa:bb:cc:dd:ee:01"}) == 0
    state.core_connected = True                               # a CORE taken as the first one found
    assert bs.max_receivers({"core_addr": ""}) == 0
    monkeypatch.setattr(mpbuild, "number", lambda text=None: 2)
    assert bs.max_receivers({"core_addr": "aa:bb:cc:dd:ee:01"}) == 1


def test_the_patch_keeps_one_incoming_connection():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    patch = open(os.path.join(here, "..", "..", "micropython", "btstack-pairing.patch"), encoding="utf-8").read()
    assert "+    gap_set_max_number_peripheral_connections(1);" in patch


def test_three_receivers_each_get_every_reading_and_a_fourth_waits(share, monkeypatch):
    """The code handles N receivers (N is 1 in use): checked with N = 3."""
    bs, state, radio, cfg = share
    monkeypatch.setattr(bs, "max_receivers", lambda cfg=None: 3)
    cfg["hr_share"] = True
    conns = [FakeConn("aa:00:00:00:00:0%d" % i) for i in range(4)]
    radio.queue = list(conns)
    log = {"full": None, "sent": False, "freed": False}

    def tick():
        if len(bs._rx) == 3 and log["full"] is None:
            log["full"] = len(radio.adverts)          # adverts so far: advertising stops while full
            log["receivers"] = state.share_receivers
            bs.send(b"\x00\x7b")
            log["sent"] = True
        elif log["sent"] and not log["freed"]:
            if len(radio.adverts) != log["full"]:
                log["advertised_while_full"] = True
            conns[1].connected = False                # one leaves: the fourth gets in
            log["freed"] = True
        elif log["freed"] and conns[3]._conn_handle in bs._rx:
            log["fourth_in"] = True
    drive(bs, cfg, [tick] * 40)
    hr = radio.registered[0].chars[0]
    got = [c for c, d in hr.notified if d == b"\x00\x7b"]
    assert sorted(id(c) for c in got) == sorted(id(c) for c in conns[:3])   # each of the three, once
    assert log["receivers"] == 3 and "advertised_while_full" not in log
    assert log.get("fourth_in")                       # the fourth connected after one left
    assert state.share_limit == 3
    bs._rx.clear()


def test_one_lost_receiver_does_not_stop_the_others(share, monkeypatch):
    bs, state, radio, cfg = share
    cfg["hr_share"] = True
    bs._cfg = cfg
    bs._hr_ch = FakeChar(FakeService(UUID(0x180D)), UUID(0x2A37), notify=True)
    a, b, c = FakeConn(), FakeConn(), FakeConn()
    b.connected = False                               # gone, not yet noticed
    bs._rx = {x._conn_handle: {"conn": x, "addr": "x", "sent": 0, "paired": False} for x in (a, b, c)}
    bs.send(b"\x00\x50")
    assert [x for x, d in bs._hr_ch.notified] == [a, c]
    bs._rx = {}


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
