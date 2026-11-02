# Smart Trainer Fan: boot, task supervisor and watchdog.

# SAFETY: keep these two lines first: every relay is off before anything else is loaded.
import relay
relay.init()

# Update mode: a computer stopping the program (Thonny, mpremote, MicroPico send Ctrl-C) used to leave the
# watchdog running, so the Pico reset 8 s later, often halfway through copying files. Now Ctrl-C switches
# the relays off and restarts into update mode: nothing starts (no watchdog, relays off), so files can be
# copied calmly. It lasts until the fan is unplugged and plugged in again (from a computer: delete
# update_mode.txt, then machine.reset()). Not a function here: tools clear the REPL's names on connecting.
import os
import machine
UPDATE_FLAG = "update_mode.txt"
try:
    os.stat(UPDATE_FLAG)
    _update_mode = machine.reset_cause() != machine.PWRON_RESET
    if not _update_mode:
        os.remove(UPDATE_FLAG)          # plugged in again: back to normal
except OSError:
    _update_mode = False

# Firmware update from the web page (updater.py): a checked update waits in update/. Put it in place now,
# before anything else is loaded, then restart into the new version (this file may be one of the new ones).
if not _update_mode:
    try:
        import updater
        _new = updater.apply()
        if _new:
            with open("reset_reason.txt", "w") as f:
                f.write("firmware updated to " + _new)
            machine.reset()
    except Exception as e:              # a problem here must never stop the fan from starting
        print("update apply:", e)


# A soft reboot (Ctrl-D, or Thonny / MicroPico running or syncing files) leaves the CYW43
# radio running from the previous run; Wi-Fi then never gets an IP and BLE.active(True) hangs
# the whole board. After a real reset the interfaces are off, so if one is still on, reset.
import network
if not _update_mode and (network.WLAN(network.STA_IF).active() or network.WLAN(network.AP_IF).active()):
    print("soft reboot with the radio still on: hard reset for a clean start")
    import machine
    try:
        with open("reset_reason.txt", "w") as f:
            f.write("soft reboot (from a computer)")
    except OSError:
        pass
    machine.reset()

import gc
import sys
import time
import asyncio
import machine

# Forgot the PIN or the access point password: plug the fan in and out QUICK_BOOTS_RESET times in a
# row, each time unplugging within QUICK_BOOT_S, then plug it in and leave it. That power-up resets
# the PIN and the AP password to defaults; everything else stays. Counted early, so a 2 s plug-in counts.
QUICK_BOOTS_FILE = "quick_boots.txt"
QUICK_BOOTS_RESET = 3
QUICK_BOOT_S = 10


def _count_power_up():
    """Quick power-ups before this one, or None if this boot isn't a power-up (watchdog / reset)."""
    if machine.reset_cause() != machine.PWRON_RESET:
        return None
    try:
        with open(QUICK_BOOTS_FILE) as f:
            n = int(f.read() or 0)
    except (OSError, ValueError):
        n = 0
    with open(QUICK_BOOTS_FILE, "w") as f:
        f.write(str(n + 1))
    return n


def _clear_quick_boots():
    with open(QUICK_BOOTS_FILE, "w") as f:
        f.write("0")


try:
    _quick_boots = _count_power_up()
except Exception as e:          # a flash problem must never stop the fan from starting
    print("quick boot counter:", e)
    _quick_boots = None

import config
import state
import console
import version
import os

RESET_REASON_FILE = "reset_reason.txt"   # written just before an intentional reset, read at the next boot
ERASED_FILE = "erased.txt"                # "Erase everything" ran: show it once on the page
USER_FILES = ("config.json", "log.txt", "log.old.txt", QUICK_BOOTS_FILE, "crash_boots.txt",
              "detail.txt", "detail.old.txt", "detail.json")   # everything the user's use left behind


def _erase_user_files():
    """Erase everything (the page): the fan starts as new. Relays are already off."""
    for name in USER_FILES:
        try:
            os.remove(name)
        except OSError:
            pass
    try:
        with open(ERASED_FILE, "w") as f:
            f.write("1")
    except OSError:
        pass


def _note_reset(reason):
    logbook.write("{} RESTART {}".format(_stamp(), reason))
    try:
        with open(RESET_REASON_FILE, "w") as f:
            f.write(reason)
    except OSError:
        pass


def _boot_reason():
    try:
        with open(RESET_REASON_FILE) as f:
            reason = f.read()
        os.remove(RESET_REASON_FILE)
        return reason
    except OSError:
        pass
    cause = machine.reset_cause()
    if cause == machine.PWRON_RESET:
        return "power on"
    if cause == machine.WDT_RESET:
        return "watchdog (the program stopped responding)"
    return "reset ({})".format(cause)


state.reset_reason = _boot_reason()

# Crash loop: if the fan restarts because of an error again and again (a bug that trips over a saved setting, say),
# the page never comes up and only USB could help. After CRASH_LOOP such restarts in a row the next start uses
# default ride settings for that run only (network, Wi-Fi, PIN and sensors kept, nothing saved), so the page comes up
# and a fixed firmware can go in over Wi-Fi. Any other kind of start (power-up, update, Restart) clears the count.
CRASH_BOOTS_FILE = "crash_boots.txt"
CRASH_LOOP = 3
SAFE_KEEP = ("hostname", "wifi_ssid", "wifi_password", "ap_password", "settings_pin", "pin_for_control", "hr_addr",
             "power_addr", "hr_rr", "link_key")


def _count_crash_boot(reason):
    """Restarts in a row caused by an error, this one included (0 = this start wasn't one)."""
    if not (reason.startswith("watchdog") or reason.startswith("a task stopped responding")):
        try:
            os.remove(CRASH_BOOTS_FILE)
        except OSError:
            pass
        return 0
    try:
        with open(CRASH_BOOTS_FILE) as f:
            n = int(f.read() or 0) + 1
    except (OSError, ValueError):
        n = 1
    with open(CRASH_BOOTS_FILE, "w") as f:
        f.write(str(n))
    return n


try:
    _crash_boots = _count_crash_boot(state.reset_reason)
except Exception as e:          # a flash problem must never stop the fan from starting
    print("crash counter:", e)
    _crash_boots = 0
import logbook
logbook.write("up=0 START version={} reason={}".format(version.VERSION, state.reset_reason))

WATCHDOG = True              # set False only for bench tests (relay_test.py, MicroPico)
WDT_TIMEOUT_MS = 8000       # within both limits: RP2040 (Pico W) ~8.3 s, RP2350 (Pico 2 W) ~16.7 s
HEARTBEAT_MAX_AGE_MS = 3000  # a critical task counts as dead after this long without a heartbeat
TEMP_EVERY_S = 10            # box temperature: read the chip's sensor this often (smoothed)
LOG_EVERY_S = 300            # logbook: a status line this often while something changed (log.txt, GET /api/log)
LOG_QUIET_S = 1800           # ... and this often when nothing did (mode, level, Wi-Fi, sensors): weeks fit in the logbook
NTP_RETRY_S = 600            # real time for the logbook: from the internet once per start, retried this often

_critical = []


def _read_box_temp(adc):
    """The RP2040 / RP2350 internal sensor (ADC 4): the chip, so a few degrees above the air in the box."""
    v = sum(adc.read_u16() for _ in range(8)) / 8 * 3.3 / 65535
    t = 27 - (v - 0.706) / 0.001721
    state.box_temp = t if state.box_temp is None else state.box_temp + (t - state.box_temp) * 0.3


def _stamp():
    """'2026-10-25 21:40Z up=1234' once the time came from the internet, else 'up=1234'."""
    t = time.gmtime()
    if t[0] >= 2025:
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}Z up={}".format(t[0], t[1], t[2], t[3], t[4], state.uptime_s)
    return "up={}".format(state.uptime_s)


_status_due = logbook.StatusDue(LOG_QUIET_S)
import detail
_rec = detail.rec()           # the detailed recording (Settings -> Maintenance); continues after a restart


def _health():
    """The detailed recording's minute line."""
    gc.collect()
    return "{} free={} rssi={} chip={} hr={} power={}".format(
        _stamp(), gc.mem_free(), state.rssi, None if state.box_temp is None else round(state.box_temp),
        "on" if state.hr_connected else "off", "on" if state.power_connected else "off")


def _log_status():
    """A status line if mode, level, Wi-Fi or a sensor changed since the last one, else only every LOG_QUIET_S.
    Signal, chip temperature and free memory always move a little, so they don't count as a change."""
    if not _status_due((state.mode, state.level, state.wifi_mode, state.hr_connected, state.power_connected),
                       state.uptime_s):
        return
    gc.collect()                            # free memory after a collection: shows a slow leak, not churn
    logbook.write("{} mode={} level={} wifi={} rssi={} chip={} free={} hr={} power={}".format(
        _stamp(), state.mode, state.level, state.wifi_mode, state.rssi,
        None if state.box_temp is None else round(state.box_temp), gc.mem_free(),
        "on" if state.hr_connected else "off", "on" if state.power_connected else "off"))


def _sync_time():
    try:
        import ntptime
        ntptime.settime()                   # UTC; blocks up to ~1 s, the watchdog allows 8 s
        logbook.write("{} time set from the internet".format(_stamp()))
        return True
    except Exception as e:
        print("time sync failed:", e)
        return False


def log(*args):
    print("[{}]".format(state.uptime_s), *args)


def heartbeat(name):
    state.heartbeats[name] = time.ticks_ms()


async def supervised(name, fn, critical=False):
    """Run fn(), log any crash. Normal tasks restart after 5 s.

    A critical task is not restarted: its heartbeat stops and the supervisor resets the board.
    """
    if critical:
        _critical.append(name)
        heartbeat(name)
    while True:
        try:
            await fn()
        except Exception as e:
            log(name, "crashed:")
            sys.print_exception(e)
            try:                                # the error and where it happened, for the logbook
                import io
                buf = io.StringIO()
                sys.print_exception(e, buf)
                tb = [l.strip() for l in buf.getvalue().split("\n") if l.strip()]
                logbook.write("{} CRASH {}: {} ({})".format(_stamp(), name, tb[-1] if tb else repr(e),
                                                            tb[-2] if len(tb) > 1 else ""))
            except Exception:
                pass
        if critical:
            return
        await asyncio.sleep(5)


def _fmt(v, digits=0):
    return "-" if v is None else ("{:.%df}" % digits).format(v)


_follow = None                 # link.FollowLevel on a follower (same level), else None
_idle_logged = False           # the idle off is in the logbook (once per ride end)


def _auto_step(logic, now_s):
    """Once per second: run fan_logic (in both modes, so its filters stay warm), apply the
    manual timeout, log in auto mode. Manual is an ordinary fan: the idle off (no pedaling)
    applies only in auto, so the fan can keep running after a ride."""
    logic.nudge = state.nudge if state.mode == "auto" else 0
    target = logic.update(now_s, state.power, state.cadence, state.hr)
    if _follow is not None:
        _follow.update(now_s, state.leader_level, cfg.get("follow_offset", 0))
        if state.mode == "follow":
            print("t={} leader={} lvl={}->{} mode=follow{}".format(state.uptime_s, state.leader_level, relay.level(),
                                                                    _follow.level, "" if state.follow_fresh else " (leader silent)"))
    global _idle_logged
    idle = state.mode == "auto" and logic.idle_s >= cfg["idle_off_min"] * 60
    if idle and not _idle_logged:
        logbook.event("idle off: no riding for {} min, ride over".format(cfg["idle_off_min"]))
    _idle_logged = idle
    if state.mode == "auto":
        state.nudge = logic.nudge           # cleared by fan_logic when the ride ends
    state.p_ema, state.p_score, state.hr_score, state.demand = logic.p_ema, logic.p_score, logic.hr_score, logic.demand
    state.basis = logic.basis
    if state.mode == "manual":
        in_manual_s = state.uptime_s - state.manual_since_s
        timeout_s = cfg["manual_timeout_min"] * 60
        state.manual_left_s = max(0, timeout_s - in_manual_s) if timeout_s else None
        if state.off_at_s is not None and state.uptime_s >= state.off_at_s:
            log("off timer: fan off")
            logbook.event("off timer ran out: fan off")
            state.set_manual(0)                 # an ordinary fan's timer: off, and it stays off
        elif timeout_s and in_manual_s >= timeout_s:
            log("manual for {} min: back to auto".format(cfg["manual_timeout_min"]))
            logbook.event("manual for {} min: back to Auto".format(cfg["manual_timeout_min"]))
            state.set_auto()
    else:
        state.manual_left_s = None
    if state.mode == "auto":
        print("t={} P={} Pema={} HR={} ps={} hs={} dem={} lvl={}->{} mode=auto{} wifi={}".format(
            state.uptime_s, _fmt(state.power), _fmt(logic.p_ema), _fmt(state.hr),
            _fmt(logic.p_score, 2), _fmt(logic.hr_score, 2), _fmt(logic.demand, 2),
            relay.level(), target, " nudge={:+d}".format(state.nudge) if state.nudge else "", state.wifi_mode))


def _why_change(logic):
    """Why the fan level is changing, for the logbook line."""
    global _logic_level
    if state.uptime_s < state.update_until_s:
        return "firmware update"
    if state.mode == "follow":
        return "leader at {}".format(state.leader_level)
    if state.mode == "manual" or not logic:
        return "manual"
    if logic.level != _logic_level:
        _logic_level = logic.level
        return "auto: " + logic.why
    return "auto: nudge {:+d}".format(state.nudge) if state.nudge else "auto"


_logic_level = 0               # fan_logic's computed level at the last logged change


async def control_task():
    """Decide the fan level and apply it. The only caller of relay.set_level()."""
    try:                        # a broken fan_logic.py must not stop manual control
        import fan_logic
        logic = fan_logic.FanLogic(cfg)
        state.auto_available = True
    except Exception as e:
        log("auto mode unavailable, manual only:")
        sys.print_exception(e)
        logic = None
        state.set_manual(0)
    now_s = 0
    last_tick = time.ticks_ms()
    prev_mode = state.mode
    loop_at = time.ticks_ms()
    while True:
        heartbeat("control")
        t = time.ticks_ms()
        _rec.note_lag(time.ticks_diff(t, loop_at) - 100)   # how late this 100 ms loop runs (detailed recording)
        loop_at = t
        if time.ticks_diff(time.ticks_ms(), last_tick) >= 1000:
            last_tick = time.ticks_add(last_tick, 1000)
            now_s += 1
            if logic:
                _auto_step(logic, now_s)
        if logic and state.mode == "auto" and prev_mode != "auto":
            # back to auto: continue from the current level; the idle timer starts again
            logic.adopt(relay.level(), now_s)
        prev_mode = state.mode
        if state.uptime_s < state.update_until_s:
            state.target_level = 0                 # a firmware update is coming in: fan off
        elif state.mode == "follow" and _follow is not None:
            state.target_level = _follow.level     # the leader's running level (+ offset); see link.py
        elif state.mode == "manual" or not logic:
            state.target_level = state.manual_level if state.mode == "manual" else 0
        else:
            state.target_level = logic.target      # computed level + nudge
        before = relay.level()
        relay.ms_until_allowed()                   # forgets a finished rate-limit wait (ticks wrap after ~6 days)
        if state.target_level != before and relay.set_level(state.target_level):
            log("fan level {} -> {} (mode={})".format(before, state.target_level, state.mode))
            why = _why_change(logic)
            logbook.event("fan {} -> {} ({})".format(before, state.target_level, why))
            _rec.line(state.uptime_s, "E", "fan {} -> {} ({})".format(before, state.target_level, why))
        state.level = relay.level()
        await asyncio.sleep_ms(100)


async def wifi_task():
    import wifi                 # imported here: an error is logged and retried, fan control keeps running
    await wifi.run(cfg)


async def web_task():
    gc.collect()                # Microdot is the biggest import: start from a clean heap
    import web
    await web.run(cfg, scan=ble_scan)


BLE_WAIT_WIFI_S = 30         # Wi-Fi tries 20 s, then starts the access point


async def link_task():
    import link                 # linked fans: broadcast as a leader / listen as a follower
    await link.run(cfg)


async def ble_task():
    if cfg.get("follow_id"):    # a follower takes its leader's data: no Bluetooth (frees the sensors' connections)
        log("following", cfg.get("follow_name") or cfg["follow_id"], "- Bluetooth off")
        while True:
            await asyncio.sleep(3600)
    # Wi-Fi and BLE share the CYW43 radio: BLE scanning during the join makes a weak network
    # miss it (seen at -77 dBm: 10 s, 19 s, gave up). Sensors can wait a few seconds at boot.
    for _ in range(BLE_WAIT_WIFI_S):
        if state.wifi_mode not in ("off", "connecting") or state.uptime_s > BLE_WAIT_WIFI_S:
            break
        await asyncio.sleep(1)
    gc.collect()
    import ble_sensors
    await ble_sensors.run(cfg)


async def share_task():
    """Heart rate sharing (setting hr_share): the fan as a Bluetooth heart-rate sensor. Not on a follower."""
    if cfg.get("follow_id"):
        while True:
            await asyncio.sleep(3600)
    for _ in range(BLE_WAIT_WIFI_S):    # like ble_task: let Wi-Fi join first
        if state.wifi_mode not in ("off", "connecting") or state.uptime_s > BLE_WAIT_WIFI_S:
            break
        await asyncio.sleep(1)
    import ble_share
    await ble_share.run(cfg)


async def ble_scan():
    """For the web page's sensor list (GET /api/scan)."""
    import ble_sensors
    return await ble_sensors.scan_nearby()


async def check_files():
    """Once after start: the firmware files against manifest.json (integrity.py). Report only."""
    await asyncio.sleep(5)                  # after the start-up rush
    try:
        import integrity
        state.files = await integrity.check()
    except Exception as e:
        state.files = "check failed: {}".format(e)
    log("files:", state.files)
    logbook.write("up={} files {}".format(state.uptime_s, state.files))


async def main():
    global _quick_boots
    wdt = machine.WDT(timeout=WDT_TIMEOUT_MS) if WATCHDOG else None
    if not wdt:
        log("WARNING: watchdog disabled in main.py (bench testing only)")

    asyncio.create_task(supervised("control", control_task, critical=True))
    asyncio.create_task(supervised("console", console.run))
    asyncio.create_task(supervised("wifi", wifi_task))
    asyncio.create_task(supervised("web", web_task))
    asyncio.create_task(supervised("ble", ble_task))
    asyncio.create_task(supervised("share", share_task))
    asyncio.create_task(supervised("link", link_task))
    asyncio.create_task(check_files())

    last = time.ticks_ms()
    up_ms = 0
    try:
        temp_adc = machine.ADC(4)
    except Exception as e:                  # no sensor: no temperature, nothing else changes
        log("box temperature unavailable:", e)
        temp_adc = None
    next_temp = 0
    next_log = LOG_EVERY_S
    next_ntp = 30
    time_set = False
    while True:
        now = time.ticks_ms()
        up_ms += time.ticks_diff(now, last)     # summed in small steps: ticks_diff(now, boot) is only
        last = now                              # valid up to ~6 days, the fan may run for weeks
        state.uptime_s = up_ms // 1000
        dead = [n for n in _critical if time.ticks_diff(now, state.heartbeats[n]) > HEARTBEAT_MAX_AGE_MS]
        if dead:
            log("task not responding:", ", ".join(dead), "- fan off, resetting")
            relay.set_level(0, force=True)
            _note_reset("a task stopped responding: " + ", ".join(dead))
            await asyncio.sleep_ms(500)
            machine.reset()
        if _quick_boots is not None and state.uptime_s >= QUICK_BOOT_S:
            _clear_quick_boots()            # ran long enough: not a quick power-up
            _quick_boots = None
        if state.update_until_s and state.uptime_s >= state.update_until_s:
            state.update_until_s = 0            # the page stopped sending: give the update up
            import updater
            if updater.active():
                updater.cancel()
                log("firmware update abandoned")
                logbook.event("firmware update abandoned (no data for a minute), nothing changed")
        if state.reboot_requested:
            log("reboot requested from the web page - fan off")
            relay.set_level(0, force=True)
            if not state.erase_requested:
                _note_reset(state.reboot_reason or "restart from the page")
            await asyncio.sleep_ms(1000)    # let the web response go out first
            if state.erase_requested:
                _erase_user_files()         # no await between this and the reset: nothing writes them back
                _note_reset("everything erased from the page")
            machine.reset()
        if state.uptime_s >= next_log:
            next_log = state.uptime_s + LOG_EVERY_S
            _log_status()
        try:
            done = _rec.second(state.uptime_s, state, cfg, _health)
            if done:
                logbook.event("detailed recording " + ("ended (24 h)" if done == "ended" else "deleted (kept 7 days)"))
        except Exception as e:
            print("detail:", e)
        if not time_set and state.wifi_mode == "sta" and state.uptime_s >= next_ntp:
            next_ntp = state.uptime_s + NTP_RETRY_S
            time_set = _sync_time()
        if temp_adc and state.uptime_s >= next_temp:
            next_temp = state.uptime_s + TEMP_EVERY_S
            try:
                _read_box_temp(temp_adc)
            except Exception:
                pass
        if wdt:
            wdt.feed()
        await asyncio.sleep_ms(1000)


def _enter_update_mode():
    relay.set_level(0, force=True)
    print("relays off - stopped from a computer: restarting into update mode")
    try:
        with open(UPDATE_FLAG, "w") as f:
            f.write("1")
    except OSError:
        pass
    _note_reset("update mode (stopped from a computer)")
    time.sleep_ms(300)
    machine.reset()


if _update_mode:
    print()
    print("UPDATE MODE: the fan program is stopped, relays off, no watchdog.")
    print("Copy the files, then unplug the fan and plug it in again.")
    try:                                # the next start, however it comes, says why
        with open(RESET_REASON_FILE, "w") as f:
            f.write("end of update mode")
    except OSError:
        pass
else:
    def _safe_settings(saved):
        """Default ride settings, keeping network, Wi-Fi, PIN and sensors; never saved (config.read_only)."""
        import profiles
        c = dict(config.DEFAULTS)
        for k in SAFE_KEEP:
            if k in saved:
                c[k] = saved[k]
        c.pop("profiles", None)
        profiles.ensure(c)
        config.read_only = True
        state.safe_start = True
        return c

    def _start_safe(saved, why, text):
        global cfg
        cfg = _safe_settings(saved)
        state.notice = text
        logbook.event("SAFE START: " + why)
        log("SAFE START:", why)

    try:
        cfg = config.load()
        if config.damaged:                  # unreadable config.json: defaults now, a copy in config.json.bad
            state.notice = ("The settings file was damaged, so the fan started with default settings (a copy is kept as "
                            "config.json.bad). Restore a backup if you have one: Settings → Maintenance → Restore from a file.")
            logbook.event("settings file damaged: started with defaults, copy in config.json.bad")
        import checks                       # every saved value as the page checks it: a bad one goes back to default
        fixed = checks.sanitize(cfg)
        if fixed:
            config.save(cfg)
            state.notice = ("Some saved settings were not valid and are back to their defaults: {}. Check them in "
                            "Settings.".format(", ".join(fixed)))
            logbook.event("settings not valid, back to defaults: " + ", ".join(fixed))
        if _quick_boots is not None and _quick_boots >= QUICK_BOOTS_RESET:
            cfg["settings_pin"] = ""
            cfg["ap_password"] = config.DEFAULTS["ap_password"]
            cfg["pin_for_control"] = False
            config.save(cfg)
            _clear_quick_boots()
            _quick_boots = None
            state.notice = "PIN and access point password were reset (plugged in and out 3 times)."
            log(state.notice)
        if _crash_boots >= CRASH_LOOP:
            _start_safe(cfg, "{} restarts in a row after an error".format(_crash_boots),
                        "The fan restarted {} times in a row after an error, so it started with default ride settings "
                        "this time. Your saved settings are kept, but can't be changed until the next normal start. "
                        "Install the latest firmware (Settings → Maintenance), or Restart to try your settings again. "
                        "The logbook shows what failed.".format(_crash_boots))
        state.rider = cfg["profiles"][cfg["profile"]]["name"] if len(cfg["profiles"]) > 1 else ""
        if cfg.get("follow_id"):            # linked fans: this one follows a leader (link.py)
            import link
            state.follow = {"id": cfg["follow_id"], "name": cfg.get("follow_name", ""),
                            "mode": cfg.get("follow_mode", "same"), "offset": cfg.get("follow_offset", 0)}
            state.follow_same = state.follow["mode"] == "same"
            _follow = link.FollowLevel()
            state.set_auto()                # same level: starts in "follow" (relays off until the leader is heard)
    except Exception as e:                  # the start-up itself failed: an error here would stop the fan for good
        try:
            sys.print_exception(e)
        except Exception:
            pass
        state.follow, state.follow_same, _follow = None, False, None
        _start_safe(globals().get("cfg") or {}, "start-up failed: {!r}".format(e)[:120],
                    "The fan couldn't start with its saved settings ({!r}), so it started with default ride settings. "
                    "Your saved settings are kept. Install the latest firmware (Settings → Maintenance), or report it "
                    "with the logbook.".format(e)[:300])
        state.rider = ""
    log("WattWind", version.VERSION, "starting, relays off; last restart:", state.reset_reason)
    try:
        os.remove(ERASED_FILE)
        state.notice = "Everything was erased: settings, riders, sensors, Wi-Fi, PIN, link keys and logbooks. The fan starts as new."
        log(state.notice)
    except OSError:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:           # Ctrl-C from a computer: update mode (see the top)
        _enter_update_mode()
    finally:
        relay.set_level(0, force=True)
        print("relays off")
