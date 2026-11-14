"""BLE central: heart rate strap, trainer (power, cadence) and CORE body temperature sensor, at the same time.

Three roles: "hr" (Heart Rate 0x180D), "power" (Cycling Power 0x1818, Fitness Machine 0x1826 as fallback) and
"core" (CORE's Core Body Temperature Service, release 1.1: core / skin temperature, Heat Strain Index, quality).
One device may serve several (a Pico-based BLE simulator does). A role only takes a device whose address matches
the saved one (config hr_addr / power_addr / core_addr); if none is saved, the first matching device found is used
and saved, so other riders' sensors are left alone. Strap and CORE are per rider (profiles).

CORE: when it reports that it gets no heart rate, the fan sends it the strap's (Control Point 0x13, once a
second; an empty 0x13 stops it). While CORE isn't connected, its saved address's advertising still carries the
core temperature (beacon): read during the scans (no Heat Strain Index there).
The radio chip allows 4 outgoing connections: strap + trainer + CORE = 3 (measured).

Cadence: from crank data in Cycling Power if the trainer sends it, otherwise from the FTMS
Indoor Bike Data. Values go stale (None) after 5 s without a notification.
Reconnects with backoff. This task never touches relays; it only writes sensor values to state.
"""

import asyncio
import time
import binascii
import bluetooth

import aioble
import config
import profiles
import state
import detail
import ble_share
from ble_parse import parse_hr_full, HrContact, parse_cp, parse_bike, CrankCadence, parse_core, parse_core_beacon

HR_SVC = bluetooth.UUID(0x180D)
HR_CHR = bluetooth.UUID(0x2A37)
CP_SVC = bluetooth.UUID(0x1818)
CP_CHR = bluetooth.UUID(0x2A63)
FTMS_SVC = bluetooth.UUID(0x1826)
BIKE_CHR = bluetooth.UUID(0x2AD2)
CORE_SVC = bluetooth.UUID("00002100-5b1e-4347-b07c-97b514dae121")       # Core Body Temperature Service
CORE_TEMP_CHR = bluetooth.UUID("00002101-5b1e-4347-b07c-97b514dae121")  # measurement (notify, 1 Hz)
CORE_CTRL_CHR = bluetooth.UUID("00002102-5b1e-4347-b07c-97b514dae121")  # control point (write + indicate)
CORE_COMPANIES = (0x0BF6, 0xF60B)    # manufacturer data in CORE's advertising: the beacon. The real CORE sends the
                                     # bytes F6 0B (= 0x0BF6, measured 2026-11-08); the maker's notes show 0B F6
CORE_STALE_MS = 15000                # core temperature changes slowly; CORE notifies about once a second
BEACON_STALE_MS = 90000
BATT_SVC = bluetooth.UUID(0x180F)     # Battery Service (optional; straps and power meters often have it)
BATT_CHR = bluetooth.UUID(0x2A19)
BATT_READ_S = 600                    # battery level is read on connect, then this often
GAP_SVC = bluetooth.UUID(0x1800)      # Generic Access: the device name, for sensors that advertise none (CORE)
NAME_CHR = bluetooth.UUID(0x2A00)

ROLES = ("hr", "power", "core")
CORE_SCAN_S = 60           # strap + trainer found, no CORE saved: look for a CORE only this often
SCAN_MS = 5000
UI_SCAN_MS = 4000
CONNECT_TIMEOUT_MS = 10000
STALE_MS = 5000
RETRY_MIN_S = 5            # nothing found / connect failed: wait 5, 10, 15, 15 ... s
RETRY_MAX_S = 15           # a strap that drops out mid-ride is back within ~20 s

# aioble cancels a running scan when it connects, so scans and connection attempts take turns.
_radio = asyncio.Lock()
_owner = {"hr": None, "power": None, "core": None}   # role -> address of the link serving it
_names = {}                            # address -> advertised name (or the device name read after connecting)
_last = {"hr": None, "power": None, "core": None}    # role -> ticks_ms of the last notification
_beacon = {"ms": None}                 # ticks_ms of the last CORE beacon reading
_cfg = None
_expire_task = None


def log(*args):
    """Sensor events: to USB serial and the logbook (not "bad packet", which can repeat every second)."""
    print("[{}] ble:".format(state.uptime_s), *args)
    if args and args[0] != "bad packet from":
        try:
            import logbook
            logbook.write("up={} ble: {}".format(state.uptime_s, " ".join(str(a) for a in args)))
        except Exception:
            pass


SWITCH_SCANS = 2            # another rider's strap seen alone in this many scans in a row: switch rider
_other = [None, 0]           # [profile index, consecutive scans] of another rider's strap


def _may_take(role, addr):
    saved = _cfg[role + "_addr"]
    if _owner[role] is not None:
        return False
    if role == "hr" and not saved:           # first found: never another rider's registered strap
        return profiles.owner_of(_cfg, addr) is None
    if role == "core" and not saved:         # ... nor another rider's CORE
        return profiles.owner_of(_cfg, addr, "core_addr") is None
    return not saved or saved == addr


def _offers(services):
    roles = []
    if HR_SVC in services:
        roles.append("hr")
    if CP_SVC in services or FTMS_SVC in services:
        roles.append("power")
    if CORE_SVC in services:
        roles.append("core")
    return roles


def _claim(role, addr):
    _owner[role] = addr
    setattr(state, role + "_connected", True)
    setattr(state, role + "_name", _names.get(addr, addr))
    if not _cfg[role + "_addr"]:
        _cfg[role + "_addr"] = addr
        profiles.sync(_cfg)              # the strap now belongs to the active rider
        config.save(_cfg)
        log("saved", addr, "as the", role, "sensor")


def _release(role, addr):
    if _owner[role] != addr:
        return
    _owner[role] = None
    _last[role] = None
    setattr(state, role + "_connected", False)
    setattr(state, role + "_name", "")
    if role == "hr":
        state.hr = None
        state.hr_off = None
    elif role == "core":
        _core_clear()
    else:
        state.power = None
        state.cadence = None


def _core_clear(keep_beacon=False):
    if keep_beacon and state.core_source == "beacon":
        return
    state.core_temp = state.core_skin = state.core_hsi = state.core_quality = state.core_hr_state = None
    state.core_hr = state.core_raw = None
    state.core_source = None


def _review(link):
    """Apply sensor choices made in the UI to a live link. Returns True to disconnect it.

    Forget (saved address cleared): drop the whole link, so a device serving both roles is
    re-checked; the next scan takes the first matching sensor (possibly the same one) and
    saves it. Another sensor chosen: release just that role."""
    for role in list(link.roles):
        saved = _cfg[role + "_addr"]
        if not saved:
            log(role, "sensor forgotten - disconnecting", link.addr)
            return True
        if saved != link.addr:
            log(role, "now uses", saved, "- dropping", link.addr)
            _release(role, link.addr)
            link.roles.remove(role)
    return not link.roles


class Link:
    """One connected device and the roles it serves."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.roles = []
        self.subs = []           # (characteristic, handler)
        self.has_cp = False      # power from Cycling Power (else from FTMS)
        self.cp_crank = False    # Cycling Power sends crank data (else cadence from FTMS)
        self.crank = CrankCadence(time.ticks_diff)
        self.hrc = HrContact(time.ticks_diff, addr in (_cfg or {}).get("hr_rr", []), time.ticks_ms())
                                                 # is the strap on the skin (any strap: what it reports)
        self.batt_ch = None
        self.core_ctrl = None        # CORE's control point (heart rate input)
        self.core_fwd = False        # sending the strap's heart rate to CORE
        self.core_logged = 0         # CORE packets written to the logbook as hex (the first 2 per connection)

    async def setup(self):
        services = []
        async for s in self.conn.services():
            services.append(s)

        def find(uuid):
            for s in services:
                if s.uuid == uuid:
                    return s
            return None

        if _may_take("hr", self.addr) and find(HR_SVC):
            ch = await find(HR_SVC).characteristic(HR_CHR)
            if ch:
                await ch.subscribe(notify=True)
                self.subs.append((ch, self.on_hr))
                self.roles.append("hr")
        if _may_take("power", self.addr):
            cp = find(CP_SVC)
            ftms = find(FTMS_SVC)
            cp_ch = await cp.characteristic(CP_CHR) if cp else None
            bike_ch = await ftms.characteristic(BIKE_CHR) if ftms else None
            if cp_ch:
                await cp_ch.subscribe(notify=True)
                self.subs.append((cp_ch, self.on_cp))
                self.has_cp = True
            if bike_ch:
                await bike_ch.subscribe(notify=True)
                self.subs.append((bike_ch, self.on_bike))
            if cp_ch or bike_ch:
                self.roles.append("power")
        if _may_take("core", self.addr) and find(CORE_SVC):
            ch = await find(CORE_SVC).characteristic(CORE_TEMP_CHR)
            if ch:
                await ch.subscribe(notify=True)
                self.subs.append((ch, self.on_core))
                self.roles.append("core")
                try:                 # answers come as indications: they must be switched on before a write
                    self.core_ctrl = await find(CORE_SVC).characteristic(CORE_CTRL_CHR)
                    if self.core_ctrl:
                        await self.core_ctrl.subscribe(indicate=True)
                except Exception:
                    self.core_ctrl = None
                if self.core_ctrl:
                    try:             # clear heart rate we may have sent before a restart: CORE keeps the last
                        await self.core_ctrl.write(b"", True)   # one and says "receiving" (2026-11-08)
                    except Exception:
                        pass
        if self.roles and find(BATT_SVC):
            try:
                self.batt_ch = await find(BATT_SVC).characteristic(BATT_CHR)
            except Exception:
                self.batt_ch = None
        if self.roles and not _names.get(self.addr) and find(GAP_SVC):
            try:                     # CORE advertises without a name: ask it
                ch = await find(GAP_SVC).characteristic(NAME_CHR)
                if ch:
                    _names[self.addr] = bytes(await ch.read(timeout_ms=2000)).decode()[:32].strip()
            except Exception:
                pass
        return self.roles

    async def _read_battery(self):
        try:
            data = await self.batt_ch.read(timeout_ms=2000)
            level = data[0] if data and data[0] <= 100 else None
        except Exception:
            return
        if "hr" in self.roles:
            state.hr_battery = level
        if "power" in self.roles:
            state.power_battery = level
        if "core" in self.roles:
            state.core_battery = level

    def _mine(self, role):
        if _owner[role] != self.addr:
            return False
        now = time.ticks_ms()
        if _last[role] is not None:
            detail.rec().gap(state.uptime_s, role, time.ticks_diff(now, _last[role]))   # gaps > 2 s, if recording
        _last[role] = now
        return True

    def on_hr(self, data):
        hr, contact, rr = parse_hr_full(data)
        if hr is None or _owner["hr"] != self.addr:
            return
        off = self.hrc.update(time.ticks_ms(), contact, rr, hr)
        state.hr_caps = self.hrc.caps()
        if rr and not off and _cfg is not None and self.addr not in _cfg.get("hr_rr", []):
            _cfg["hr_rr"] = (_cfg.get("hr_rr", []) + [self.addr])[-8:]   # remember: this strap sends beat times
            config.save(_cfg)
        if off != state.hr_off:
            state.hr_off = off
            log("heart rate: " + ({"contact": "strap not worn (no skin contact)", "beats": "strap not worn (no beat times)",
                                   "zero": "no valid reading (under 30 bpm)"}
                                  .get(off) or "strap worn again"))
        if off:
            state.hr = None              # a strap off the skin may keep sending its last value: not fresh
            return
        self._mine("hr")
        state.hr = hr
        ble_share.send(data)             # heart rate sharing, if on and an app is connected

    def on_core(self, data):
        raw = binascii.hexlify(bytes(data)).decode()
        if self.core_logged < 2:     # the real bytes, for checking the parser and the simulator later
            self.core_logged += 1
            log("CORE packet", raw)
        d = parse_core(data)
        if d is None or not self._mine("core"):
            return
        state.core_raw = raw
        state.core_temp = d["core"]
        state.core_skin = d["skin"]
        state.core_hsi = d["hsi"]
        state.core_quality = d["quality"]
        state.core_hr_state = d["hr_state"]
        state.core_hr = d["hr"]
        state.core_source = "link"

    async def _core_heart_rate(self):
        """Once a second: CORE without heart rate gets the strap's (0x13); none to send: stop (empty 0x13)."""
        if not self.core_ctrl:
            return
        hr = state.hr
        try:
            if hr is not None and (self.core_fwd or state.core_hr_state == "none"):
                await self.core_ctrl.write(bytes([0x13, int(hr) & 0xFF]), True)
                if not self.core_fwd:
                    self.core_fwd = True
                    log("CORE gets no heart rate: sending the strap's")
            elif self.core_fwd and hr is None:
                await self.core_ctrl.write(b"\x13", True)
                self.core_fwd = False
                log("no heart rate to send to CORE: stopped")
        except Exception as e:
            print("ble: CORE heart rate input failed", repr(e))

    def on_cp(self, data):
        power, crank = parse_cp(data)
        if power is None or not self._mine("power"):
            return
        state.power = power
        if crank:
            self.cp_crank = True
            state.cadence = self.crank.update(crank[0], crank[1], time.ticks_ms())

    def on_bike(self, data):
        power, cadence = parse_bike(data)
        if not self._mine("power"):
            return
        if power is not None and not self.has_cp:
            state.power = power
        if cadence is not None and not self.cp_crank:
            state.cadence = round(cadence)

    async def _consume(self, ch, handler):
        try:
            while True:
                data = await ch.notified()
                try:
                    handler(data)
                except Exception as e:     # one bad packet must not end the stream
                    log("bad packet from", self.addr, bytes(data), repr(e))
        except aioble.DeviceDisconnectedError:
            pass

    async def serve(self):
        for role in self.roles:
            _claim(role, self.addr)
        log("connected", _names.get(self.addr, ""), self.addr, "for", ", ".join(self.roles))
        tasks = [asyncio.create_task(self._consume(ch, h)) for ch, h in self.subs]
        batt_due = time.ticks_ms()
        try:
            while self.conn.is_connected():
                if _review(self):
                    await self.conn.disconnect()
                    break
                if self.batt_ch and time.ticks_diff(time.ticks_ms(), batt_due) >= 0:
                    batt_due = time.ticks_add(time.ticks_ms(), BATT_READ_S * 1000)
                    await self._read_battery()
                if "core" in self.roles:
                    await self._core_heart_rate()
                await asyncio.sleep(1)
        finally:
            for t in tasks:
                t.cancel()
            for role in self.roles:
                _release(role, self.addr)
            if "hr" in self.roles:
                state.hr_battery = None
            if "power" in self.roles:
                state.power_battery = None
            if "core" in self.roles:
                state.core_battery = None
            log("disconnected", self.addr)


def _hear(addr, rssi, result=None):
    """A saved sensor's signal, each time its advertising is heard: the page shows it (MicroPython can't read the
    signal of a connection). Only the saved sensors are kept."""
    saved = [_cfg.get(r + "_addr") for r in ROLES] if _cfg else []
    if addr in saved:
        for a in list(state.heard):
            if a not in saved:
                del state.heard[a]
        state.heard[addr] = (rssi, state.uptime_s)
        if result is not None and addr == _cfg.get("core_addr"):     # CORE's raw advertising / scan response
            state.core_adv = [binascii.hexlify(bytes(x or b"")).decode() for x in (result.adv_data, result.resp_data)]


async def _find():
    """Scan for a device that can take a free role. Returns (device, name) or None."""
    other = None                             # another rider's strap seen in this scan
    active_seen = False
    async with _radio:
        async with aioble.scan(SCAN_MS, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                addr = result.device.addr_hex()
                _hear(addr, result.rssi, result)
                _note_beacon(result, addr)
                if addr in _owner.values() or ble_share.is_share(result.name()):
                    continue                     # (a fan sharing heart rate is never taken as a strap)
                roles = _offers(list(result.services()))
                if "hr" in roles and _owner["hr"] is None:
                    who = profiles.owner_of(_cfg, addr)
                    if who is not None and who != _cfg.get("profile", 0):
                        other = (who, result.device, result.name() or "")
                        continue
                    if who is not None:
                        active_seen = True
                if any(_may_take(r, addr) for r in roles):
                    _names[addr] = result.name() or _names.get(addr, "")
                    return result.device
    # Straps only send while worn: if only another rider's strap is around, that rider is riding.
    if other and not active_seen and _owner["hr"] is None and not state.rider_by_hand:
        _other[1] = _other[1] + 1 if _other[0] == other[0] else 1
        _other[0] = other[0]
        if _other[1] >= SWITCH_SCANS:
            _other[0], _other[1] = None, 0
            profiles.activate(_cfg, other[0])
            config.save(_cfg)
            state.rider = profiles.name(_cfg)
            log("strap of", state.rider, "- switching rider")
            try:
                import logbook
                logbook.write("up={} rider {} (strap)".format(state.uptime_s, state.rider))
            except Exception:
                pass
            _names[other[1].addr_hex()] = other[2]
            return other[1]
    else:
        _other[0], _other[1] = None, 0
    return None


def _note_beacon(result, addr):
    """The saved CORE's temperature from its advertising, while it isn't connected (no Heat Strain Index there)."""
    if _owner["core"] is not None or not _cfg or addr != _cfg.get("core_addr"):
        return
    try:
        for cid, payload in result.manufacturer():
            t = parse_core_beacon(payload) if cid in CORE_COMPANIES else None
            if t is not None:
                state.core_temp = t
                state.core_skin = state.core_hsi = state.core_quality = state.core_hr_state = None
                state.core_hr = None
                state.core_source = "beacon"
                _beacon["ms"] = time.ticks_ms()
    except Exception:
        pass


async def _connect(device):
    addr = device.addr_hex()
    async with _radio:
        try:
            conn = await device.connect(timeout_ms=CONNECT_TIMEOUT_MS)
        except Exception as e:
            log("connect to", addr, "failed:", repr(e))
            return False
    link = Link(conn, addr)
    try:
        roles = await link.setup()
    except Exception as e:
        log("setup of", addr, "failed:", repr(e))
        roles = []
    if not roles:
        log(addr, "offers nothing usable, disconnecting")
        await conn.disconnect()
        return False
    asyncio.create_task(link.serve())
    return True


async def _search():
    retry_s = RETRY_MIN_S
    while True:
        if all(_owner[r] for r in ROLES) or state.uptime_s < state.update_until_s:
            await asyncio.sleep(1)          # all found, or a firmware update is coming in (Wi-Fi gets the radio)
            continue
        device = await _find()
        if device and await _connect(device):
            retry_s = RETRY_MIN_S
            continue
        if _owner["hr"] and _owner["power"] and not _owner["core"] and not _cfg.get("core_addr"):
            await asyncio.sleep(CORE_SCAN_S)    # most riders have no CORE: look now and then, not all the time
            continue
        await asyncio.sleep(retry_s)
        retry_s = min(retry_s * 2, RETRY_MAX_S)


async def _expire():
    while True:
        now = time.ticks_ms()
        for role in ROLES:
            last = _last[role]
            stale = CORE_STALE_MS if role == "core" else STALE_MS
            if last is None or time.ticks_diff(now, last) > stale:
                if role == "hr":
                    state.hr = None
                elif role == "core":
                    _core_clear(keep_beacon=True)
                else:
                    state.power = None
                    state.cadence = None
        if state.core_source == "beacon" and (_beacon["ms"] is None
                                              or time.ticks_diff(now, _beacon["ms"]) > BEACON_STALE_MS):
            _core_clear()
        await asyncio.sleep(1)


async def run(cfg):
    global _cfg, _expire_task
    _cfg = cfg
    if _expire_task is None:          # survives a restart of run() by the supervisor
        _expire_task = asyncio.create_task(_expire())
    await _search()


async def scan_nearby():
    """For GET /api/scan: nearby HR, power and CORE sensors, plus the ones connected now
    (a connected sensor usually stops advertising)."""
    found = {}
    async with _radio:
        async with aioble.scan(UI_SCAN_MS, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                roles = _offers(list(result.services()))
                if roles and not ble_share.is_share(result.name()):
                    addr = result.device.addr_hex()
                    _hear(addr, result.rssi, result)
                    found[addr] = {"addr": addr, "name": result.name() or _names.get(addr, ""), "rssi": result.rssi,
                                   "types": roles, "connected": False}
    for role in ROLES:
        addr = _owner[role]
        if addr:
            d = found.setdefault(addr, {"addr": addr, "name": _names.get(addr, ""), "rssi": None,
                                        "types": [], "connected": True})
            d["connected"] = True
            if role not in d["types"]:
                d["types"].append(role)
    return sorted(found.values(), key=lambda d: -(d["rssi"] if d["rssi"] is not None else 0))
