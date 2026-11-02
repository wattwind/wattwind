"""main.py: the real boot script, run in a sandbox (a temp folder, stand-in machine / network, virtual clock; see
tests/mpy_sim.py). Covers the start-up (reset reasons, update mode, a staged update, the plug-in PIN reset, erase,
damaged settings), control_task (auto, manual, timers, firmware update, reasons in the logbook) and the supervisor
loop (watchdog, dead task, reboot, erase, uptime across the tick wrap)."""
import asyncio
import importlib
import json
import os
import sys
import types

import pytest

import config
import state
from conftest import FIRMWARE
from mpy_sim import PERIOD, Clock, FakeMachine, FakeNetwork, Reset, run_until

MAIN = os.path.join(FIRMWARE, "main.py")


@pytest.fixture
def pico(tmp_path, monkeypatch):
    """boot(**files, cause=...) runs main.py up to its asyncio.run(main()) and returns the module."""
    monkeypatch.chdir(tmp_path)
    events = []
    import logbook
    import detail
    monkeypatch.setattr(logbook, "write", events.append)
    monkeypatch.setattr(detail, "_rec", None)          # a fresh recorder in the temp folder
    monkeypatch.setattr(config, "damaged", False)
    monkeypatch.setattr(config, "read_only", False)
    started = []
    monkeypatch.setattr(asyncio, "run", lambda coro: (started.append(coro.__name__), coro.close()))
    import gc
    import traceback
    monkeypatch.setattr(gc, "mem_free", lambda: 200000, raising=False)                  # MicroPython only
    monkeypatch.setattr(sys, "print_exception", lambda e, f=sys.stdout: traceback.print_exception(e, file=f),
                        raising=False)

    def boot(cause=FakeMachine.PWRON_RESET, files=None, radio_on=False, clock_state=True):
        importlib.reload(state)
        for name, text in (files or {}).items():
            os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
            with open(name, "w") as f:
                f.write(text)
        m = FakeMachine(cause)
        monkeypatch.setitem(sys.modules, "machine", m)
        clock = Clock(monkeypatch, state if clock_state else None)
        net = FakeNetwork(clock)
        if radio_on:
            net.WLAN(net.STA_IF).active(True)
        monkeypatch.setitem(sys.modules, "network", net)
        mod = types.ModuleType("wattwind_main")
        mod.__file__ = MAIN
        code = compile(open(MAIN, encoding="utf-8").read(), MAIN, "exec")
        try:
            exec(code, mod.__dict__)
        except Reset:
            mod.reset_at_boot = True
        import relay
        relay._last_change = None        # main.py's last line (relays off when asyncio.run ends) ran here at once;
                                         # on the Pico asyncio.run(main()) never returns
        return types.SimpleNamespace(mod=mod, m=m, clock=clock, events=events, started=started)
    return boot


def relays(m):
    import relay
    return {"K0": m.pins.get(relay.K0_PIN), "speed": [m.pins.get(p) for p in relay.SPEED_PINS]}


def text(p):
    return "\n".join(p.events)


# ---- start-up ----------------------------------------------------------------------------------

def test_power_on_boots_with_relays_off(pico):
    p = pico()
    assert relays(p.m) == {"K0": 0, "speed": [0, 0, 0]}
    assert state.reset_reason == "power on"
    assert "START version=" in text(p) and "reason=power on" in text(p)
    assert p.started == ["main"]                            # the main loop would start
    assert os.path.exists("config.json")                    # first start: settings created


@pytest.mark.parametrize("cause,files,reason", [
    (FakeMachine.WDT_RESET, {}, "watchdog (the program stopped responding)"),
    (FakeMachine.WDT_RESET, {"reset_reason.txt": "restart from the page"}, "restart from the page"),
    (FakeMachine.SOFT_RESET, {}, "reset (5)"),
])
def test_reset_reasons(pico, cause, files, reason):
    p = pico(cause=cause, files=files)
    assert state.reset_reason == reason
    assert not os.path.exists("reset_reason.txt")           # read once


def test_update_mode_runs_nothing_until_a_power_up(pico):
    p = pico(cause=FakeMachine.WDT_RESET, files={"update_mode.txt": "1"})
    assert p.started == [] and not hasattr(p.mod, "cfg")    # no program, no watchdog
    assert relays(p.m) == {"K0": 0, "speed": [0, 0, 0]}
    assert open("reset_reason.txt").read() == "end of update mode"
    assert os.path.exists("update_mode.txt")


def test_power_up_ends_update_mode(pico):
    p = pico(files={"update_mode.txt": "1"})
    assert p.started == ["main"] and not os.path.exists("update_mode.txt")


def test_a_staged_update_is_put_in_place_then_restart(pico):
    files = {"update/newfile.py": "x = 1\n", "update_apply.json": json.dumps({"version": "9.9.9", "files": ["newfile.py"]})}
    p = pico(cause=FakeMachine.WDT_RESET, files=files)
    assert getattr(p.mod, "reset_at_boot", False) and p.m.resets == 1
    assert open("newfile.py").read() == "x = 1\n"
    assert open("reset_reason.txt").read() == "firmware updated to 9.9.9"


def test_soft_reboot_with_the_radio_on_resets(pico):
    p = pico(cause=FakeMachine.SOFT_RESET, radio_on=True)
    assert getattr(p.mod, "reset_at_boot", False)
    assert open("reset_reason.txt").read() == "soft reboot (from a computer)"


def test_three_quick_plug_ins_reset_pin_and_access_point_password(pico, tmp_path):
    cfg = dict(config.DEFAULTS, settings_pin="1234", ap_password="mine12345", pin_for_control=True, ftp=240)
    p = pico(files={"config.json": json.dumps(cfg), "quick_boots.txt": "3"})
    saved = json.load(open("config.json"))
    assert saved["settings_pin"] == "" and saved["ap_password"] == "wattwind" and saved["pin_for_control"] is False
    assert saved["ftp"] == 240                              # everything else stays
    assert "PIN and access point password were reset" in state.notice
    assert open("quick_boots.txt").read() == "0"


def test_two_quick_plug_ins_change_nothing(pico):
    cfg = dict(config.DEFAULTS, settings_pin="1234")
    pico(files={"config.json": json.dumps(cfg), "quick_boots.txt": "2"})
    assert json.load(open("config.json"))["settings_pin"] == "1234"
    assert open("quick_boots.txt").read() == "3"            # counted


def test_a_watchdog_restart_is_not_a_plug_in(pico):
    pico(cause=FakeMachine.WDT_RESET, files={"quick_boots.txt": "2"})
    assert open("quick_boots.txt").read() == "2"


def test_erased_notice_once(pico):
    pico(files={"erased.txt": "1"})
    assert state.notice.startswith("Everything was erased") and not os.path.exists("erased.txt")


def test_damaged_settings_notice(pico):
    pico(files={"config.json": "{broken"})
    assert state.notice.startswith("The settings file was damaged")
    assert os.path.exists("config.json.bad")


# ---- control_task ------------------------------------------------------------------------------

def run_control(p, seconds, stop=None):
    return run_until(p.mod.control_task(), p.clock, p.clock.s + seconds, stop=stop)


def test_auto_ride_steps_up_with_reasons(pico):
    p = pico()
    state.power, state.cadence = 230, 90                     # FTP 200: demand above 1
    run_control(p, 60)
    import relay
    assert relay.level() == 3 and relays(p.m) == {"K0": 1, "speed": [0, 0, 1]}
    lines = [e for e in p.events if " fan " in e]
    assert [l.split("fan ")[1][:6] for l in lines] == ["0 -> 1", "1 -> 2", "2 -> 3"]
    assert "(auto: demand " in lines[0] and "(power)" in lines[0]


def ride(p, phases):
    """One continuous control_task through phases [(until_s, power, cadence), ...] (a restart of control_task
    would start a fresh fan_logic, which never happens on the fan: it is critical, a crash resets the board)."""
    def inputs():
        for until, pw, cad in phases:
            if p.clock.s < until:
                state.power, state.cadence = pw, cad
                return False
        return True
    return run_until(p.mod.control_task(), p.clock, phases[-1][0] + 1, stop=inputs)


def test_stopped_pedaling_steps_down_with_its_reason(pico):
    p = pico()
    ride(p, [(60, 230, 90), (300, 0, 0)])
    import relay
    assert relay.level() == 0
    down = [e for e in p.events if " fan " in e][3:]
    assert [l.split("fan ")[1][:6] for l in down] == ["3 -> 2", "2 -> 1", "1 -> 0"]
    assert all("(auto: stopped pedaling)" in l for l in down)


def test_manual_level_and_the_rate_limit(pico):
    p = pico()
    import relay
    state.set_manual(1)
    run_control(p, 0.5)
    assert relay.level() == 1
    state.set_manual(3)
    run_control(p, 1.0)
    assert relay.level() == 1                                # less than 2 s since the last change
    run_control(p, 1.5)
    assert relay.level() == 3
    assert text(p).count("(manual)") == 2


def test_manual_timeout_back_to_auto(pico):
    p = pico()
    p.mod.cfg["manual_timeout_min"] = 1
    state.set_manual(2)
    run_control(p, 70)
    assert state.mode == "auto" and "manual for 1 min: back to Auto" in text(p)


def test_off_timer(pico):
    p = pico()
    import relay
    state.set_manual(2)
    state.off_at_s = state.uptime_s + 30
    run_control(p, 25)
    assert relay.level() == 2
    run_control(p, 10)
    assert relay.level() == 0 and state.mode == "manual" and "off timer ran out" in text(p)


def test_fan_off_while_a_firmware_update_comes_in(pico):
    p = pico()
    import relay
    state.set_manual(3)
    run_control(p, 3)
    state.update_until_s = state.uptime_s + 60
    run_control(p, 5)
    assert relay.level() == 0 and "(firmware update)" in text(p)


def test_idle_off_logged_once_per_ride_end(pico):
    p = pico()
    p.mod.cfg["idle_off_min"] = 1
    state.power, state.cadence = 230, 90
    run_control(p, 30)
    state.power = state.cadence = None                       # sensors gone
    run_control(p, 200)
    assert text(p).count("idle off: no riding for 1 min") == 1


# ---- the supervisor loop (main) -----------------------------------------------------------------

@pytest.fixture
def loop(pico, monkeypatch):
    """main() with its tasks not started (each is tested on its own): only the supervisor loop runs."""
    def make(**kw):
        p = pico(clock_state=False, **kw)
        monkeypatch.setattr(asyncio, "create_task", lambda coro: coro.close())
        return p
    return make


def test_watchdog_fed_and_status_lines(loop):
    p = loop()
    run_until(p.mod.main(), p.clock, 400)
    assert p.m.fed >= 390
    assert any(" mode=auto level=0 " in e for e in p.events)  # the 5-minute status line


def test_a_dead_critical_task_turns_off_and_resets(loop):
    p = loop()
    import relay
    relay.set_level(2, force=True)
    p.mod._critical.append("control")
    state.heartbeats["control"] = -10000 % PERIOD            # long ago
    with pytest.raises(Reset):
        run_until(p.mod.main(), p.clock, 30)
    assert relay.level() == 0
    assert open("reset_reason.txt").read() == "a task stopped responding: control"


def test_reboot_from_the_page(loop):
    p = loop()
    state.reboot_requested, state.reboot_reason = True, "restart from the page"
    with pytest.raises(Reset):
        run_until(p.mod.main(), p.clock, 30)
    assert open("reset_reason.txt").read() == "restart from the page"


def test_erase_everything_removes_the_user_files(loop):
    p = loop(files={"log.txt": "x", "detail.txt": "x", "quick_boots.txt": "0"})
    state.reboot_requested = state.erase_requested = True
    with pytest.raises(Reset):
        run_until(p.mod.main(), p.clock, 30)
    for f in ("config.json", "log.txt", "detail.txt", "quick_boots.txt"):
        assert not os.path.exists(f), f
    assert os.path.exists("erased.txt")
    assert open("reset_reason.txt").read() == "everything erased from the page"


def test_quick_boot_count_cleared_after_running_a_while(loop):
    p = loop(files={"quick_boots.txt": "1"})
    run_until(p.mod.main(), p.clock, 15)
    assert open("quick_boots.txt").read() == "0"


def test_uptime_keeps_counting_across_the_tick_wrap(loop):
    p = loop()
    p.clock.ms = PERIOD - 5000                               # the ms counter wraps 5 s from now
    run_until(p.mod.main(), p.clock, p.clock.s + 20)
    assert 19 <= state.uptime_s <= 21


def test_supervised_task_restarts_after_a_crash(pico):
    p = pico()
    calls = []

    async def flaky():
        calls.append(p.clock.s)
        raise ValueError("boom")
    run_until(p.mod.supervised("web", flaky), p.clock, 12)
    assert len(calls) == 3 and calls[1] - calls[0] == pytest.approx(5)
    assert "CRASH web: ValueError: boom" in text(p)


def test_a_crashed_critical_task_is_not_restarted(pico):
    p = pico()
    calls = []

    async def dies():
        calls.append(1)
        raise ValueError("boom")
    run_until(p.mod.supervised("control", dies, critical=True), p.clock, 20)
    assert calls == [1]                                      # the watchdog path takes over (test above)


# ---- start-up checks and the crash loop ---------------------------------------------------------------------------

def test_a_bad_saved_value_is_reset_at_start_and_named(pico):
    cfg = dict(config.DEFAULTS, ftp="240", hostname="ok-name")
    pico(files={"config.json": json.dumps(cfg)})
    saved = json.load(open("config.json"))
    assert saved["ftp"] == 200 and saved["hostname"] == "ok-name"
    assert "not valid and are back to their defaults: ftp" in state.notice


@pytest.mark.parametrize("reason", ["a task stopped responding: control", None])   # None: the watchdog itself
def test_third_crash_restart_in_a_row_starts_safe(pico, reason):
    cfg = dict(config.DEFAULTS, ftp=240, settings_pin="1234", ap_password="mine12345", wifi_ssid="HomeWiFi")
    files = {"config.json": json.dumps(cfg), "crash_boots.txt": "2"}
    if reason:
        files["reset_reason.txt"] = reason
    p = pico(cause=FakeMachine.WDT_RESET, files=files)
    assert state.safe_start and config.read_only
    assert p.mod.cfg["ftp"] == 200                                # default ride settings in memory ...
    assert p.mod.cfg["settings_pin"] == "1234" and p.mod.cfg["wifi_ssid"] == "HomeWiFi"   # ... network and PIN kept
    assert json.load(open("config.json"))["ftp"] == 240           # the saved settings untouched
    config.save(p.mod.cfg)
    assert json.load(open("config.json"))["ftp"] == 240           # and can't be overwritten in this run
    assert "restarted 3 times in a row" in state.notice and "SAFE START" in text(p)
    assert p.started == ["main"]                                  # the fan runs: the page comes up


def test_two_crash_restarts_still_start_normally(pico):
    cfg = dict(config.DEFAULTS, ftp=240)
    p = pico(cause=FakeMachine.WDT_RESET, files={"config.json": json.dumps(cfg), "crash_boots.txt": "1"})
    assert not state.safe_start and p.mod.cfg["ftp"] == 240
    assert open("crash_boots.txt").read() == "2"


@pytest.mark.parametrize("cause,files", [(FakeMachine.PWRON_RESET, {}),
                                         (FakeMachine.WDT_RESET, {"reset_reason.txt": "restart from the page"}),
                                         (FakeMachine.WDT_RESET, {"reset_reason.txt": "firmware updated to 1.0.1"})])
def test_any_other_start_clears_the_crash_count(pico, cause, files):
    p = pico(cause=cause, files=dict(files, **{"crash_boots.txt": "5"}))
    assert not state.safe_start and not os.path.exists("crash_boots.txt")


def test_an_error_during_start_up_starts_safe_instead_of_stopping(pico, monkeypatch):
    import link
    cfg = dict(config.DEFAULTS, follow_id="WattWind-1234", follow_key="k" * 32, settings_pin="1234")

    class Broken:
        def __init__(self):
            raise RuntimeError("boom")
    monkeypatch.setattr(link, "FollowLevel", Broken)
    p = pico(files={"config.json": json.dumps(cfg)})
    assert state.safe_start and p.started == ["main"]
    assert p.mod.cfg["follow_id"] == "" and p.mod._follow is None and state.follow is None
    assert "couldn't start with its saved settings" in state.notice and "boom" in state.notice
