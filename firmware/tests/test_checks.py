"""checks.sanitize: every saved value is checked at start like the page checks a new one; a bad one goes back to its
default, so a value saved by an older version or damaged on the flash can't stop the fan."""
import copy

import pytest

import checks
import config
import profiles


def fresh():
    c = copy.deepcopy(config.DEFAULTS)
    profiles.ensure(c)
    return c


def test_valid_settings_stay_as_they_are():
    c = fresh()
    c.update(ftp=240, hr_max=180, use="power", hostname="wattwind2")
    profiles.sync(c)
    before = copy.deepcopy(c)
    assert checks.sanitize(c) == []
    assert c == before


def test_a_bad_value_goes_back_to_its_default():
    c = fresh()
    c["ftp"], c["response"], c["hostname"] = "240", "turbo", "-bad-"
    fixed = checks.sanitize(c)
    assert set(fixed) >= {"ftp", "response", "hostname"}
    assert c["ftp"] == 200 and c["response"] == "normal" and c["hostname"] == "wattwind"
    assert c["profiles"][0]["ftp"] == 200                    # the active rider mirrored again


def test_pairs_that_dont_fit_together_both_go_back():
    c = fresh()
    c["hr_rest"], c["hr_max"] = 110, 105                     # each in range, together impossible
    c["up_thresholds"], c["down_thresholds"] = [0.45, 0.7, 0.88], [0.5, 0.63, 0.81]   # down above up at level 1
    fixed = checks.sanitize(c)
    assert (c["hr_rest"], c["hr_max"]) == (60, 190)
    assert c["down_thresholds"] == [0.38, 0.63, 0.81] and "step levels" in fixed


def test_riders_are_checked_too():
    c = fresh()
    c["profiles"].append({"name": "", "ftp": 5000, "hr_max": 180, "hr_rest": 50, "use": "both", "response": "quick",
                          "up_thresholds": [0.5, 0.75, 0.9], "down_thresholds": [0.43, 0.68, 0.83], "hr_addr": "zz"})
    fixed = checks.sanitize(c)
    p = c["profiles"][1]
    assert p["name"] == "Rider 2" and p["ftp"] == 200 and p["hr_addr"] == "" and p["response"] == "quick"
    assert "rider name" in fixed and any("Rider 2: ftp" in f for f in fixed)


def test_selected_rider_out_of_range_and_broken_rider_list():
    c = fresh()
    c["profile"] = 7
    assert "selected rider" in checks.sanitize(c) and c["profile"] == 0
    c = fresh()
    c["profiles"] = "nonsense"
    assert "riders" in checks.sanitize(c)
    assert isinstance(c["profiles"], list) and c["profiles"][0]["name"] == "Rider 1"


def test_fan_buttons_pin_without_a_pin():
    c = fresh()
    c["pin_for_control"] = True
    assert "pin_for_control" in checks.sanitize(c) and c["pin_for_control"] is False


def test_strings_lists_and_link_settings():
    c = fresh()
    c["wifi_ssid"], c["hr_rr"], c["follow_mode"], c["follow_offset"] = 42, ["not an address"], "x", 5
    fixed = checks.sanitize(c)
    assert c["wifi_ssid"] == "" and c["hr_rr"] == [] and c["follow_mode"] == "same" and c["follow_offset"] == 0
    assert {"wifi_ssid", "hr_rr", "follow_mode", "follow_offset"} <= set(fixed)


def test_never_raises_on_garbage():
    for junk in ({}, {"profiles": [None, 3]}, {"ftp": None, "up_thresholds": "x", "profile": "a"},
                 {"hr_rest": "a", "hr_max": [1]}):
        c = fresh()
        c.update(junk)
        checks.sanitize(c)                                    # no exception, whatever is in the file
        assert isinstance(c["ftp"], int) and isinstance(c["profiles"], list)


def test_hr_share_kept_or_reset():
    c = fresh()
    c["hr_share"] = True
    assert checks.sanitize(c) == [] and c["hr_share"] is True
    c["hr_share"] = "on"
    assert "hr_share" in checks.sanitize(c) and c["hr_share"] is False


def test_hr_share_restored_from_a_backup():
    import config
    assert checks.restore_settings(dict(config.DEFAULTS), {"hr_share": True}) == {"hr_share": True}
    with pytest.raises(ValueError):
        checks.restore_settings(dict(config.DEFAULTS), {"hr_share": "yes"})
