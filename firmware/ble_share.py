"""Heart rate sharing (setting hr_share, off by default): the fan also acts as a Bluetooth heart-rate sensor.

An app or watch (Zwift, a bike computer ...) connects to "WattWind-XXXX HR" like to a strap and gets every
notification the strap sends, unchanged (heart rate, beat times), while the strap itself stays connected to the
fan only. Useful when a strap allows just one or two Bluetooth connections.

- ONE receiver at a time (MAX_RECEIVERS; user's decision 2026-11-07, option A: up to 4 sensors + 1 receiver).
  Measured: 2-3 receivers can connect, but while 2 or more are
  connected the radio (CYW43439) refuses every new outgoing connection (HCI 0x09), so a strap or trainer that drops
  can't come back, and repeated refusals leave the stack stuck until a restart. The 1.1 MicroPython file also keeps
  BTstack at one incoming connection (btstack-pairing.patch). The code below handles N receivers; N is 1.
- Each reading is sent to each receiver on its own (notify per connection): MicroPython's write(send_update=True)
  would notify EVERY link, the strap and trainer included, and stop at the first failing one.
- Only fresh readings are sent: nothing while the strap is off the skin, missing or disconnected (the receiver
  then shows no heart rate, as with a strap taken off).
- Only a fan with its own sensors: a follower has Bluetooth off (main.py share_task).
- Other fans never take a share as their strap (ble_sensors skips names is_share() recognises).
- Pairing (only on the pairing MicroPython build, ble_bonds.supported()): receivers that insist on pairing
  (Garmin Edge) pair with "Just Works" (no code: the fan has no screen) and are remembered in ble_bonds.json,
  so they reconnect after a restart. Always allowed: pairing only adds encryption, and anyone nearby can use
  the share without it anyway (an off switch was tried: a receiver paired before then reconnected every 10 s,
  measured 2026-11-03). On the stock build a pairing request is not answered and such receivers can't use it.
This task never touches relays.
"""

import asyncio
import struct
import bluetooth

import aioble
import ble_bonds
import state

ble_bonds.install()                   # before Bluetooth starts: BTstack reads the stored keys while starting

HR_SVC = bluetooth.UUID(0x180D)
HR_CHR = bluetooth.UUID(0x2A37)       # Heart Rate Measurement (notify)
LOC_CHR = bluetooth.UUID(0x2A38)      # Body Sensor Location (read): 1 = chest
APPEARANCE = 0x0341                   # Heart Rate Sensor: Heart Rate Belt (Bluetooth Assigned Numbers 2.6)
ADV_INTERVAL_US = 250000
ADV_RECHECK_MS = 5000                 # advertising restarts this often, so a changed setting is seen
SUFFIX = " HR"
STOP_PASSES = 5                       # sharing off: stop advertising this many times, 1 s apart
_IO_NO_INPUT_OUTPUT = 3               # pairing without a code ("Just Works"): the fan has no screen or keys

MAX_RECEIVERS = 1                     # see the module notes: more blocks sensor reconnects (measured)
SENSOR_LINKS = 2                      # the fan's own strap and trainer (+1 with a CORE sensor)

_hr_ch = None                         # the registered Heart Rate Measurement characteristic
_rx = {}                              # the connected receivers: conn_handle -> {"conn", "addr", "sent", "paired"}
_cfg = None


def log(*args):
    print("[{}] share:".format(state.uptime_s), *args)
    try:
        import logbook
        logbook.write("up={} hr share: {}".format(state.uptime_s, " ".join(str(a) for a in args)))
    except Exception:
        pass


def adv_name():
    """WattWind-XXXX HR: the fan's id (as its access point and in linked fans) + HR."""
    try:
        import link
        return link.my_id() + SUFFIX
    except Exception:
        return "WattWind" + SUFFIX


def is_share(name):
    """A fan's shared heart rate (any fan's): never taken as a strap."""
    return bool(name) and name.startswith("WattWind") and name.endswith(SUFFIX)


def enabled(cfg):
    return bool(cfg and cfg.get("hr_share")) and not cfg.get("follow_id")


def max_receivers(cfg=None):
    """How many receivers may connect: the MicroPython file's connections minus the fan's own sensors, capped at
    MAX_RECEIVERS (1). 0 on the older file (3 connections) with strap, trainer and a CORE: the page says so."""
    try:
        import mpbuild
        links = mpbuild.features()["connections"]
    except Exception:
        links = 3
    sensors = SENSOR_LINKS + (1 if (cfg or {}).get("core_addr") or state.core_connected else 0)
    return max(0, min(MAX_RECEIVERS, links - sensors))


def _update_state():
    n = len(_rx)
    state.share_receivers = n
    state.share_secure = "paired" if any(r["paired"] for r in _rx.values()) else ""
    if state.share != "off":
        state.share = "connected" if n else "waiting"


def pairing(cfg=None):
    """For the page: "on" (pairing MicroPython build) or "unsupported" (stock build)."""
    return "on" if ble_bonds.supported() else "unsupported"


def _apply_pairing(cfg):
    """Pairing build only: allow pairing (and keeping the keys), and say what the fan is (GAP Appearance, which
    Garmin reads to decide the sensor type). Repeated before each advertising round (cheap; Bluetooth may have
    been restarted)."""
    if not ble_bonds.supported():
        return
    ble = aioble.core.ble
    try:
        ble.config(bond=True, mitm=False, io=_IO_NO_INPUT_OUTPUT, le_secure=False)
        ble.gatts_write(ble_bonds.GAP_APPEARANCE_HANDLE, struct.pack("<H", APPEARANCE))
    except Exception as e:
        print("share: pairing setup failed", repr(e))


def _on_encryption(conn_handle, encrypted, bonded):
    """From the Bluetooth stack (ble_bonds.irq): note it for the task, which writes the logbook."""
    # A fresh pairing and a reconnect of a paired device both end "encrypted and bonded".
    r = _rx.get(conn_handle)
    if r is not None and encrypted and bonded:
        r["paired"] = True
        state.share_secure = "paired"


ble_bonds.on_encryption = _on_encryption


def send(data):
    """From ble_sensors.on_hr: a fresh strap notification, passed on unchanged to every connected receiver."""
    if _hr_ch is None or not _rx or not enabled(_cfg):
        return
    data = bytes(data)
    try:
        _hr_ch.write(data)                              # the value a receiver reads; no notify to every link
    except Exception as e:
        print("share: write failed", repr(e))
    for r in list(_rx.values()):
        try:
            _hr_ch.notify(r["conn"], data)              # this receiver only
            r["sent"] += 1
            state.share_sent += 1
        except Exception as e:                          # a lost receiver must never stop the others or the strap
            print("share: send failed", r["addr"], repr(e))


def _register():
    global _hr_ch
    if _hr_ch is not None:
        return
    svc = aioble.Service(HR_SVC)
    _hr_ch = aioble.Characteristic(svc, HR_CHR, notify=True)
    aioble.Characteristic(svc, LOC_CHR, read=True, initial=b"\x01")
    aioble.register_services(svc)


def _stop_advertising():
    try:
        aioble.core.ble.gap_advertise(None)
    except Exception as e:
        print("share: stop advertising failed", repr(e))


async def _serve(conn, cfg):
    """One receiver: logs it, notes pairing, disconnects it when sharing is switched off."""
    handle = conn._conn_handle
    addr = conn.device.addr_hex()
    r = {"conn": conn, "addr": addr, "sent": 0, "paired": False}
    _rx[handle] = r
    _update_state()
    log("receiver connected", addr, "({} of {})".format(len(_rx), max_receivers(cfg)))
    noted = False
    try:
        while conn.is_connected() and enabled(cfg) and state.uptime_s >= state.update_until_s:
            if r["paired"] and not noted:
                noted = True
                state.share_bonds = ble_bonds.count()
                log("receiver paired, connection encrypted", addr,
                    "({} paired device(s) kept)".format(state.share_bonds))
            await asyncio.sleep(1)
        if conn.is_connected():                         # switched off on the page, or an update is coming in
            await conn.disconnect()
    except Exception as e:
        print("share: receiver", addr, repr(e))
    finally:
        _rx.pop(handle, None)
        _update_state()
        log("receiver disconnected", addr, "({} readings sent)".format(r["sent"]))


async def run(cfg):
    global _cfg
    _cfg = cfg
    stop_passes = 0
    while True:
        state.share_pairing = pairing(cfg)
        state.share_bonds = ble_bonds.count() if state.share_pairing != "unsupported" else 0
        state.share_limit = max_receivers(cfg)
        if not enabled(cfg) or state.uptime_s < state.update_until_s:   # off, or a firmware update is coming in
            state.share = "off"
            # BTstack switches advertising back on by itself when a connection ends (measured: the fan stayed
            # visible after sharing was switched off). Stop it, and again for a few seconds after the last session.
            if stop_passes:
                _stop_advertising()
                stop_passes -= 1
            await asyncio.sleep(1)
            continue
        stop_passes = STOP_PASSES
        _register()
        _apply_pairing(cfg)
        state.share = "connected" if _rx else "waiting"
        if len(_rx) >= state.share_limit:               # full: no advertising until one leaves
            await asyncio.sleep(1)
            continue
        if not state.share_name:
            state.share_name = adv_name()
            try:        # the name an app reads after connecting (GAP Device Name 0x2A00); else "MPY BTSTACK"
                aioble.config(gap_name=state.share_name)
            except Exception as e:
                print("share: gap_name not set", repr(e))
        try:
            conn = await aioble.advertise(ADV_INTERVAL_US, name=state.share_name, services=[HR_SVC],
                                          appearance=APPEARANCE, timeout_ms=ADV_RECHECK_MS)
        except asyncio.TimeoutError:
            continue
        asyncio.create_task(_serve(conn, cfg))
        await asyncio.sleep_ms(200)                     # let _serve register it before counting again
