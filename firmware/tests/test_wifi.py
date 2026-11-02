"""wifi.py on a virtual clock with a scripted router (tests/mpy_sim.py): client mode, the access point, falling back
and switching back, the test join from the setup page. Minutes of Wi-Fi life run in milliseconds."""
import asyncio
import importlib
import sys
import types

import pytest

import config
import state
from mpy_sim import Clock, FakeNetwork, run_until


@pytest.fixture
def wifi_env(monkeypatch):
    importlib.reload(state)
    clock = Clock(monkeypatch, state)
    events = []
    import logbook
    monkeypatch.setattr(logbook, "write", events.append)

    async def serve(ip, log):                       # captive DNS: just wait (tested in test_dns.py)
        await asyncio.Event().wait()
    monkeypatch.setitem(sys.modules, "dns", types.SimpleNamespace(serve=serve))

    def make(ssid="HomeWiFi", password="secretpass", **net_kw):
        net = FakeNetwork(clock, **net_kw)
        monkeypatch.setitem(sys.modules, "network", net)
        sys.modules.pop("wifi", None)
        import wifi
        cfg = dict(config.DEFAULTS, wifi_ssid=ssid, wifi_password=password, ap_password="ownpassword1")
        return wifi, net, cfg
    return clock, events, make


def log_text(events):
    return "\n".join(events)


def test_no_network_saved_starts_the_access_point(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(ssid="")
    run_until(wifi.run(cfg), clock, 600, stop=None)
    assert state.wifi_mode == "ap" and state.ip == "192.168.4.1"
    assert state.wifi_ssid == "WattWind-1A2B"                      # last 2 bytes of the MAC
    assert net.WLAN(net.AP_IF).cfg == {"essid": "WattWind-1A2B", "password": "ownpassword1"}
    assert net.joins == []                                         # nothing to try


def test_home_network_joins_in_client_mode(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make()
    run_until(wifi.run(cfg), clock, 60)
    assert state.wifi_mode == "sta" and state.ip == "192.168.1.50" and state.rssi == -60
    assert not net.WLAN(net.AP_IF).active()
    assert "connected to HomeWiFi after 2 s" in log_text(events)


def test_router_off_at_start_then_back(wifi_env):
    """A power cut: the router needs longer than the fan. Access point after 20 s, the home network is tried again
    after 2 minutes, then every 5 minutes, and the fan switches back."""
    clock, events, make = wifi_env
    wifi, net, cfg = make(router_up=lambda t: t >= 300)
    run_until(wifi.run(cfg), clock, 2000, stop=lambda: state.wifi_mode == "sta")
    assert state.wifi_mode == "sta"
    tries = sorted({int(t) for t, _ in net.joins})
    assert tries[0] == 0                                          # at start
    retry_starts = [t for t in tries if t >= 100]
    assert 135 <= retry_starts[0] <= 145                          # first retry from the access point: ~2 min
    assert 440 <= clock.s <= 470                                  # back at the 2nd retry (5 min later)
    assert not net.WLAN(net.AP_IF).active()
    assert "back on HomeWiFi" in log_text(events)


def test_short_drop_reconnects_without_the_access_point(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(router_up=lambda t: not 100 <= t < 160)
    modes = set()
    run_until(wifi.run(cfg), clock, 400, stop=lambda: modes.add(state.wifi_mode) or False)
    assert state.wifi_mode == "sta"
    assert "ap" not in modes and "connecting" in modes
    assert "connection lost" in log_text(events) and "router gone" not in log_text(events)


def test_long_drop_switches_to_the_access_point(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(router_up=lambda t: t < 100)
    run_until(wifi.run(cfg), clock, 400, stop=lambda: state.wifi_mode == "ap")
    assert state.wifi_mode == "ap"
    assert 215 <= clock.s <= 260                                  # lost at ~100 s, gives up after FALLBACK_AP_S
    assert "router gone for 120 s" in log_text(events)


def test_wrong_password_goes_to_the_access_point_at_once(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(password="wrongpass")
    run_until(wifi.run(cfg), clock, 100, stop=lambda: state.wifi_mode == "ap")
    assert state.wifi_mode == "ap" and clock.s < 5
    assert "wrong password for HomeWiFi" in log_text(events)


def test_no_switch_while_someone_uses_the_page_on_the_access_point(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(router_up=lambda t: t >= 30)

    def page_open():                                              # the setup page polls every 1.5 s
        state.page_seen_s = state.uptime_s
        return False
    run_until(wifi.run(cfg), clock, 700, stop=page_open)
    assert state.wifi_mode == "ap"                                # never left while the page was in use
    assert all(t < 25 for t, _ in net.joins)                      # no retry at all after the first 20 s


def test_test_join_from_the_setup_page(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(ssid="")
    state.wifi_test_request = ("HomeWiFi", "secretpass")
    run_until(wifi.run(cfg), clock, 100, stop=lambda: state.wifi_test["state"] not in ("idle", "testing"))
    assert state.wifi_test == {"state": "ok", "ssid": "HomeWiFi", "ip": "192.168.1.50", "error": ""}
    assert state.wifi_mode == "ap"                                # nothing switched: the page asks first
    assert not net.WLAN(net.STA_IF).active()


def test_test_join_wrong_password(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(ssid="")
    state.wifi_test_request = ("HomeWiFi", "nope12345")
    run_until(wifi.run(cfg), clock, 100, stop=lambda: state.wifi_test["state"] not in ("idle", "testing"))
    assert state.wifi_test["state"] == "failed" and state.wifi_test["error"] == "wrong password"


def test_a_bad_access_point_password_falls_back_to_the_default_never_open(wifi_env):
    clock, events, make = wifi_env
    wifi, net, cfg = make(ssid="")
    cfg["ap_password"] = "short"
    run_until(wifi.run(cfg), clock, 30)
    assert net.WLAN(net.AP_IF).cfg["password"] == "wattwind"
