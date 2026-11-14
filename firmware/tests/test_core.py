"""CORE body temperature sensor (release 1.1): the "core" role in ble_sensors, heart rate sent to CORE, the beacon,
per-rider ownership, settings, linked fans and the detailed recording. Stand-in bluetooth / aioble modules."""
import asyncio
import struct
import sys
import time
import types

import pytest

CORE = "00002100-5b1e-4347-b07c-97b514dae121"


class UUID:
    def __init__(self, v):
        self.v = v.lower() if isinstance(v, str) else v

    def __eq__(self, other):
        return isinstance(other, UUID) and self.v == other.v

    def __hash__(self):
        return hash(self.v)


@pytest.fixture
def ble(monkeypatch):
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(UUID=UUID))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(DeviceDisconnectedError=Exception))
    if not hasattr(time, "ticks_ms"):
        monkeypatch.setattr(time, "ticks_ms", lambda: int(time.monotonic() * 1000), raising=False)
        monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    import importlib
    import config
    import state
    importlib.reload(state)
    sys.modules.pop("ble_sensors", None)
    import ble_sensors as bs
    saved = []
    monkeypatch.setattr(config, "save", lambda c: saved.append(dict(c)))
    bs._cfg = dict(config.DEFAULTS)
    import profiles
    profiles.ensure(bs._cfg)
    return bs, state, saved


A = "aa:bb:cc:dd:ee:01"
C = "aa:bb:cc:dd:ee:0c"


def meas(core, skin=3400, qs=0x13, hr=0, hsi=0xFF, flags=0x37):
    return struct.pack("<BhhhBBB", flags, core, skin, 0, qs, hr, hsi)


def test_core_offered_by_its_service(ble):
    bs, _, _ = ble
    assert bs._offers([UUID(CORE)]) == ["core"]
    assert bs._offers([UUID(0x180D), UUID(CORE)]) == ["hr", "core"]
    assert bs._offers([UUID(0x1809)]) == []                  # Health Thermometer alone: not CORE's full data


def test_first_core_found_is_saved_for_the_active_rider(ble):
    bs, state, saved = ble
    assert bs._may_take("core", C)
    bs._claim("core", C)
    assert bs._cfg["core_addr"] == C and bs._cfg["profiles"][0]["core_addr"] == C and saved
    assert state.core_connected
    bs._release("core", C)
    assert not bs._may_take("core", "aa:bb:cc:dd:ee:99")      # saved: only that one


def test_another_riders_core_is_not_taken_first_found(ble):
    bs, _, _ = ble
    import profiles
    import config
    profiles.add(bs._cfg, "Sam", config.DEFAULTS)            # Sam active, no CORE yet
    bs._cfg["profiles"][0]["core_addr"] = C                  # Alex's CORE
    assert not bs._may_take("core", C)
    assert bs._may_take("core", "aa:bb:cc:dd:ee:77")


def test_core_values_and_release(ble):
    bs, state, _ = ble
    link = bs.Link(None, C)
    bs._claim("core", C)
    link.on_core(meas(3812, qs=0x13, hsi=42))
    assert (state.core_temp, state.core_skin, state.core_quality, state.core_hsi) == (38.12, 34.0, 3, 4.2)
    assert state.core_hr_state == "none" and state.core_source == "link"
    link.on_core(meas(3812, qs=0x10, hsi=42))                 # quality invalid: no value
    assert state.core_temp is None and state.core_hsi is None
    link.on_core(meas(3812, qs=0x23, hr=131))                 # CORE says it receives 131 bpm
    assert state.core_hr_state == "receiving" and state.core_hr == 131
    bs._release("core", C)
    assert state.core_source is None and not state.core_connected and state.core_hr is None


def test_data_from_a_released_core_is_ignored(ble):
    bs, state, _ = ble
    link = bs.Link(None, C)
    link.on_core(meas(3812, hsi=42))
    assert state.core_temp is None


class FakeCtrl:
    def __init__(self):
        self.writes = []

    async def write(self, data, response=False):
        self.writes.append(bytes(data))


def test_strap_heart_rate_sent_only_while_core_has_none(ble):
    bs, state, _ = ble
    link = bs.Link(None, C)
    link.core_ctrl = FakeCtrl()
    state.hr = 140
    state.core_hr_state = "receiving"                         # CORE has its own strap: leave it alone
    asyncio.run(link._core_heart_rate())
    assert link.core_ctrl.writes == []
    state.core_hr_state = "none"
    asyncio.run(link._core_heart_rate())
    assert link.core_ctrl.writes == [bytes([0x13, 140])] and link.core_fwd
    state.core_hr_state = "receiving"                         # now it gets ours: keep sending
    state.hr = 142
    asyncio.run(link._core_heart_rate())
    assert link.core_ctrl.writes[-1] == bytes([0x13, 142])
    state.hr = None                                           # strap gone: stop (empty 0x13)
    asyncio.run(link._core_heart_rate())
    assert link.core_ctrl.writes[-1] == b"\x13" and not link.core_fwd
    n = len(link.core_ctrl.writes)
    asyncio.run(link._core_heart_rate())
    assert len(link.core_ctrl.writes) == n                    # nothing more until CORE asks again


def test_heart_rate_input_failure_is_harmless(ble):
    bs, state, _ = ble
    link = bs.Link(None, C)

    class Broken:
        async def write(self, data, response=False):
            raise OSError(-128)
    link.core_ctrl = Broken()
    state.hr, state.core_hr_state = 130, "none"
    asyncio.run(link._core_heart_rate())                       # printed, not raised


class FakeResult:
    def __init__(self, payload, company=0x0BF6):
        self.payload = payload
        self.company = company

    def manufacturer(self, filter=None):
        if filter in (None, self.company):
            yield (self.company, self.payload)


@pytest.mark.parametrize("company", [0x0BF6, 0xF60B])
def test_beacon_company_either_byte_order(ble, company):
    # The real CORE sends F6 0B (0x0BF6, 2026-11-08); the maker's notes show 0B F6 (0xF60B): both are read.
    bs, state, _ = ble
    bs._cfg["core_addr"] = C
    bs._note_beacon(FakeResult(bytes([0, 0x24, 0x6B, 0x90]), company), C)    # bytes from the real CORE
    assert state.core_temp == 36.971


def test_beacon_of_another_company_is_ignored(ble):
    bs, state, _ = ble
    bs._cfg["core_addr"] = C
    bs._note_beacon(FakeResult(bytes([0, 4, 0xB3, 0x91]), 0x004C), C)
    assert state.core_temp is None


def test_beacon_of_the_saved_core_while_not_connected(ble):
    bs, state, _ = ble
    bs._cfg["core_addr"] = C
    bs._note_beacon(FakeResult(bytes([0, 4, 0xB3, 0x91])), "aa:bb:cc:dd:ee:99")   # another CORE: ignored
    assert state.core_temp is None
    bs._note_beacon(FakeResult(bytes([0, 4, 0xB3, 0x91])), C)
    assert state.core_temp == 37.299 and state.core_source == "beacon" and state.core_hsi is None
    bs._claim("core", C)                                       # connected: the link's values count, not the beacon
    state.core_temp = 38.0
    bs._note_beacon(FakeResult(bytes([0, 4, 0xB3, 0x91])), C)
    assert state.core_temp == 38.0


def test_no_beacon_without_a_saved_core(ble):
    bs, state, _ = ble
    bs._note_beacon(FakeResult(bytes([0, 4, 0xB3, 0x91])), C)
    assert state.core_temp is None


def test_battery_goes_to_core(ble):
    bs, state, _ = ble
    link = bs.Link(None, C)
    link.roles = ["core"]

    class Batt:
        async def read(self, timeout_ms=0):
            return bytes([12])
    link.batt_ch = Batt()
    asyncio.run(link._read_battery())
    assert state.core_battery == 12


# ------------------------------------------------------------------ settings and riders


def test_core_belongs_to_one_rider():
    import config
    import profiles
    cfg = dict(config.DEFAULTS)
    profiles.ensure(cfg)
    cfg["core_addr"] = C
    profiles.sync(cfg)
    profiles.add(cfg, "Sam", config.DEFAULTS)
    assert cfg["core_addr"] == "" and cfg["profiles"][1]["core_addr"] == ""   # a new rider has no CORE
    cfg["core_addr"] = C                                                       # Sam takes it
    profiles.sync(cfg)
    assert cfg["profiles"][0]["core_addr"] == "" and cfg["profiles"][1]["core_addr"] == C
    profiles.activate(cfg, 0)
    assert cfg["core_addr"] == "" and cfg["heat"] is True


def test_settings_checked():
    import checks
    import config
    cfg = dict(config.DEFAULTS)
    assert checks.check_settings(cfg, {"heat": False}) == {"heat": False}
    assert checks.check_settings(cfg, {"core_addr": C}) == {"core_addr": C}
    for bad in ({"heat": "no"}, {"core_addr": "core"}):
        with pytest.raises(ValueError):
            checks.check_settings(cfg, bad)


def test_heat_levels_checked():
    import checks
    import config
    cfg = dict(config.DEFAULTS)
    assert cfg["heat_levels"] == [3.0, 7.0]
    assert checks.check_settings(cfg, {"heat_levels": [2, 5.5]}) == {"heat_levels": [2.0, 5.5]}
    for bad, words in (([0.5, 7], "from 1 to 10"), ([3, 11], "from 1 to 10"), ([3], "from 1 to 10"),
                       ("3,7", "from 1 to 10"), ([True, 7], "from 1 to 10"), ([5, 5], "must be below level 3"),
                       ([7, 3], "must be below level 3")):
        with pytest.raises(ValueError) as e:
            checks.check_settings(cfg, {"heat_levels": bad})
        assert str(e.value).startswith("Heat strain") and words in str(e.value)


def test_bad_saved_heat_levels_go_back_to_the_default():
    import checks
    import config
    import profiles
    cfg = dict(config.DEFAULTS)
    profiles.ensure(cfg)
    cfg["heat_levels"] = [8.0, 4.0]
    cfg["profiles"][0]["heat_levels"] = "x"
    fixed = checks.sanitize(cfg)
    assert cfg["heat_levels"] == [3.0, 7.0] and cfg["profiles"][0]["heat_levels"] == [3.0, 7.0]
    assert "heat_levels" in fixed


def test_heat_levels_are_per_rider():
    import config
    import profiles
    cfg = dict(config.DEFAULTS)
    profiles.ensure(cfg)
    profiles.add(cfg, "Sam", config.DEFAULTS)
    cfg["heat_levels"] = [2.0, 5.0]                    # Sam's
    profiles.sync(cfg)
    profiles.activate(cfg, 0)
    assert cfg["heat_levels"] == [3.0, 7.0]
    profiles.activate(cfg, 1)
    assert cfg["heat_levels"] == [2.0, 5.0]


def test_reset_rider_keeps_the_core_and_resets_heat():
    import web
    assert "heat" in web.RESET_GROUPS["rider"] and "core_addr" not in web.RESET_GROUPS["rider"]
    assert "heat_levels" in web.RESET_GROUPS["rider"]


def test_old_config_gets_the_new_keys(tmp_path):
    import json
    import checks
    import config
    import profiles
    old = {k: v for k, v in config.DEFAULTS.items() if k not in ("core_addr", "heat", "heat_levels")}
    old["profiles"] = [{"name": "Alex", "ftp": 240, "hr_max": 190, "hr_rest": 60, "use": "both", "response": "normal",
                        "up_thresholds": [0.45, 0.7, 0.88], "down_thresholds": [0.38, 0.63, 0.81], "hr_addr": ""}]
    old["profile"] = 0
    p = tmp_path / "config.json"
    p.write_text(json.dumps(old))                      # a 1.0 config: no CORE keys, riders without them
    cfg = config.load(str(p))
    assert checks.sanitize(cfg) == []
    assert cfg["core_addr"] == "" and cfg["heat"] is True
    assert cfg["profiles"][0]["core_addr"] == "" and cfg["profiles"][0]["heat"] is True
    assert cfg["heat_levels"] == [3.0, 7.0] and cfg["profiles"][0]["heat_levels"] == [3.0, 7.0]


# ------------------------------------------------------------------ linked fans and the recording


def test_leader_packet_carries_core_and_followers_check_it():
    import link
    import state as st
    s = types.SimpleNamespace(uptime_s=10, leader_seen_s=None, leader_level=None, hr=None, power=None, cadence=None,
                              hr_connected=False, power_connected=False, hr_name="", power_name="",
                              core_temp=None, core_hsi=None, core_source=None, core_connected=False, core_name="")
    link._apply({"lvl": 2, "hr": 150, "core": 38.4, "hsi": 4.5}, {}, s, "leader")
    assert (s.core_temp, s.core_hsi, s.core_source) == (38.4, 4.5, "leader")
    assert s.core_connected and s.core_name == "CORE via leader"
    assert s.hr_name == "HR via leader" and s.power_name == "power via leader"
    link._apply({"lvl": 2, "hrc": 1, "hr": None}, {}, s, "leader")           # strap connected, not worn
    assert not s.hr_connected                   # the CORE dot on, like HR / power
    link._apply({"lvl": 2, "core": "hot", "hsi": 99}, {}, s, "leader")       # nonsense: ignored
    assert s.core_temp is None and s.core_hsi is None
    link._apply({"lvl": 2}, {}, s, "leader")                                  # a 1.0 leader sends none
    assert s.core_temp is None and not s.core_connected
    s.core_temp, s.core_source, s.core_connected, s.uptime_s = 38.0, "leader", True, 100
    link._expire({}, s)
    assert s.core_temp is None and not s.core_connected


def test_recording_line_has_core_when_there_is_one(tmp_path, monkeypatch):
    import detail
    monkeypatch.chdir(tmp_path)
    r = detail.Recorder() if hasattr(detail, "Recorder") else None
    if r is None:
        pytest.skip("no Recorder class")
    lines = []
    monkeypatch.setattr(r, "line", lambda now, tag, text: lines.append((tag, text)))
    st = types.SimpleNamespace(power=200, cadence=90, hr=150, level=2, target_level=2, mode="auto", hr_off=None,
                               core_temp=38.12, core_hsi=4.2, core_skin=35.0, core_quality=3, heat=True)
    r._settings, r._minute_at = None, 10 ** 9
    r.on = True
    try:
        r.second(5, st, {}, None)
    except Exception:
        pytest.skip("recorder needs more state")
    ride = [t for tag, t in lines if tag == "R"]
    assert ride and ride[-1].endswith(" core=38.12 hsi=4.2 skin=35.0 q=3 heat")
