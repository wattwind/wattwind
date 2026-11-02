"""Wi-Fi: client mode with the saved network, otherwise a WPA2 access point WattWind-XXXX.

Boot: if an SSID is saved, try it for 20 s. Connected: keep the connection; if it drops, retry
for 2 minutes, then give up on the router. Not connected (or no SSID, or gave up): start the
access point, UI at 192.168.4.1. With an SSID saved, the access point keeps trying the home
network (first after 2 min, a router needs that long after a power cut, then every 5 min) and
switches back when it joins, unless the page is open over the access point (setup in progress).
Setup from the access point: the page asks for a test join (state.wifi_test_request); the station
joins while the access point stays up, and the result with the new IP goes to state.wifi_test,
so the page can show the new address before the fan switches over.
Fan control never waits for Wi-Fi: everything here yields to the other tasks.
"""

import asyncio
import binascii
import time
import network

import state

CONNECT_TIMEOUT_S = 20
RETRY_JOIN_MS = 3000         # repeat a failed join attempt this often within the timeout
CHECK_S = 2                 # how often a client connection is checked
RETRY_S = 5                  # pause between join attempts after a drop
FALLBACK_AP_S = 120          # router still gone after this long: switch to the access point
HOME_RETRY_FIRST_S = 120     # in access point mode, first try of the saved home network after this
HOME_RETRY_S = 300           # ... then this often
PAGE_IN_USE_S = 120          # page polled within this long: someone uses the access point, don't switch
DEFAULT_AP_PASSWORD = "wattwind"   # used if the saved one is not 8-63 chars: never an open AP
POWER_SAVE_OFF = 0xA11140    # cyw43 "performance" mode: quicker web responses


def log(*args):
    """Wi-Fi events: to USB serial and to the logbook (events only, a few per hour at most)."""
    print("[{}] wifi:".format(state.uptime_s), *args)
    try:
        import logbook
        logbook.write("up={} wifi: {}".format(state.uptime_s, " ".join(str(a) for a in args)))
    except Exception:
        pass


async def run(cfg):
    network.hostname(cfg["hostname"])        # before the interface is activated
    ssid, password = cfg["wifi_ssid"], cfg["wifi_password"]
    sta = network.WLAN(network.STA_IF)
    if ssid:
        sta.active(True)
        sta.config(pm=POWER_SAVE_OFF)
        state.wifi_mode = "connecting"
        state.wifi_ssid = ssid
        log("connecting to", ssid)
        if not await _connect(sta, ssid, password, CONNECT_TIMEOUT_S):
            log("could not connect to", ssid, "(status {})".format(sta.status()))
            sta.disconnect()
            sta.active(False)
    while True:
        if sta.isconnected():
            await _stay_connected(sta, ssid, password)   # returns only on giving up
            log("router gone for", FALLBACK_AP_S, "s, switching to the access point")
            sta.disconnect()
            sta.active(False)
        await _access_point(cfg)                         # returns when the home network is back


async def _connect(sta, ssid, password, timeout_s):
    """Join for client mode: on success, publish mode and IP in state."""
    t0 = state.uptime_s
    if await _join(sta, ssid, password, timeout_s) != "ok":
        return False
    state.wifi_mode = "sta"
    state.ip = sta.ifconfig()[0]
    log("connected to", ssid, "after", state.uptime_s - t0, "s, IP", state.ip, "signal", _rssi(sta), "dBm",
        "-> http://{}.local or http://{}".format(network.hostname(), state.ip))
    return True


async def _join(sta, ssid, password, timeout_s):
    """Join within timeout_s; returns "ok", "wrong password" or "not found". A weak network is
    often missed by one join attempt ("no AP found"), so a failed attempt is repeated every
    RETRY_JOIN_MS. Changes no state."""
    sta.connect(ssid, password)
    attempts = 1
    since_attempt = 0
    for _ in range(timeout_s * 4):
        await asyncio.sleep_ms(250)
        since_attempt += 250
        if sta.isconnected():
            return "ok"
        status = sta.status()
        if status == network.STAT_WRONG_PASSWORD:
            log("wrong password for", ssid)
            return "wrong password"
        if status in (network.STAT_NO_AP_FOUND, network.STAT_CONNECT_FAIL) \
                and since_attempt >= RETRY_JOIN_MS:
            attempts += 1
            since_attempt = 0
            sta.disconnect()
            sta.connect(ssid, password)
    log("gave up on", ssid, "after", attempts, "attempts")
    return "not found"


def scan_raw():
    """Nearby networks as WLAN.scan() tuples (ssid, bssid, channel, rssi, security, hidden). Blocks
    ~2-3 s. Works on the home network and from the access point (the station is switched on briefly)."""
    sta = network.WLAN(network.STA_IF)
    was_on = sta.active()
    if not was_on:
        sta.active(True)
    try:
        return sta.scan()
    finally:
        if not was_on:
            sta.active(False)


def _rssi(sta):
    try:
        return sta.status("rssi")
    except Exception:
        return "?"


async def _stay_connected(sta, ssid, password):
    """Watch the connection. After a drop, rejoin for up to FALLBACK_AP_S; returns if that fails
    (the caller then starts the access point, so the page stays reachable)."""
    n = 0
    while True:
        await asyncio.sleep(CHECK_S)
        if sta.isconnected():
            n += 1
            if n % 15 == 1:              # signal for the page, about every 30 s
                rssi = _rssi(sta)
                state.rssi = rssi if isinstance(rssi, int) else None
            continue
        state.rssi = None
        state.wifi_mode = "connecting"
        state.ip = ""
        log("connection lost, retrying for", FALLBACK_AP_S, "s, then access point")
        lost = time.ticks_ms()
        while True:
            left_s = FALLBACK_AP_S - time.ticks_diff(time.ticks_ms(), lost) // 1000
            if left_s <= 0:
                return
            sta.disconnect()
            if await _connect(sta, ssid, password, min(CONNECT_TIMEOUT_S, left_s)):
                break
            await asyncio.sleep(RETRY_S)


async def _access_point(cfg):
    ap = network.WLAN(network.AP_IF)
    password = cfg["ap_password"]
    if not 8 <= len(password) <= 63:
        log("ap_password must be 8-63 characters, using the default")
        password = DEFAULT_AP_PASSWORD
    name = "WattWind-" + binascii.hexlify(ap.config("mac")[-2:]).decode().upper()
    ap.config(essid=name, password=password)   # a password means WPA2
    ap.active(True)
    while not ap.active():
        await asyncio.sleep_ms(100)
    state.wifi_mode = "ap"
    state.rssi = None
    state.wifi_ssid = name
    state.ip = ap.ifconfig()[0]
    log("access point", name, "-> http://{}".format(state.ip))
    portal = asyncio.create_task(_captive_dns(state.ip))
    try:
        await _ap_loop(ap, cfg)
    finally:
        portal.cancel()


async def _captive_dns(ip):
    """Every name resolves to the fan while the access point is up: phones open the page by themselves."""
    try:
        import dns
        await dns.serve(ip, log)
    except asyncio.CancelledError:
        raise
    except Exception as e:                   # no portal is no reason to stop the access point
        log("captive DNS stopped:", repr(e))


async def _ap_loop(ap, cfg):
    home = cfg["wifi_ssid"]
    next_try = state.uptime_s + HOME_RETRY_FIRST_S
    while True:
        await asyncio.sleep(1)
        if state.wifi_test_request:
            ssid, password = state.wifi_test_request
            state.wifi_test_request = None
            await _test_join(ssid, password)
        elif home and state.uptime_s >= next_try:
            next_try = state.uptime_s + HOME_RETRY_S
            if state.uptime_s - state.page_seen_s < PAGE_IN_USE_S:
                continue                     # someone is on the page over the access point
            if await _rejoin_home(ap, home, cfg["wifi_password"]):
                return


async def _rejoin_home(ap, ssid, password):
    """From the access point: try the saved home network; on success turn the access point off."""
    log("trying", ssid, "again (access point stays on)")
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    sta.config(pm=POWER_SAVE_OFF)
    if await _join(sta, ssid, password, CONNECT_TIMEOUT_S) != "ok":
        sta.disconnect()
        sta.active(False)
        return False
    ap.active(False)
    state.wifi_mode = "sta"
    state.wifi_ssid = ssid
    state.ip = sta.ifconfig()[0]
    log("back on", ssid, "IP", state.ip, "-> http://{}.local".format(network.hostname()))
    return True


async def _test_join(ssid, password):
    """Join `ssid` with the access point still up, report the IP the router gives, disconnect.
    The router usually gives the same IP again after the reboot that follows."""
    log("testing", ssid, "(access point stays on)")
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    sta.config(pm=POWER_SAVE_OFF)
    result = await _join(sta, ssid, password, CONNECT_TIMEOUT_S)
    if result == "ok":
        ip = sta.ifconfig()[0]
        log("test OK:", ssid, "IP", ip, "signal", _rssi(sta), "dBm")
        state.wifi_test = {"state": "ok", "ssid": ssid, "ip": ip, "error": ""}
    else:
        state.wifi_test = {"state": "failed", "ssid": ssid, "ip": "", "error": result}
    sta.disconnect()
    sta.active(False)
