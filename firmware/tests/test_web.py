import asyncio
import importlib

import pytest

import config
import state
import web
from conftest import FIRMWARE
from microdot_test_client import TestClient


@pytest.fixture
def env(monkeypatch):
    importlib.reload(state)              # fresh runtime state for every test
    monkeypatch.chdir(FIRMWARE)          # www/index.html is opened relative to the Pico's root
    cfg = dict(config.DEFAULTS)
    saved = []
    client = TestClient(web.create_app(cfg, save=lambda c: saved.append(dict(c))))
    return cfg, saved, client


def run(coro):
    return asyncio.run(coro)


def post(client, path, body):
    return run(client.post(path, body=body))


def test_index_served(env):
    _, _, client = env
    res = run(client.get("/"))
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("text/html")
    assert "WattWind" in res.text


def test_status(env):
    _, _, client = env
    state.level = 2
    state.ip = "192.168.4.1"
    res = run(client.get("/api/status"))
    assert res.status_code == 200
    assert res.json["level"] == 2 and res.json["mode"] == "auto"   # starts in auto
    assert res.json["ip"] == "192.168.4.1"


def test_manual_level(env):
    _, _, client = env
    res = post(client, "/api/mode", {"mode": "manual", "level": 3})
    assert res.status_code == 200
    assert state.mode == "manual" and state.manual_level == 3


@pytest.mark.parametrize("level", [-1, 4, 1.5, "2", True, None])
def test_manual_level_invalid(env, level):
    _, _, client = env
    res = post(client, "/api/mode", {"mode": "manual", "level": level})
    assert res.status_code == 400
    assert state.manual_level == 0


def test_auto_refused_until_available(env):
    _, _, client = env
    state.set_manual(0)
    assert post(client, "/api/mode", {"mode": "auto"}).status_code == 409
    assert state.mode == "manual"
    state.auto_available = True
    assert post(client, "/api/mode", {"mode": "auto"}).status_code == 200
    assert state.mode == "auto"


def test_auto_nudge(env):
    _, _, client = env
    state.auto_available = True
    r = post(client, "/api/mode", {"mode": "auto", "nudge": 1})
    assert r.status_code == 200 and r.json["nudge"] == 1 and state.nudge == 1
    assert post(client, "/api/mode", {"mode": "auto"}).json["nudge"] == 1      # Auto again keeps it
    for bad in (3, -3, "1", 1.5):
        assert post(client, "/api/mode", {"mode": "auto", "nudge": bad}).status_code == 400
    post(client, "/api/mode", {"mode": "manual", "level": 2})                  # manual clears it
    assert state.nudge == 0
    assert post(client, "/api/mode", {"mode": "auto"}).json["nudge"] == 0


def test_bad_body(env):
    _, _, client = env
    assert post(client, "/api/mode", {"mode": "fast"}).status_code == 400
    res = run(client.post("/api/mode", headers={"Content-Type": "application/json"}, body="{bad"))
    assert res.status_code == 400


def test_config_hides_secrets(env):
    cfg, _, client = env
    cfg["wifi_password"] = "secret123"
    cfg["settings_pin"] = "1234"
    res = run(client.get("/api/config"))
    assert res.status_code == 200
    for key in web.SECRETS:
        assert key not in res.json
    assert res.json["pin_set"] is True
    assert res.json["ftp"] == config.DEFAULTS["ftp"]


def test_config_saved_only_on_change(env):
    cfg, saved, client = env
    res = post(client, "/api/config", {"ftp": 280, "hr_max": cfg["hr_max"]})
    assert res.status_code == 200 and res.json["changed"] == ["ftp"]
    assert cfg["ftp"] == 280 and len(saved) == 1
    res = post(client, "/api/config", {"ftp": 280})
    assert res.json["changed"] == [] and len(saved) == 1


def test_response_setting(env):
    cfg, _, client = env
    assert post(client, "/api/config", {"response": "quick"}).status_code == 200
    assert cfg["response"] == "quick"
    assert post(client, "/api/config", {"response": "fast"}).status_code == 400


def test_hr_share_setting_and_status(env):
    cfg, saved, client = env
    assert run(client.get("/api/config")).json["hr_share"] is False
    st = run(client.get("/api/status")).json
    assert st["hr_share"] == "off" and st["hr_share_name"] == ""
    res = post(client, "/api/config", {"hr_share": True})
    assert res.status_code == 200 and res.json["changed"] == ["hr_share"] and cfg["hr_share"] is True
    state.share, state.share_name = "connected", "WattWind-1A2B HR"
    st = run(client.get("/api/status")).json
    assert (st["hr_share"], st["hr_share_name"]) == ("connected", "WattWind-1A2B HR")


def test_help_page_served(env):
    _, _, client = env
    res = run(client.get("/help"))
    assert res.status_code == 200 and "WattWind" in res.text


@pytest.mark.parametrize("body", [
    {"ftp": 20},
    {"ftp": "250"},
    {"ftp": 250.5},
    {"hr_rest": 100, "hr_max": 100},
    {"up_thresholds": [0.5, 0.4, 0.9]},
    {"up_thresholds": [0.5, 0.7]},
    {"down_thresholds": [0.5, 0.63, 0.81]},     # 0.5 is above level 1's step-up 0.45
    {"hostname": "Watt Wind"},
    {"hostname": "-fan"},
    {"ap_password": "short"},
    {"wifi_ssid": "sneaky"},                    # only via /api/wifi
    {"hr_share": "yes"},
    {"hr_share": 1},
    {"unknown": 1},
])
def test_config_invalid(env, body):
    cfg, saved, client = env
    before = dict(cfg)
    res = post(client, "/api/config", body)
    assert res.status_code == 400
    assert cfg == before and saved == []


def test_thresholds_and_hostname(env):
    cfg, _, client = env
    res = post(client, "/api/config", {"up_thresholds": [0.5, 0.75, 0.9], "hostname": "fan-2"})
    assert res.status_code == 200
    assert cfg["up_thresholds"] == [0.5, 0.75, 0.9] and cfg["hostname"] == "fan-2"


def test_pin_required_once_set(env):
    cfg, _, client = env
    assert post(client, "/api/config", {"settings_pin": "1234"}).status_code == 200
    assert post(client, "/api/config", {"ftp": 300}).status_code == 403
    assert post(client, "/api/config", {"ftp": 300, "pin": "0000"}).status_code == 403
    assert post(client, "/api/config", {"ftp": 300, "pin": "1234"}).status_code == 200
    assert post(client, "/api/wifi", {"ssid": "home", "password": "password1"}).status_code == 403
    # fan control never needs the PIN
    assert post(client, "/api/mode", {"mode": "manual", "level": 1}).status_code == 200
    r = post(client, "/api/config", {"settings_pin": "", "pin": "1234"})       # a PIN can be changed, not removed
    assert r.status_code == 400 and cfg["settings_pin"] == "1234"
    assert post(client, "/api/config", {"settings_pin": "5678", "pin": "1234"}).status_code == 200


def test_wifi_saves_and_requests_reboot(env):
    cfg, saved, client = env
    res = post(client, "/api/wifi", {"ssid": "home", "password": "password1"})
    assert res.status_code == 200
    assert cfg["wifi_ssid"] == "home" and cfg["wifi_password"] == "password1"
    assert len(saved) == 1 and state.reboot_requested


def test_reboot_requests_reboot(env):
    _, saved, client = env
    assert post(client, "/api/reboot", {}).status_code == 200
    assert state.reboot_requested and saved == []


def test_reboot_needs_pin_when_set(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/reboot", {}).status_code == 403
    assert post(client, "/api/reboot", {"pin": "9999"}).status_code == 403
    assert not state.reboot_requested
    assert post(client, "/api/reboot", {"pin": "1234"}).status_code == 200
    assert state.reboot_requested


def test_fan_buttons_open_unless_pin_for_control(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/mode", {"mode": "manual", "level": 1}).status_code == 200
    cfg["pin_for_control"] = True
    assert post(client, "/api/mode", {"mode": "manual", "level": 2}).status_code == 403
    assert post(client, "/api/mode", {"mode": "manual", "level": 2, "pin": "9999"}).status_code == 403
    assert post(client, "/api/mode", {"mode": "manual", "level": 2, "pin": "1234"}).status_code == 200
    cfg["settings_pin"] = ""              # option on but no PIN set (e.g. after the plug-in reset): open
    assert post(client, "/api/mode", {"mode": "manual", "level": 0}).status_code == 200


def test_pin_for_control_setting(env):
    cfg, _, client = env
    r = post(client, "/api/config", {"pin_for_control": True})          # no PIN set: refused
    assert r.status_code == 400 and "settings PIN first" in r.json["error"]
    assert not cfg["pin_for_control"]
    assert post(client, "/api/config", {"pin_for_control": True, "settings_pin": "1234"}).status_code == 200
    assert cfg["pin_for_control"] is True
    assert post(client, "/api/config", {"pin_for_control": "yes", "pin": "1234"}).status_code == 400


def test_status_has_diagnostics(env):
    _, _, client = env
    s = run(client.get("/api/status")).json
    for key in ("version", "board", "reset_reason", "rssi", "hr_battery", "power_battery", "mem_free"):
        assert key in s


@pytest.mark.parametrize("body", [
    {"ssid": "home", "password": "short"},
    {"ssid": "x" * 33, "password": "password1"},
    {"password": "password1"},
])
def test_wifi_invalid(env, body):
    cfg, saved, client = env
    assert post(client, "/api/wifi", body).status_code == 400
    assert saved == [] and not state.reboot_requested


def test_scan_unavailable_without_ble(env):
    _, _, client = env
    assert run(client.get("/api/scan")).status_code == 503


def test_scan_lists_devices(monkeypatch):
    importlib.reload(state)
    devices = [{"addr": "aa:bb:cc:dd:ee:ff", "name": "Sim", "rssi": -60, "types": ["hr"], "connected": False}]

    async def fake_scan():
        return devices

    client = TestClient(web.create_app(dict(config.DEFAULTS), save=lambda c: None, scan=fake_scan))
    res = run(client.get("/api/scan"))
    assert res.status_code == 200 and res.json["devices"] == devices


@pytest.mark.parametrize("addr,ok", [
    ("aa:bb:cc:dd:ee:ff", True), ("", True),
    ("AA:BB:CC:DD:EE:FF", False), ("aa:bb:cc:dd:ee", False), ("aa-bb-cc-dd-ee-ff", False),
    ("aa:bb:cc:dd:ee:fg", False), (None, False),
])
def test_sensor_addresses(env, addr, ok):
    cfg, _, client = env
    res = post(client, "/api/config", {"hr_addr": addr, "power_addr": addr})
    assert (res.status_code == 200) == ok
    if ok:
        assert cfg["hr_addr"] == addr == cfg["power_addr"]


def test_use_setting(env):
    cfg, _, client = env
    assert post(client, "/api/config", {"use": "power"}).status_code == 200
    assert cfg["use"] == "power"
    assert post(client, "/api/config", {"use": "watts"}).status_code == 400


def test_use_names_match_fan_logic():
    import fan_logic
    assert set(web.USES) == set(fan_logic.USES)


def test_response_names_match_fan_logic():
    import fan_logic
    assert set(web.RESPONSES) == set(fan_logic.RESPONSES)


def test_wifi_test_only_from_access_point(env):
    _, saved, client = env
    state.wifi_mode = "sta"
    assert post(client, "/api/wifi/test", {"ssid": "home", "password": "password1"}).status_code == 409
    assert state.wifi_test_request is None


def test_wifi_test_requests_join_and_reports(env):
    cfg, saved, client = env
    state.wifi_mode = "ap"
    res = post(client, "/api/wifi/test", {"ssid": "home", "password": "password1"})
    assert res.status_code == 200 and res.json["state"] == "testing"
    assert state.wifi_test_request == ("home", "password1")
    assert saved == [] and cfg["wifi_ssid"] == "" and not state.reboot_requested
    assert post(client, "/api/wifi/test", {"ssid": "home", "password": "password1"}).status_code == 409
    state.wifi_test = {"state": "ok", "ssid": "home", "ip": "192.168.1.50", "error": ""}
    res = run(client.get("/api/wifi/test"))
    assert res.json["ip"] == "192.168.1.50"


@pytest.mark.parametrize("body, code", [
    ({"ssid": "", "password": "password1"}, 400),
    ({"ssid": "home", "password": "short"}, 400),
    ({"ssid": "home", "password": "password1", "pin": "0000"}, 403),
])
def test_wifi_test_invalid(env, body, code):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    if "pin" not in body:
        body = dict(body, pin="1234")
    state.wifi_mode = "ap"
    assert post(client, "/api/wifi/test", body).status_code == code
    assert state.wifi_test_request is None


@pytest.mark.parametrize("path", ["/generate_204", "/hotspot-detect.html", "/connecttest.txt"])
def test_captive_checks_redirect_to_the_page(env, path):
    _, _, client = env
    state.ip = "192.168.4.1"
    r = run(client.get(path))
    assert r.status_code == 302 and r.headers["Location"] == "http://192.168.4.1/"


def test_unknown_address_redirects_only_on_the_access_point(env):
    _, _, client = env
    state.ip = "192.168.4.1"
    state.wifi_mode = "ap"
    assert run(client.get("/some/where")).status_code == 302
    state.wifi_mode = "sta"
    assert run(client.get("/some/where")).status_code == 404


def test_max_level_setting(env):
    cfg, _, client = env
    assert post(client, "/api/config", {"max_level": 2}).status_code == 200 and cfg["max_level"] == 2
    for bad in (0, 4, "2"):
        assert post(client, "/api/config", {"max_level": bad}).status_code == 400


def test_off_timer(env):
    _, _, client = env
    state.uptime_s = 1000
    state.auto_available = True
    state.set_auto()
    assert post(client, "/api/timer", {"minutes": 30}).status_code == 409      # not in manual
    post(client, "/api/mode", {"mode": "manual", "level": 2})
    r = post(client, "/api/timer", {"minutes": 30})
    assert r.status_code == 200 and r.json["off_left_s"] == 1800 and state.off_at_s == 1000 + 1800
    post(client, "/api/mode", {"mode": "manual", "level": 3})                  # another level keeps it
    assert state.off_at_s == 2800
    assert post(client, "/api/timer", {"minutes": 0}).json["off_left_s"] is None   # cancel
    post(client, "/api/timer", {"minutes": 60})
    post(client, "/api/mode", {"mode": "auto"})                                # auto clears it
    assert state.off_at_s is None
    for bad in (-1, 1441, "30", 1.5):
        assert post(client, "/api/timer", {"minutes": bad}).status_code == 400


def test_networks_merges_sorts_and_skips_hidden():
    found = [(b"Home", b"a", 1, -70, 3, 0), (b"Home", b"b", 6, -55, 3, 0), (b"Cafe", b"c", 11, -80, 0, 0),
             (b"", b"d", 1, -40, 3, 1), (b"\x00\x00", b"e", 1, -45, 3, 1)]
    assert web.networks(found) == [{"ssid": "Home", "rssi": -55, "secure": True},
                                   {"ssid": "Cafe", "rssi": -80, "secure": False}]


def test_wifi_scan_route(env, monkeypatch):
    import sys, types
    _, _, client = env
    fake = types.ModuleType("wifi")
    fake.scan_raw = lambda: [(b"Home", b"a", 1, -60, 3, 0)]
    monkeypatch.setitem(sys.modules, "wifi", fake)
    state.wifi_mode = "sta"
    state.wifi_test = {"state": "idle", "ssid": "", "ip": "", "error": ""}
    r = run(client.get("/api/wifi/scan"))
    assert r.status_code == 200 and r.json["networks"][0]["ssid"] == "Home"
    state.wifi_mode = "connecting"
    assert run(client.get("/api/wifi/scan")).status_code == 409


def test_profiles_api(env):
    import profiles
    cfg, _, client = env
    profiles.ensure(cfg)
    r = post(client, "/api/profile", {"action": "add", "name": "Anna"})
    assert r.status_code == 200 and r.json["profile"] == 1 and len(r.json["profiles"]) == 2
    assert run(client.get("/api/status")).json["rider"] == "Anna"
    post(client, "/api/config", {"ftp": 180})                    # Anna's FTP
    post(client, "/api/profile", {"action": "select", "index": 0})
    assert cfg["ftp"] != 180 and state.rider_by_hand        # no strap-based switching after a manual choice
    post(client, "/api/profile", {"action": "select", "index": 1})
    assert cfg["ftp"] == 180
    assert post(client, "/api/profile", {"action": "select", "index": 5}).status_code == 400
    assert post(client, "/api/profile", {"action": "rename", "index": 1, "name": ""}).status_code == 400
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/profile", {"action": "delete", "index": 1}).status_code == 403
    assert post(client, "/api/profile", {"action": "select", "index": 0}).status_code == 200   # like a fan button
    assert post(client, "/api/profile", {"action": "delete", "index": 1, "pin": "1234"}).status_code == 200
    assert len(cfg["profiles"]) == 1 and run(client.get("/api/status")).json["rider"] == ""


def test_reset_groups(env):
    import profiles
    cfg, _, client = env
    profiles.ensure(cfg)
    post(client, "/api/config", {"ftp": 300, "up_thresholds": [0.4, 0.6, 0.8], "down_thresholds": [0.3, 0.5, 0.7],
                                 "idle_off_min": 30, "hostname": "myfan"})
    r = post(client, "/api/reset", {"what": "rider"})
    assert r.status_code == 200 and cfg["ftp"] == config.DEFAULTS["ftp"]
    assert cfg["up_thresholds"] == config.DEFAULTS["up_thresholds"] and cfg["profiles"][0]["ftp"] == config.DEFAULTS["ftp"]
    assert cfg["idle_off_min"] == 30 and cfg["hostname"] == "myfan"          # fan and network untouched
    post(client, "/api/reset", {"what": "fan"})
    assert cfg["idle_off_min"] == config.DEFAULTS["idle_off_min"] and cfg["hostname"] == "myfan"
    assert post(client, "/api/reset", {"what": "network"}).status_code == 400
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/reset", {"what": "fan"}).status_code == 403


def test_config_says_when_the_ap_password_is_the_default(env):
    cfg, _, client = env
    cfg["ap_password"] = config.DEFAULTS["ap_password"]
    r = run(client.get("/api/config"))
    assert r.json["ap_default"] is True and "ap_password" not in r.json
    post(client, "/api/config", {"ap_password": "my-own-secret"})
    assert run(client.get("/api/config")).json["ap_default"] is False


# ---- settings backup / restore --------------------------------------------------------------------

def test_backup_leaves_secrets_out_unless_asked(env):
    cfg, _, client = env
    cfg.update(wifi_password="secret-wifi", settings_pin="", link_key="k" * 32)
    j = post(client, "/api/backup", {}).json
    assert j["wattwind_backup"] == 1 and j["config"]["ftp"] == cfg["ftp"]
    assert "wifi_password" not in j["config"] and "link_key" not in j["config"]
    j = post(client, "/api/backup", {"secrets": True}).json
    assert j["config"]["wifi_password"] == "secret-wifi" and j["secrets"] is True


def test_restore_round_trip_and_checks(env):
    cfg, saved, client = env
    j = post(client, "/api/backup", {}).json
    j["config"]["ftp"] = 275
    j["config"]["unknown_key"] = 1                       # ignored
    r = post(client, "/api/restore", {"backup": j})
    assert r.status_code == 200 and cfg["ftp"] == 275 and "unknown_key" not in cfg and state.reboot_requested
    bad = dict(j, config=dict(j["config"], ftp=5000))
    assert post(client, "/api/restore", {"backup": bad}).status_code == 400
    assert post(client, "/api/restore", {"backup": {"hello": 1}}).status_code == 400


def test_backup_and_restore_need_the_pin(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/backup", {}).status_code == 403
    j = post(client, "/api/backup", {"pin": "1234"}).json
    assert post(client, "/api/restore", {"backup": j}).status_code == 403
    assert post(client, "/api/restore", {"backup": j, "pin": "1234"}).status_code == 200


# ---- web attack surface ------------------------------------------------------------------------

def test_dns_rebinding_foreign_names_refused(env):
    cfg, _, client = env
    state.wifi_mode, state.ip = "sta", "192.168.1.50"
    for host in ("wattwind.local", "WattWind.local", "wattwind", "wattwind.fritz.box", "192.168.1.50", "192.168.1.50:80"):
        assert run(client.get("/api/status", headers={"Host": host})).status_code == 200, host
    for host in ("evil.example", "wattwind.evil.example", "192.168.1.51"):
        assert run(client.get("/api/status", headers={"Host": host})).status_code == 421, host
    state.wifi_mode = "ap"                                   # own network: captive portal names are fine
    assert run(client.get("/api/status", headers={"Host": "captive.apple.com"})).status_code == 200


def test_csrf_needs_json_and_no_cors(env):
    cfg, _, client = env
    state.mode = "auto"
    r = run(client.post("/api/mode", body='{"mode": "manual", "level": 3}', headers={"Content-Type": "text/plain"}))
    assert r.status_code == 400 and state.mode == "auto"        # a foreign site's "simple" request does nothing
    r = run(client.post("/api/mode", body={"mode": "manual", "level": 1}))
    assert "Access-Control-Allow-Origin" not in r.headers       # never allow other sites to read or preflight


def test_pin_guessing_slows_down(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    state.uptime_s = 100
    for _ in range(2):                                          # two free mistakes
        assert post(client, "/api/reboot", {"pin": "0000"}).json["error"] == "wrong PIN"
    r = post(client, "/api/reboot", {"pin": "0000"})
    assert r.status_code == 403
    r = post(client, "/api/reboot", {"pin": "1234"})            # even the right PIN waits now
    assert r.status_code == 403 and "try again" in r.json["error"]
    state.uptime_s = 102
    assert post(client, "/api/reboot", {"pin": "1234"}).status_code == 200 and state.pin_fails == 0


def test_diagnostics_file_without_secrets(env, tmp_path, monkeypatch):
    cfg, _, client = env
    cfg.update(wifi_password="secret-wifi", settings_pin="", link_key="k" * 32, wifi_ssid="HomeWiFi")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "log.txt").write_text("up=0 START version=x reason=power on\n")
    r = run(client.get("/api/diagnostics"))
    assert r.status_code == 200
    t = r.text
    assert "WattWind diagnostics" in t and "HomeWiFi" in t and "START version=x" in t
    assert "secret-wifi" not in t and "k" * 32 not in t and "wifi_password" in t   # listed as set, value hidden


# ---- logbook events ------------------------------------------------------------------------------

@pytest.fixture
def events(monkeypatch):
    import logbook
    lines = []
    monkeypatch.setattr(logbook, "write", lines.append)
    return lines


def test_logbook_events_for_buttons_settings_and_links(env, events):
    cfg, _, client = env
    state.uptime_s = 42
    post(client, "/api/mode", {"mode": "manual", "level": 2})
    post(client, "/api/config", {"ftp": 260})
    post(client, "/api/config", {"ftp": 260})                    # nothing changed: no line
    post(client, "/api/link/pair", {})
    post(client, "/api/link/unpair", {})
    assert events[0] == "up=42 button: level 2"
    assert events[1] == "up=42 settings saved: ftp"
    assert events[2].startswith("up=42 linked fans: pairing opened")
    assert events[3] == "up=42 linked fans: all followers unpaired (new key)"
    assert len(events) == 4
    assert not any("260" in e for e in events)                    # names only, never values


def test_logbook_security_events_are_rate_limited(env, events):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    state.wifi_mode, state.ip = "sta", "192.168.1.50"
    for i in range(25):
        state.uptime_s = 1000 * i                                  # past every wait
        post(client, "/api/reboot", {"pin": "0000"})
    pins = [e for e in events if "wrong PIN" in e]
    assert [e.split("(")[1] for e in pins] == ["1 in a row)", "3 in a row)", "10 in a row)", "20 in a row)"]
    for _ in range(12):
        run(client.get("/api/status", headers={"Host": "evil.example"}))
    hosts = [e for e in events if "refused a request" in e]
    assert len(hosts) == 2 and "evil.example" in hosts[0]


# ---- EN 303 645: private reads need the PIN, erase everything ----------------------------------

def test_logbook_and_diagnostics_need_the_pin_when_set(env, tmp_path, monkeypatch):
    cfg, _, client = env
    monkeypatch.chdir(tmp_path)
    (tmp_path / "log.txt").write_text("up=0 START\n")
    assert run(client.get("/api/log")).status_code == 200            # no PIN set: open
    cfg["settings_pin"] = "1234"
    for path in ("/api/log", "/api/log?old=1", "/api/diagnostics"):
        r = run(client.get(path))
        assert r.status_code == 403 and r.json["error"] == "PIN needed", path
        assert state.pin_fails == 0                                   # asking isn't guessing
    assert run(client.get("/api/log", headers={"X-Pin": "0000"})).status_code == 403
    assert state.pin_fails == 1
    r = run(client.get("/api/log", headers={"X-Pin": "1234"}))
    assert r.status_code == 200 and "START" in r.text
    assert run(client.get("/api/diagnostics", headers={"X-Pin": "1234"})).status_code == 200
    assert run(client.get("/api/status")).status_code == 200         # status stays open (it drives the page)


def test_erase_everything(env):
    cfg, _, client = env
    cfg["settings_pin"] = "1234"
    assert post(client, "/api/erase", {"confirm": "erase"}).status_code == 403
    assert post(client, "/api/erase", {"pin": "1234"}).status_code == 400            # needs the confirmation
    assert not state.reboot_requested
    r = post(client, "/api/erase", {"pin": "1234", "confirm": "erase"})
    assert r.status_code == 200 and state.erase_requested and state.reboot_requested


def test_page_warns_without_pin(env):
    cfg, _, client = env
    assert run(client.get("/api/config")).json["pin_set"] is False
    page = run(client.get("/")).text
    assert 'id="nopin"' in page and "eraseAll()" in page and "X-Pin" in page


# ---- first setup: own access point password and a PIN (EN 303 645 5.1-1, 5.5-5) ------------------

@pytest.mark.setup_gate
def test_first_setup_gate(env):
    cfg, saved, client = env
    assert run(client.get("/api/status")).json["setup"] is True                      # defaults: setup needed
    for path, body in (("/api/config", {"ftp": 250}), ("/api/wifi", {"ssid": "home", "password": "password1"}),
                       ("/api/backup", {}), ("/api/link/pair", {}), ("/api/reset", {"what": "fan"}),
                       ("/api/profile", {"action": "add", "name": "Sam"})):
        r = post(client, path, body)
        assert r.status_code == 409 and r.json["setup"] is True, path
    # still open: the fan buttons and reboot (choosing a rider too: only "select" passes the gate)
    assert post(client, "/api/mode", {"mode": "manual", "level": 2}).status_code == 200
    assert post(client, "/api/reboot", {}).status_code == 200


@pytest.mark.setup_gate
@pytest.mark.parametrize("body, error", [
    ({"ap_password": "wattwind", "new_pin": "1234"}, "not the default"),
    ({"ap_password": "short", "new_pin": "1234"}, "8 to 63"),
    ({"ap_password": "my-own-pass", "new_pin": "12"}, "4 to 16"),
    ({"ap_password": "my-own-pass"}, "4 to 16"),                                     # no PIN yet: one is needed
])
def test_first_setup_refuses(env, body, error):
    cfg, saved, client = env
    r = post(client, "/api/setup", body)
    assert r.status_code == 400 and error in r.json["error"] and not saved


@pytest.mark.setup_gate
def test_first_setup_done(env):
    cfg, saved, client = env
    r = post(client, "/api/setup", {"ap_password": "my-own-pass", "new_pin": "2468"})
    assert r.status_code == 200 and r.json["pin_set"] and not r.json["ap_default"]
    assert cfg["ap_password"] == "my-own-pass" and cfg["settings_pin"] == "2468" and saved
    assert run(client.get("/api/status")).json["setup"] is False
    assert post(client, "/api/config", {"ftp": 250}).status_code == 403                # now the PIN is needed
    assert post(client, "/api/config", {"ftp": 250, "pin": "2468"}).status_code == 200
    assert post(client, "/api/setup", {"ap_password": "other-pass", "new_pin": "1111"}).status_code == 409
    r = post(client, "/api/config", {"ap_password": "wattwind", "pin": "2468"})          # never back to the default
    assert r.status_code == 400 and cfg["ap_password"] == "my-own-pass"


@pytest.mark.setup_gate
def test_first_setup_keeps_an_existing_pin(env):
    cfg, saved, client = env
    cfg["settings_pin"] = "1357"                         # an older fan: PIN set, default access point password
    assert post(client, "/api/setup", {"ap_password": "my-own-pass"}).status_code == 403
    r = post(client, "/api/setup", {"ap_password": "my-own-pass", "pin": "1357"})
    assert r.status_code == 200 and cfg["settings_pin"] == "1357"


def test_restore_checks_remembered_straps(env):
    cfg, _, client = env
    good = web.restore_settings(cfg, {"hr_rr": ["d8:66:77:88:99:aa"]})
    assert good["hr_rr"] == ["d8:66:77:88:99:aa"]
    for bad in ("x", ["nope"], ["c4:11:22:33:44:55"] * 9):
        with pytest.raises(ValueError):
            web.restore_settings(cfg, {"hr_rr": bad})


# ---- detailed recording (detail.py) ------------------------------------------------------------

def test_detailed_recording_start_download_stop_delete(env, events, tmp_path, monkeypatch):
    import detail
    cfg, _, client = env
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(detail, "_rec", None)                  # a fresh recorder in this folder
    cfg["settings_pin"] = "1234"
    assert run(client.get("/api/status")).json["detail"] is None
    assert post(client, "/api/detail", {"action": "start"}).status_code == 403
    assert run(client.get("/api/detail")).status_code == 403
    r = post(client, "/api/detail", {"action": "start", "pin": "1234"})
    assert r.status_code == 200 and r.json["detail"]["on"]
    state.power, state.level, state.target_level = 180, 1, 1
    detail.rec().second(1, state, cfg)
    t = run(client.get("/api/detail", headers={"X-Pin": "1234"})).text
    assert "recording started" in t and "1 R 180" in t
    assert post(client, "/api/detail", {"action": "stop", "pin": "1234"}).json["detail"]["on"] is False
    assert "keep_s" in run(client.get("/api/status")).json["detail"]
    assert post(client, "/api/detail", {"action": "delete", "pin": "1234"}).json["detail"] is None
    assert "(no recording)" in run(client.get("/api/detail", headers={"X-Pin": "1234"})).text
    assert post(client, "/api/detail", {"action": "nonsense", "pin": "1234"}).status_code == 400
    log = " ".join(events)
    assert "detailed recording started" in log and "detailed recording deleted" in log


def test_safe_start_refuses_setting_changes(env):
    cfg, saved, client = env
    state.safe_start = True
    r = post(client, "/api/config", {"ftp": 250})
    assert r.status_code == 409 and r.json["safe"] and r.json["error"].startswith("Safe start")
    assert post(client, "/api/mode", {"mode": "manual", "level": 1}).status_code == 200   # the fan buttons work
    assert run(client.get("/api/status")).json["safe_start"] is True
    assert saved == []


def test_stalled_connections_are_closed_so_the_page_stays_reachable(monkeypatch):
    """Found 2026-11-01: half-sent requests from a suspended phone held the Pico's few sockets, so the page couldn't
    be opened. web.FanApp gives every request REQUEST_READ_S; here 0.3 s, over real sockets."""
    import socket
    importlib.reload(state)
    monkeypatch.setattr(web, "REQUEST_READ_S", 0.3)
    app = web.create_app(dict(config.DEFAULTS), save=lambda c: None)
    s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); port = s0.getsockname()[1]; s0.close()

    async def scenario():
        server = asyncio.ensure_future(app.start_server(host="127.0.0.1", port=port))
        await asyncio.sleep(0.2)
        stalled = []
        for _ in range(6):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n")      # never finished
            await w.drain()
            stalled.append((r, w))
        await asyncio.sleep(0.8)
        closed = [await asyncio.wait_for(r.read(), 1) == b"" for r, _ in stalled]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await w.drain()
        answer = await asyncio.wait_for(r.read(), 2)
        app.shutdown()
        await asyncio.wait_for(server, 2)
        return closed, answer
    closed, answer = asyncio.run(scenario())
    assert all(closed)                                              # every stalled connection was dropped
    assert answer.startswith(b"HTTP/1.0 200") or answer.startswith(b"HTTP/1.1 200")
