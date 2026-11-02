"""Web UI and JSON API (Microdot).

Never touches relays: it only writes mode / level into state, and the control task in
main.py applies them. New Wi-Fi settings and the reboot button set state.reboot_requested; main.py reboots.
Runs under CPython too (tests/test_web.py).
"""

import gc
import os

import state
import config
import version
import profiles
import link
import logbook
import detail
import asyncio
import microdot as _md
from microdot import Microdot, Response, Request
from checks import (NUMBERS, THRESHOLDS, HOSTNAME_CHARS, SENSOR_ADDRS, RESPONSES, USES, HEX, BACKUP_KEYS,  # noqa
                    CHECKED, is_ble_addr, restore_settings, check_settings, _is_int, _is_number)

INDEX = "www/index.html"
HELP = "www/help.html"
ICON = "www/icon.png"
PORT = 80

CAPTIVE_CHECKS = ("/generate_204", "/gen_204",                     # Android, ChromeOS
                  "/hotspot-detect.html", "/library/test/success.html",   # iPhone, Mac
                  "/connecttest.txt", "/ncsi.txt", "/redirect",     # Windows
                  "/canonical.html", "/success.txt")                # Firefox
RESET_GROUPS = {               # POST /api/reset: what goes back to the defaults (network and PIN never)
    "rider": ("ftp", "hr_max", "hr_rest", "use", "response", "up_thresholds", "down_thresholds"),
    "fan": ("dwell_up_s", "dwell_down_s", "manual_timeout_min", "idle_off_min", "max_level"),
}
SECRETS = ("wifi_password", "ap_password", "settings_pin", "link_key", "follow_key")
UPDATE_IDLE_S = 60           # firmware update: no piece for this long = given up (the fan may run again)


# First setup (EN 303 645 5.1-1, 5.5-5): until the fan has its own access point password and a settings PIN, the
# routes that change settings answer 409 and the page shows the setup card. The fan buttons, status, restore,
# reboot and erase stay open. REQUIRE_SETUP is switched off only in the older host tests.
REQUIRE_SETUP = True
PIN_MIN, PIN_MAX = 4, 16
SETUP_GATED = ("/api/config", "/api/wifi", "/api/update/start", "/api/link/pair", "/api/link/unpair", "/api/follow",
               "/api/reset", "/api/backup")
SAFE_BLOCKED = ("/api/config", "/api/wifi", "/api/profile", "/api/reset", "/api/restore", "/api/backup", "/api/setup",
                "/api/follow", "/api/link/pair", "/api/link/unpair", "/api/timer")
_cfg = {}                               # the settings create_app() serves (status() reports whether setup is needed)


def setup_needed(cfg):
    return REQUIRE_SETUP and (not cfg.get("settings_pin") or cfg.get("ap_password") == config.DEFAULTS["ap_password"])


def status():
    return {
        "setup": setup_needed(_cfg),
        "mode": state.mode, "level": state.level, "target": state.target_level,
        "auto_available": state.auto_available,
        "power": state.power, "cadence": state.cadence, "hr": state.hr,
        "hr_connected": state.hr_connected, "power_connected": state.power_connected,
        "hr_name": state.hr_name, "power_name": state.power_name,
        "p_ema": state.p_ema, "p_score": state.p_score, "hr_score": state.hr_score,
        "demand": state.demand, "basis": state.basis, "hr_off": state.hr_off, "hr_caps": state.hr_caps,
        "hr_share": state.share, "hr_share_name": state.share_name,
        "wifi": state.wifi_mode, "ssid": state.wifi_ssid, "ip": state.ip,
        "rider": state.rider,
        "uptime": state.uptime_s, "notice": state.notice, "manual_left_s": state.manual_left_s, "nudge": state.nudge,
        "off_left_s": None if state.off_at_s is None else max(0, state.off_at_s - state.uptime_s),
        "version": version.VERSION, "board": version.BOARD, "reset_reason": state.reset_reason, "files": state.files,
        "rssi": state.rssi, "hr_battery": state.hr_battery, "power_battery": state.power_battery,
        "box_temp": None if state.box_temp is None else round(state.box_temp),
        "mem_free": gc.mem_free() if hasattr(gc, "mem_free") else None,   # MicroPython only
        "link_id": state.link_id,
        "follow": None if state.follow is None else dict(state.follow, fresh=state.follow_fresh,
                                                         leader_level=state.leader_level,
                                                         unpaired=state.follow_unpaired),
        "pair_left_s": max(0, state.pair_until_s - state.uptime_s),
        "updating": state.uptime_s < state.update_until_s,
        "detail": detail.rec().status(),        # detailed recording: None, or on / time left / size
        "safe_start": state.safe_start,         # started with default ride settings after errors (main.py)
        "name": _cfg.get("hostname", ""),       # the fan's name, shown in the page's header (several fans)
    }




def _files(path, out, depth=0):
    for name in sorted(os.listdir(path)):
        p = (path.rstrip("/") + "/" + name) if path not in ("", "/") else name
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st[0] & 0x4000 and depth < 3:
            _files(p, out, depth + 1)
        else:
            out.append("  {:7d}  {}".format(st[6], p))


def logbook_stamp():
    """'2026-10-31 21:40Z' once the time came from the internet, else 'at up=1234'."""
    import time
    t = time.gmtime()
    if t[0] >= 2025:
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}Z".format(t[0], t[1], t[2], t[3], t[4])
    return "at up={}".format(state.uptime_s)


def diagnostics_text(cfg):
    """The diagnostics file, as a generator of text pieces (streamed, so the logbooks never sit in RAM)."""
    import json
    yield "WattWind diagnostics\n====================\n"
    yield "firmware {} (board {})\n\n".format(version.VERSION, version.BOARD)
    try:
        yield "status:\n" + json.dumps(status()) + "\n\n"
    except Exception as e:
        yield "status: failed {!r}\n\n".format(e)
    safe = {k: cfg[k] for k in BACKUP_KEYS if k in cfg and k not in SECRETS}
    safe["secrets set"] = [k for k in SECRETS if cfg.get(k)]
    yield "settings (passwords, PIN and keys left out):\n" + json.dumps(safe) + "\n\n"
    try:
        st = os.statvfs("/")
        yield "flash: {} KB total, {} KB free\n".format(st[0] * st[2] // 1024, st[0] * st[3] // 1024)
    except Exception:
        pass
    try:
        yield "RAM free: {} bytes\n".format(gc.mem_free())
    except Exception:
        pass
    try:
        yield "detailed recording: {} (download it separately: Settings -> Maintenance)\n".format(detail.rec().status())
    except Exception:
        pass
    try:
        import time
        now = time.ticks_ms()
        yield "task heartbeats (ms ago): {}\n".format(
            {k: time.ticks_diff(now, v) for k, v in state.heartbeats.items()})
    except Exception:
        pass
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        yield "wifi: mode {} station active {} connected {} status {} ifconfig {} rssi {}\n".format(
            state.wifi_mode, sta.active(), sta.isconnected(), sta.status(), sta.ifconfig(), state.rssi)
    except Exception:
        pass
    files = []
    try:
        _files("", files)
    except Exception:
        pass
    yield "\nfiles:\n" + "\n".join(files) + "\n"
    for title, path in (("previous logbook", "log.old.txt"), ("logbook", "log.txt")):
        yield "\n== {} ({}) ==\n".format(title, path)
        try:
            with open(path) as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    yield chunk
        except OSError:
            yield "(none)\n"


def set_follow(cfg, fid="", name="", key="", mode="same", offset=0):
    """Start / change / stop following (fid "" = own sensors again). Keeps config and state in step."""
    cfg.update({"follow_id": fid, "follow_name": name, "follow_key": key, "follow_mode": mode, "follow_offset": offset})
    state.follow = {"id": fid, "name": name, "mode": mode, "offset": offset} if fid else None
    state.follow_same = bool(fid) and mode == "same"
    if state.mode in ("auto", "follow"):
        state.set_auto()               # auto <-> follow with the new setting


def public_config(cfg):
    """Settings for the page: secrets left out, only whether a PIN is set."""
    out = {k: v for k, v in cfg.items() if k not in SECRETS}
    out["pin_set"] = bool(cfg["settings_pin"])
    out["ap_default"] = cfg["ap_password"] == config.DEFAULTS["ap_password"]   # the published default
    return out


def _own_secrets_error(data):
    """A new access point password or PIN from the page: never the published default, never no PIN. (A backup may
    still hold an empty PIN: then the setup card comes back after the restore.)"""
    if "ap_password" in data and data["ap_password"] == config.DEFAULTS["ap_password"]:
        return "Access point password: choose your own, not the default"
    if "settings_pin" in data:
        p = data["settings_pin"]
        if not isinstance(p, str) or not PIN_MIN <= len(p) <= PIN_MAX:
            return "Settings PIN: {} to {} characters (a PIN can be changed, not removed)".format(PIN_MIN, PIN_MAX)
    return None




def networks(found, limit=20):
    """WLAN.scan() tuples -> [{"ssid", "rssi", "secure"}], one entry per name (mesh systems repeat it)
    with its strongest signal, strongest first; hidden (nameless) networks left out."""
    best = {}
    for f in found:
        try:
            name = bytes(f[0]).decode("utf-8")
        except Exception:
            continue
        if not name or "\x00" in name:
            continue
        if name not in best or f[3] > best[name][0]:
            best[name] = (f[3], f[4] != 0)
    out = [{"ssid": n, "rssi": r, "secure": s} for n, (r, s) in best.items()]
    out.sort(key=lambda d: -d["rssi"])
    return out[:limit]


PIN_FREE_TRIES = 2           # wrong PINs before the wait starts; then 1, 2, 4 ... PIN_MAX_WAIT_S
PIN_MAX_WAIT_S = 60


def _pin_ok(cfg, data):
    """No PIN set, or the right one. Wrong PINs make the next try wait (slows guessing); no PIN given (the page
    asking whether one is needed) doesn't count."""
    pin = cfg["settings_pin"]
    if not pin:
        return True
    if state.uptime_s < state.pin_wait_until:
        return False
    given = data.get("pin")
    if given == pin:
        state.pin_fails = 0
        return True
    if given:
        state.pin_fails += 1
        if state.pin_fails > PIN_FREE_TRIES:
            state.pin_wait_until = state.uptime_s + min(2 ** (state.pin_fails - PIN_FREE_TRIES - 1), PIN_MAX_WAIT_S)
        n = state.pin_fails
        if n in (1, PIN_FREE_TRIES + 1) or n % 10 == 0:          # a few lines, even under a guessing attack
            logbook.event("security: wrong PIN ({} in a row)".format(n))
    return False


def _pin_error():
    left = state.pin_wait_until - state.uptime_s
    if left > 0:
        return {"error": "too many wrong PINs: try again in {} s".format(left)}
    return {"error": "wrong PIN"}


LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".localdomain", ".box", ".fritz.box")


def host_ok(host, names, ip, wifi_mode):
    """DNS rebinding guard: on the home network, answer only requests addressed to the fan itself (its name, with
    a usual local suffix, or its IP). In access-point mode any name (the captive portal redirects them)."""
    if wifi_mode == "ap" or not host:
        return True
    h = host.split(":")[0].strip().lower().rstrip(".")
    if h in ("localhost", "127.0.0.1", "192.168.4.1") or (ip and h == ip):
        return True
    for n in names:
        n = (n or "").lower()
        if n and (h == n or any(h == n + sfx for sfx in LOCAL_SUFFIXES)):
            return True
    return False


def _json_body(req):
    try:
        data = req.json
    except ValueError:
        data = None
    return data if isinstance(data, dict) else None


REQUEST_READ_S = 10          # a client must send its whole request within this, else the connection is closed
RESPONSE_WRITE_S = 120       # ... and take the answer within this (big downloads on weak Wi-Fi need time)


async def _drop(writer):
    try:
        await writer.aclose()
    except Exception:
        pass


class FanApp(Microdot):
    """Microdot with a time limit per connection. Found 2026-11-01: an iPhone that suspended the page (a download to
    OneDrive, cancelled) left connections with half-sent requests open; the Pico has only a few sockets, and with about
    five of them stuck nobody could open the page until the phone let go ("could not connect to the server"). Same as
    Microdot.handle_request otherwise."""

    async def handle_request(self, reader, writer):
        req = None
        try:
            req = await asyncio.wait_for(Request.create(self, reader, writer, writer.get_extra_info("peername")),
                                         REQUEST_READ_S)
        except asyncio.TimeoutError:
            await _drop(writer)              # never finished its request: free the socket
            return
        except OSError as exc:
            if exc.errno not in _md.MUTED_SOCKET_ERRORS:
                raise
        except Exception as exc:
            _md.print_exception(exc)
        res = await self.dispatch_request(req)
        try:
            if res != Response.already_handled:
                await asyncio.wait_for(res.write(writer), RESPONSE_WRITE_S)
            await writer.aclose()
        except asyncio.TimeoutError:
            await _drop(writer)              # the client stopped reading
        except OSError as exc:
            if exc.errno not in _md.MUTED_SOCKET_ERRORS:
                raise


def create_app(cfg, save=config.save, scan=None):
    """scan: async function returning nearby sensors (ble_sensors.scan_nearby), or None."""
    global _cfg
    _cfg = cfg
    app = FanApp()
    boot_name = cfg.get("hostname", "")         # the mDNS name in use until the next restart

    @app.before_request
    async def check_safe_start(req):
        """Safe start (main.py): the settings in memory are defaults, so nothing that saves settings may run."""
        if state.safe_start and req.method == "POST" and req.path in SAFE_BLOCKED:
            return {"error": "Safe start: settings can't be changed now. Install the latest firmware, or Restart to "
                             "use your saved settings again", "safe": True}, 409

    @app.before_request
    async def check_setup(req):
        if req.method != "POST" or not setup_needed(cfg):
            return None
        gated = req.path in SETUP_GATED
        if req.path == "/api/profile":
            body = req.json if isinstance(req.json, dict) else {}
            gated = body.get("action") != "select"
        if gated:
            return {"error": "first set your own access point password and a PIN", "setup": True}, 409

    @app.before_request
    async def check_host(req):
        host = req.headers.get("Host", "")
        if not host_ok(host, (boot_name, cfg.get("hostname", "")), state.ip, state.wifi_mode):
            state.host_refused += 1
            n = state.host_refused
            if n in (1, 10, 100) or n % 1000 == 0:
                logbook.event("security: refused a request addressed to {} ({} so far)".format(host[:40], n))
            return {"error": "not addressed to this fan"}, 421

    @app.get("/")
    async def index(req):
        return Response.send_file(INDEX, max_age=0)

    @app.get("/help")
    async def help_page(req):
        return Response.send_file(HELP, max_age=0)

    def _read_pin(req):
        """GETs that show private things (logbook, diagnostics) take the PIN from the X-Pin header."""
        if _pin_ok(cfg, {"pin": req.headers.get("X-Pin", "")}):
            return None
        if not req.headers.get("X-Pin") and state.uptime_s >= state.pin_wait_until:
            return {"error": "PIN needed"}, 403
        return _pin_error(), 403

    @app.get("/api/log")
    async def get_log(req):                 # the fan's logbook (logbook.py), streamed from flash
        err = _read_pin(req)
        if err:
            return err
        path = logbook.OLD if req.args.get("old") else logbook.PATH
        try:
            os.stat(path)
        except OSError:
            return "(empty)\n", 200, {"Content-Type": "text/plain; charset=utf-8"}
        return Response.send_file(path, content_type="text/plain; charset=utf-8", max_age=0)

    @app.get("/api/detail")
    async def get_detail(req):              # the detailed recording (detail.py), both files, oldest first, streamed
        err = _read_pin(req)
        if err:
            return err
        if not detail.rec().exists():
            return "(no recording)\n", 200, {"Content-Type": "text/plain; charset=utf-8"}
        return Response(detail.rec().chunks(), headers={"Content-Type": "text/plain; charset=utf-8"})

    @app.post("/api/detail")
    async def post_detail(req):
        """{"action": "start" / "stop" / "delete"}: the detailed recording. Settings PIN."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        r, action = detail.rec(), data.get("action")
        if action == "start":
            try:
                import updater
                free = updater.free_bytes() + r.size()      # the old recording's space comes back
            except Exception:
                free = detail.MAX_BYTES * detail.SPACE_SHARE
            r.start(state.uptime_s, logbook_stamp(), free)
            logbook.event("detailed recording started (24 h)")
        elif action == "stop":
            r.stop(state.uptime_s)
            logbook.event("detailed recording stopped from the page")
        elif action == "delete":
            r.delete()
            logbook.event("detailed recording deleted from the page")
        else:
            return {"error": "action: start, stop or delete"}, 400
        return status()

    @app.get("/apple-touch-icon.png")
    async def icon(req):                    # home-screen icon (also asked for by iPhones by itself)
        return Response.send_file(ICON, content_type="image/png", max_age=86400)

    # Captive portal: on the fan's own network every name points here (dns.py). Phones and laptops check
    # these addresses when they join a network; a redirect makes them open the fan's page by themselves.
    def to_page(req):
        return Response.redirect("http://{}/".format(state.ip or "192.168.4.1"))

    for path in CAPTIVE_CHECKS:
        app.route(path)(to_page)

    @app.errorhandler(404)
    async def not_found(req):
        if state.wifi_mode == "ap":          # any other unknown address on the access point: the page
            return to_page(req)
        return {"error": "not found"}, 404

    @app.get("/api/status")
    async def get_status(req):
        state.page_seen_s = state.uptime_s     # the page is open: the Wi-Fi task won't switch networks now
        return status()

    @app.post("/api/mode")
    async def post_mode(req):
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if cfg.get("pin_for_control") and not _pin_ok(cfg, data):
            return {"error": "PIN needed for the fan buttons"}, 403
        mode = data.get("mode")
        if mode == "auto":
            if not state.auto_available:
                return {"error": "auto mode is not available yet"}, 409
            nudge = data.get("nudge", state.nudge if state.mode == "auto" else 0)
            if not _is_int(nudge) or not -2 <= nudge <= 2:
                return {"error": "nudge must be -2 to 2"}, 400
            state.set_auto()
            state.nudge = nudge
        elif mode == "manual":
            level = data.get("level")
            if not _is_int(level) or not 0 <= level <= 3:
                return {"error": "level must be 0-3"}, 400
            state.set_manual(level)
        elif mode == "follow" and state.follow_same:
            state.set_auto()           # a same-level follower's default mode
        else:
            return {"error": "mode must be auto or manual"}, 400
        what = {"auto": "Auto", "follow": "Follow"}.get(mode) or "level {}".format(data.get("level"))
        if mode == "auto" and state.nudge:
            what += " nudge {:+d}".format(state.nudge)
        logbook.event("button: " + what)
        state.notice = ""               # any action on the page counts as having seen the message
        return status()

    @app.get("/api/link")
    async def get_link(req):
        """Linked fans: this fan's id, the leaders heard on the network, what it follows."""
        return {"id": state.link_id, "name": cfg.get("hostname", ""), "heard": state.leaders_heard,
                "follow": status()["follow"], "pair_left_s": max(0, state.pair_until_s - state.uptime_s)}

    @app.post("/api/link/pair")
    async def post_pair(req):
        """Leader: open the pairing window (link.PAIR_S); a follower then fetches the key."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        if cfg.get("follow_id"):
            return {"error": "this fan follows another fan: it can't lead"}, 409
        state.pair_until_s = state.uptime_s + link.PAIR_S
        logbook.event("linked fans: pairing opened for {} s".format(link.PAIR_S))
        return {"pair_left_s": link.PAIR_S}

    @app.post("/api/link/unpair")
    async def post_unpair(req):
        """Leader: a new link key, so every fan following this one stops (they offer "Pair again")."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        if cfg.get("follow_id"):
            return {"error": "this fan follows another fan: it has no followers"}, 409
        cfg["link_key"] = link.new_key()
        save(cfg)
        logbook.event("linked fans: all followers unpaired (new key)")
        state.pair_until_s = 0
        return {"ok": True}

    @app.get("/api/link/key")
    async def get_link_key(req):
        """Asked by a follower while pairing is open on this (leader) fan."""
        if state.uptime_s >= state.pair_until_s or not cfg.get("link_key"):
            return {"error": "pairing is not open: press Pair a new fan on this fan first"}, 403
        return {"id": state.link_id, "name": cfg.get("hostname", ""), "key": cfg["link_key"]}

    @app.post("/api/follow")
    async def post_follow(req):
        """{"id": leader id, "mode": "same"/"own", "offset": 1/0/-1/-2}: follow (fetches the key from the leader
        the first time; then restarts without Bluetooth). {"id": ""}: own sensors again (restarts).
        {"id": the leader followed now, "pair": true}: fetch its key again (after it unpaired), no restart."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        fid = data.get("id", "")
        mode = data.get("mode", cfg.get("follow_mode", "same"))
        offset = data.get("offset", cfg.get("follow_offset", 0))
        if mode not in link.MODES:
            return {"error": "mode: same or own"}, 400
        if not _is_int(offset) or offset not in link.OFFSETS:
            return {"error": "offset: 1, 0, -1 or -2"}, 400
        if not isinstance(fid, str):
            return {"error": "id: a fan id"}, 400
        if fid == "":
            if cfg.get("follow_id"):
                set_follow(cfg)
                save(cfg)
                state.reboot_requested = True        # Bluetooth back on
            return {"reboot": True}
        again = fid == cfg.get("follow_id") and data.get("pair") is True
        if fid == cfg.get("follow_id") and not again:   # same leader: change how it follows, no restart
            set_follow(cfg, fid, cfg.get("follow_name", ""), cfg.get("follow_key", ""), mode, offset)
            save(cfg)
            return status()
        if fid == state.link_id:
            return {"error": "a fan can't follow itself"}, 400
        lead = [h for h in state.leaders_heard if h["id"] == fid]
        if not lead:
            return {"error": "that fan isn't heard on the network"}, 404
        try:
            code, got = await link.fetch_key(lead[0]["ip"])
        except Exception:
            return {"error": "can't reach {} ({})".format(lead[0]["name"] or fid, lead[0]["ip"])}, 502
        if code != 200 or not got.get("key") or got.get("id") != fid:
            return {"error": "pairing is not open on {}: press Pair a new fan there first".format(lead[0]["name"] or fid)}, 409
        set_follow(cfg, fid, got.get("name", "") or fid, got["key"], mode, offset)
        save(cfg)
        if again:                                    # already without Bluetooth: the new key works at once
            return status()
        state.reboot_requested = True                # restart without Bluetooth
        return {"reboot": True, "following": got.get("name", "") or fid}

    @app.post("/api/profile")
    async def post_profile(req):
        """Riders: {"action": "select", "index": i} (like a fan button), or "add" {"name"},
        "rename" {"index", "name"}, "delete" {"index"} (settings: need the settings PIN)."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        action, i = data.get("action"), data.get("index")
        ps = cfg["profiles"]
        if action == "select":
            if cfg.get("pin_for_control") and not _pin_ok(cfg, data):
                return {"error": "PIN needed for the fan buttons"}, 403
        elif not _pin_ok(cfg, data):
            return _pin_error(), 403
        if action in ("select", "rename", "delete") and (not _is_int(i) or not 0 <= i < len(ps)):
            return {"error": "no such rider"}, 400
        try:
            if action == "select":
                profiles.activate(cfg, i)
                state.rider_by_hand = True      # the strap rule won't switch away from a rider picked by hand
            elif action == "add":
                profiles.add(cfg, data.get("name"), config.DEFAULTS)
            elif action == "rename":
                profiles.rename(cfg, i, data.get("name"))
            elif action == "delete":
                profiles.delete(cfg, i)
            else:
                return {"error": "action: select, add, rename or delete"}, 400
        except ValueError as e:
            return {"error": str(e)}, 400
        save(cfg)
        state.rider = profiles.name(cfg) if len(cfg["profiles"]) > 1 else ""
        logbook.event("rider {}: now {}".format(action, profiles.name(cfg)))
        return public_config(cfg)

    @app.post("/api/reset")
    async def post_reset(req):
        """{"what": "rider"}: the selected rider's values (name and strap stay); {"what": "fan"}: the
        shared timing settings. Network settings and the PIN are never reset here."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        keys = RESET_GROUPS.get(data.get("what"))
        if not keys:
            return {"error": "what: rider or fan"}, 400
        for k in keys:
            v = config.DEFAULTS[k]
            cfg[k] = list(v) if isinstance(v, list) else v
        profiles.sync(cfg)
        save(cfg)
        logbook.event("settings: {} values back to the defaults".format(data.get("what")))
        state.notice = ""
        return public_config(cfg)

    @app.post("/api/timer")
    async def post_timer(req):                # manual "off in N minutes"; 0 cancels
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if cfg.get("pin_for_control") and not _pin_ok(cfg, data):
            return {"error": "PIN needed for the fan buttons"}, 403
        minutes = data.get("minutes")
        if not _is_int(minutes) or not 0 <= minutes <= 1440:
            return {"error": "minutes must be 0 to 1440"}, 400
        if minutes and (state.mode != "manual" or state.manual_level == 0):
            return {"error": "the timer is for a level picked by hand (1, 2 or 3)"}, 409
        state.off_at_s = state.uptime_s + minutes * 60 if minutes else None
        return status()

    @app.post("/api/notice/dismiss")
    async def dismiss_notice(req):
        state.notice = ""
        return status()

    @app.get("/api/config")
    async def get_config(req):
        return public_config(cfg)

    @app.post("/api/config")
    async def post_config(req):
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        err = _own_secrets_error(data)
        if err:
            return {"error": err}, 400
        try:
            changed = check_settings(cfg, data)
        except ValueError as e:
            return {"error": str(e)}, 400
        if changed:                     # write the flash only when something changed
            cfg.update(changed)
            profiles.sync(cfg)          # the active rider's FTP, HR range, response, strap
            save(cfg)
            logbook.event("settings saved: " + ", ".join(sorted(changed)))
        state.notice = ""               # any action on the page counts as having seen the message
        out = public_config(cfg)
        out["changed"] = sorted(changed)
        return out

    @app.get("/api/scan")
    async def get_scan(req):
        if scan is None:
            return {"error": "Bluetooth is not running"}, 503
        return {"devices": await scan()}

    def wifi_body(req):
        """(ssid, password, None) or (None, None, error response)."""
        data = _json_body(req)
        if data is None:
            return None, None, ({"error": "JSON body expected"}, 400)
        if not _pin_ok(cfg, data):
            return None, None, (_pin_error(), 403)
        ssid = data.get("ssid")
        password = data.get("password", "")
        if not isinstance(ssid, str) or len(ssid) > 32:
            return None, None, ({"error": "network name: up to 32 characters ('' = access point only)"}, 400)
        if not isinstance(password, str) or not (password == "" or 8 <= len(password) <= 63):
            return None, None, ({"error": "password: 8-63 characters, or empty for an open network"}, 400)
        return ssid, password, None

    @app.post("/api/wifi/test")
    async def post_wifi_test(req):
        """From the access point only: join the network while the AP stays up, to learn the IP
        the router gives before switching. Poll GET /api/wifi/test for the result."""
        ssid, password, err = wifi_body(req)
        if err:
            return err
        if not ssid:
            return {"error": "network name needed"}, 400
        if state.wifi_mode != "ap":
            return {"error": "only possible from the fan's own network"}, 409
        if state.wifi_test["state"] == "testing":
            return {"error": "a test is already running"}, 409
        state.wifi_test = {"state": "testing", "ssid": ssid, "ip": "", "error": ""}
        state.wifi_test_request = (ssid, password)
        return state.wifi_test

    @app.get("/api/wifi/scan")
    async def wifi_scan(req):               # nearby Wi-Fi networks for choosing the home network
        if state.wifi_mode == "connecting" or state.wifi_test["state"] == "testing":
            return {"error": "Wi-Fi is busy joining a network, try again in a few seconds"}, 409
        import wifi
        try:
            found = wifi.scan_raw()
        except Exception as e:
            return {"error": "scan failed: {}".format(e)}, 500
        return {"networks": networks(found)}

    @app.get("/api/wifi/test")
    async def get_wifi_test(req):
        return state.wifi_test

    @app.post("/api/wifi")
    async def post_wifi(req):
        ssid, password, err = wifi_body(req)
        if err:
            return err
        cfg["wifi_ssid"] = ssid
        cfg["wifi_password"] = password
        save(cfg)
        state.reboot_requested = True
        return {"ok": True, "reboot": True}

    @app.post("/api/update/start")
    async def update_start(req):
        """Firmware update from the page (updater.py): {"manifest_text": manifest.json as in the update file,
        "sig": manifest.sig (hex), "sizes": {name: bytes}, "pin"};
        "full": true sends every file. Answers which files to send (the ones that differ from the installed ones)."""
        import updater
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        installed = None                    # the installed files' list, if the start-up check found them all ok
        if not data.get("full") and state.files == "ok":
            try:
                import json
                with open("manifest.json") as f:
                    installed = json.load(f).get("files")
            except (OSError, ValueError):
                installed = None
        try:
            manifest, signed_sha = updater.verified_manifest(data.get("manifest_text"), data.get("sig"))
            info = updater.start(manifest, data.get("sizes"), installed=installed, signed_sha=signed_sha)
        except (updater.UpdateError, OSError) as e:
            logbook.event("firmware update refused: {}".format(e))
            return {"error": str(e)}, 400
        logbook.event("firmware update to {} started: {} files".format(info.get("version"), len(info.get("send", ()))))
        state.update_until_s = state.uptime_s + UPDATE_IDLE_S      # fan off while the files come in
        info["current"] = version.VERSION
        return info

    @app.post("/api/update/file")
    async def update_file(req):
        """One piece of one file: raw bytes, ?path=...&offset=...; the PIN in the X-Pin header."""
        import updater
        if not _pin_ok(cfg, {"pin": req.headers.get("X-Pin", "")}):
            return _pin_error(), 403
        try:
            offset = int(req.args.get("offset", ""))
            got = updater.write(req.args.get("path", ""), offset, req.body or b"")
        except ValueError:
            return {"error": "offset: a number"}, 400
        except (updater.UpdateError, OSError) as e:
            return {"error": str(e)}, 400
        state.update_until_s = state.uptime_s + UPDATE_IDLE_S
        return {"got": got}

    @app.post("/api/update/finish")
    async def update_finish(req):
        """Check the staged files; if all are right, restart: the next start puts them in place."""
        import updater
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        try:
            new = await updater.finish()
        except (updater.UpdateError, OSError, ValueError) as e:
            state.update_until_s = 0
            logbook.event("firmware update failed, nothing changed: {}".format(e))
            return {"error": str(e)}, 400
        state.reboot_reason = "firmware update {} -> {}".format(version.VERSION, new)
        state.reboot_requested = True
        return {"ok": True, "version": new, "reboot": True}

    @app.post("/api/backup")
    async def post_backup(req):
        """The settings as a backup file: {"pin", "secrets": true/false}. Secrets (Wi-Fi password, PIN, access point
        password, link keys) only when asked for."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        with_secrets = data.get("secrets") is True
        keep = [k for k in BACKUP_KEYS if k in cfg and (with_secrets or k not in SECRETS)]
        return {"wattwind_backup": 1, "version": version.VERSION, "secrets": with_secrets,
                "config": {k: cfg[k] for k in keep}}

    @app.post("/api/restore")
    async def post_restore(req):
        """{"pin", "backup": <the file>}: checks every value like the settings form, saves, restarts."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        b = data.get("backup")
        if not isinstance(b, dict) or b.get("wattwind_backup") != 1 or not isinstance(b.get("config"), dict):
            return {"error": "not a WattWind settings file"}, 400
        try:
            new = restore_settings(cfg, b["config"])
        except ValueError as e:
            return {"error": "not restored: {}".format(e)}, 400
        cfg.update(new)
        profiles.ensure(cfg)
        profiles.activate(cfg, cfg["profile"])
        save(cfg)
        state.reboot_reason = "settings restored from a backup"
        state.reboot_requested = True
        return {"ok": True, "restored": len(new), "reboot": True}

    @app.get("/api/diagnostics")
    async def get_diagnostics(req):
        """One text file for analysing a problem: status, settings without secrets, files, flash, memory, Wi-Fi,
        both logbooks. Streamed. Contains the network name and sensor addresses: share it privately."""
        err = _read_pin(req)
        if err:
            return err
        return Response(diagnostics_text(cfg), headers={"Content-Type": "text/plain; charset=utf-8"})

    @app.post("/api/reboot")
    async def post_reboot(req):
        """Hard reset from the page (main.py turns the fan off first). PIN if one is set."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        state.reboot_requested = True
        return {"ok": True, "reboot": True}

    @app.post("/api/setup")
    async def post_setup(req):
        """First setup: {"ap_password", "new_pin"}; a PIN that is already set is kept unless a new one is given (and
        needed as "pin"). Only while setup is needed; nothing restarts (the password applies at the next start)."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not setup_needed(cfg):
            return {"error": "already set up: change them in Settings"}, 409
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        new = {"ap_password": data.get("ap_password"), "settings_pin": data.get("new_pin") or cfg["settings_pin"]}
        err = _own_secrets_error(new)
        if err:
            return {"error": err}, 400
        try:
            check_settings(cfg, new)
        except ValueError as e:
            return {"error": str(e)}, 400
        cfg.update(new)
        save(cfg)
        logbook.event("first setup done: own access point password and PIN")
        state.notice = ""
        return public_config(cfg)

    @app.post("/api/erase")
    async def post_erase(req):
        """Erase everything (EN 303 645 5.11): settings, riders, sensors, Wi-Fi, PIN, link keys, logbooks. main.py
        turns the fan off, deletes the files and restarts; the fan then starts as new (access point, defaults)."""
        data = _json_body(req)
        if data is None:
            return {"error": "JSON body expected"}, 400
        if not _pin_ok(cfg, data):
            return _pin_error(), 403
        if data.get("confirm") != "erase":
            return {"error": "confirm must be \"erase\""}, 400
        logbook.event("erase everything requested from the page")
        state.erase_requested = True
        state.reboot_requested = True
        return {"ok": True, "reboot": True}

    return app


async def run(cfg, scan=None):
    app = create_app(cfg, scan=scan)
    print("[{}] web: listening on port {}".format(state.uptime_s, PORT))
    await app.start_server(port=PORT)
