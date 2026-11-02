"""User settings. Defaults are below; config.json overrides them (created on first boot).

Wiring (GPIO numbers) is fixed in code, not here: see relay.py.
"""

import json
import os

import profiles

PATH = "config.json"
damaged = False                  # load() found config.json unreadable and started from defaults (main.py tells the page)
read_only = False                # safe start (main.py): the settings in memory are defaults; never write them over the saved ones
_replace = getattr(os, "replace", None) or os.rename   # MicroPython has only rename (LittleFS replaces)

DEFAULTS = {
    # Wi-Fi
    "hostname": "wattwind",      # http://wattwind.local
    "wifi_ssid": "",
    "wifi_password": "",
    "ap_password": "wattwind",   # password of the WattWind-XXXX access point (8+ chars)
    "settings_pin": "",
    "pin_for_control": False,    # True: the fan buttons need the PIN too (if one is set)          # if set, needed to change settings

    # Rider
    "ftp": 200,                  # defaults: a typical 30-year-old recreational rider (~2.7 W/kg at 75 kg)
    "hr_max": 190,               # 220 - age
    "hr_rest": 60,               # resting heart rate of an averagely fit adult

    # Auto mode
    "up_thresholds": [0.45, 0.70, 0.88],    # demand to step up into level 1, 2, 3
    "down_thresholds": [0.38, 0.63, 0.81],  # demand below which level 1, 2, 3 steps down
    "dwell_up_s": 15,
    "dwell_down_s": 60,
    "use": "both",               # what decides in Auto: "both" (the higher score), "power" or "hr" (fan_logic.USES)
    "response": "normal",        # fan response: "calm", "normal" or "quick" (fan_logic.RESPONSES)

    # Timeouts
    "manual_timeout_min": 480,   # manual -> auto after N minutes (0 = never): 8 h covers ordinary-fan use; a forgotten fan ends in auto
    "idle_off_min": 15,          # fan off after N minutes without pedaling
    "max_level": 3,              # highest level auto may choose (1-3): e.g. 2 at night; manual is not limited

    # BLE sensors ("" = use the first one found and save it)
    "hr_addr": "",
    "power_addr": "",
    "hr_rr": [],                 # heart-rate sensors that send beat times (ble_parse.HrContact), remembered
    "hr_share": False,           # pass the strap's heart rate on as a Bluetooth heart-rate sensor (ble_share.py)

    # Linked fans (link.py): this fan's key as a leader; the leader it follows ("" = uses its own sensors)
    "link_key": "",              # created on first start; handed to followers while pairing is open
    "follow_id": "",
    "follow_name": "",
    "follow_key": "",
    "follow_mode": "same",       # "same" (leader's level) or "own" (leader's sensor data, own settings)
    "follow_offset": 0,          # same level: 1, 0, -1 or -2 (leader off = off)
}


def load(path=PATH):
    global damaged
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError("not a settings object")
        cfg.update(saved)
    except OSError:              # no config.json yet: create it
        save(cfg, path)
    except ValueError:           # damaged file: keep a copy, start from defaults (the fan must start)
        damaged = True
        try:
            _replace(path, path + ".bad")
        except OSError:
            pass
        save(cfg, path)
    profiles.ensure(cfg)         # rider profiles (profiles.py); an older config gets "Rider 1" from its values
    return cfg


def save(cfg, path=PATH):
    """Write to a temporary file, then rename: a power cut while saving leaves the old file."""
    if read_only:
        print("config: safe start, settings not saved")
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    _replace(tmp, path)
