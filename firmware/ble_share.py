"""Heart rate sharing (setting hr_share, off by default): the fan also acts as a Bluetooth heart-rate sensor.

An app or watch (Zwift, a bike computer ...) connects to "WattWind-XXXX HR" like to a strap and gets every
notification the strap sends, unchanged (heart rate, beat times), while the strap itself stays connected to the
fan only. Useful when a strap allows just one or two Bluetooth connections.

- One receiver at a time: the custom MicroPython allows 3 connections (strap + trainer + receiver). While one
  is connected, the fan doesn't advertise.
- Only fresh readings are sent: nothing while the strap is off the skin, missing or disconnected (the receiver
  then shows no heart rate, as with a strap taken off).
- Only a fan with its own sensors: a follower has Bluetooth off (main.py share_task).
- Other fans never take a share as their strap (ble_sensors skips names is_share() recognises).
This task never touches relays.
"""

import asyncio
import bluetooth

import aioble
import state

HR_SVC = bluetooth.UUID(0x180D)
HR_CHR = bluetooth.UUID(0x2A37)       # Heart Rate Measurement (notify)
LOC_CHR = bluetooth.UUID(0x2A38)      # Body Sensor Location (read): 1 = chest
APPEARANCE = 0x0341                   # Heart Rate Sensor: Heart Rate Belt (Bluetooth Assigned Numbers 2.6)
ADV_INTERVAL_US = 250000
ADV_RECHECK_MS = 5000                 # advertising restarts this often, so a changed setting is seen
SUFFIX = " HR"
STOP_PASSES = 5                       # sharing off: stop advertising this many times, 1 s apart

_hr_ch = None                         # the registered Heart Rate Measurement characteristic
_conn = None                          # the connected receiver, or None
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


def send(data):
    """From ble_sensors.on_hr: a fresh strap notification, passed on unchanged if a receiver is connected."""
    if _hr_ch is None or _conn is None or not enabled(_cfg):
        return
    try:
        _hr_ch.write(bytes(data), send_update=True)    # notifies the receiver if it subscribed
        state.share_sent += 1
    except Exception as e:                             # a lost receiver must never stop the strap's data
        print("share: send failed", repr(e))


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


async def run(cfg):
    global _conn, _cfg
    _cfg = cfg
    stop_passes = 0
    while True:
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
        state.share = "waiting"
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
        addr = conn.device.addr_hex()
        _conn = conn
        state.share = "connected"
        state.share_sent = 0
        log("receiver connected", addr)
        try:
            while conn.is_connected() and enabled(cfg):
                await asyncio.sleep(1)
            if conn.is_connected():                    # switched off on the page
                await conn.disconnect()
        finally:
            _conn = None
            state.share = "off" if not enabled(cfg) else "waiting"
            log("receiver disconnected", addr, "({} readings sent)".format(state.share_sent))
