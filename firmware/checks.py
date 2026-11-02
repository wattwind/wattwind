"""Setting checks: one place for the rules a setting must meet. Used by the web page (POST /api/config, restore)
and at every start (sanitize: a value saved by an older version, or damaged on the flash, must not be able to
stop the fan). Pure Python: host-tested (tests/test_web.py, tests/test_checks.py).
"""
import config
import profiles

# Settings that POST /api/config may change: key -> (type, min, max, name on the page for error messages)
NUMBERS = {
    "ftp": (int, 50, 1000, "FTP (W)"),
    "hr_max": (int, 100, 230, "HR max (bpm)"),
    "hr_rest": (int, 30, 120, "HR rest (bpm)"),
    "dwell_up_s": (int, 0, 600, "Min. time before step up (s)"),
    "dwell_down_s": (int, 0, 600, "Min. time before step down (s)"),
    "manual_timeout_min": (int, 0, 1440, "Manual → auto after (min)"),   # up to 24 h; 0 = never
    "idle_off_min": (int, 1, 600, "Auto: off after no pedaling (min)"),
    "max_level": (int, 1, 3, "Auto: highest level"),
}
THRESHOLDS = ("up_thresholds", "down_thresholds")

HOSTNAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-"
SENSOR_ADDRS = ("hr_addr", "power_addr")

RESPONSES = ("calm", "normal", "quick")      # keys of fan_logic.RESPONSES
USES = ("both", "power", "hr")               # fan_logic.USES: what decides in Auto
HEX = "0123456789abcdef"


def is_ble_addr(value):
    """'' (pick the first sensor found) or 'aa:bb:cc:dd:ee:ff' (lower case, as aioble writes it)."""
    if value == "":
        return True
    return (isinstance(value, str) and len(value) == 17
            and all(value[i] == ":" if i % 3 == 2 else value[i] in HEX for i in range(17)))

BACKUP_KEYS = tuple(k for k in config.DEFAULTS) + ("profiles", "profile")
CHECKED = tuple(NUMBERS) + THRESHOLDS + ("response", "use", "hostname", "ap_password", "pin_for_control",
                                         "settings_pin", "hr_share") + SENSOR_ADDRS

def restore_settings(cfg, b):
    """Values from a backup -> the ones to apply. Unknown keys are ignored; a bad value raises ValueError."""
    new = {k: v for k, v in b.items() if k in BACKUP_KEYS}
    check_settings(cfg, {k: v for k, v in new.items() if k in CHECKED})
    if "hr_rr" in new and (not isinstance(new["hr_rr"], list) or len(new["hr_rr"]) > 8
                           or not all(isinstance(a, str) and is_ble_addr(a) and a for a in new["hr_rr"])):
        raise ValueError("hr_rr")
    for k in ("wifi_ssid", "wifi_password", "link_key", "follow_id", "follow_name", "follow_key"):
        if k in new and (not isinstance(new[k], str) or len(new[k]) > 64):
            raise ValueError(k)
    import link
    if "follow_mode" in new and new["follow_mode"] not in link.MODES:
        raise ValueError("follow_mode")
    if "follow_offset" in new and new["follow_offset"] not in link.OFFSETS:
        raise ValueError("follow_offset")
    ps = new.get("profiles")
    if ps is not None:
        if not isinstance(ps, list) or not 1 <= len(ps) <= profiles.MAX:
            raise ValueError("riders")
        for p in ps:
            if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"]:
                raise ValueError("riders")
            check_settings(cfg, {k: v for k, v in p.items() if k in CHECKED})
    if "profile" in new and (not _is_int(new["profile"]) or not 0 <= new["profile"] < len(ps or cfg["profiles"])):
        raise ValueError("selected rider")
    return new

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float))) and not isinstance(v, bool)

def check_settings(cfg, data):
    """Validate a settings update. Returns the changed values; raises ValueError."""
    new = {}
    for key, value in data.items():
        if key == "pin":
            continue
        new[key] = _check_one(key, value)
    return _check_together(cfg, new)


def _check_one(key, value):
    """One setting on its own: the value to store (thresholds as floats), or ValueError with the message for the page."""
    if key in NUMBERS:
        typ, lo, hi, name = NUMBERS[key]
        if not _is_int(value) or not lo <= value <= hi:
            raise ValueError("{}: a whole number from {} to {}".format(name, lo, hi))
    elif key in THRESHOLDS:
        if (not isinstance(value, list) or len(value) != 3
                or not all(_is_number(x) and 0 < x <= 2 for x in value)):
            raise ValueError("Step {}: each value must be a number above 0 and at most 2".format(
                "up" if key == "up_thresholds" else "down"))
        value = [float(x) for x in value]
    elif key == "use":
        if value not in USES:
            raise ValueError("Decide by: both, power or hr")
    elif key == "response":
        if value not in RESPONSES:
            raise ValueError("Fan response: Calm, Normal or Quick")
    elif key == "hostname":
        if (not isinstance(value, str) or not 1 <= len(value) <= 32
                or any(c not in HOSTNAME_CHARS for c in value)
                or value[0] == "-" or value[-1] == "-"):
            raise ValueError("Hostname: 1 to 32 characters, only a-z, 0-9 and - (no - at the start or end)")
    elif key == "ap_password":
        if not isinstance(value, str) or not 8 <= len(value) <= 63:
            raise ValueError("Access point password: 8 to 63 characters")
    elif key in SENSOR_ADDRS:
        if not is_ble_addr(value):
            raise ValueError("Sensor address: aa:bb:cc:dd:ee:ff, or empty for the first one found")
    elif key == "pin_for_control":
        if not isinstance(value, bool):
            raise ValueError("Fan buttons need the PIN: true or false")
    elif key == "hr_share":
        if not isinstance(value, bool):
            raise ValueError("Share heart rate: true or false")
    elif key == "settings_pin":
        if not isinstance(value, str) or len(value) > 16:
            raise ValueError("Settings PIN: up to 16 characters")
    else:
        raise ValueError("unknown setting: {}".format(key))
    return value


def _check_together(cfg, new):
    """The rules between settings (HR rest below max, the step levels in order, a PIN for the fan buttons)."""
    merged = dict(cfg)
    merged.update(new)
    if merged["hr_rest"] >= merged["hr_max"]:
        raise ValueError("HR rest must be below HR max")
    if merged.get("pin_for_control") and not merged["settings_pin"]:
        raise ValueError("Fan buttons need the PIN: set a settings PIN first")
    up, down = merged["up_thresholds"], merged["down_thresholds"]
    for i in range(3):          # the most specific message first: one level, with its values
        if not down[i] < up[i]:
            raise ValueError("Level {}: step down ({}) must be below step up ({})".format(i + 1, down[i], up[i]))
    for name, row in (("up", up), ("down", down)):
        for i in range(2):
            if not row[i] < row[i + 1]:
                raise ValueError("Step {}: level {} ({}) must be below level {} ({})".format(
                    name, i + 1, row[i], i + 2, row[i + 1]))
    return {k: v for k, v in new.items() if cfg.get(k) != v}


# ---- at start: every saved value, as the page would check it -------------------------------------------------------

_PAIRS = (("hr_rest", "hr_max"), ("up_thresholds", "down_thresholds"))


def sanitize(cfg, defaults=None):
    """Check every saved setting the way the page checks a new one; a value that fails goes back to its default
    (for a pair that doesn't fit together: both). Riders too, then the active rider is mirrored again. Returns the
    names of what was reset ([] = all fine). Never raises."""
    d = defaults or config.DEFAULTS
    fixed = []

    def reset(target, key, label):
        target[key] = list(d[key]) if isinstance(d[key], list) else d[key]
        if label not in fixed:
            fixed.append(label)

    try:
        for key in CHECKED:
            if key in cfg:
                try:
                    cfg[key] = _check_one(key, cfg[key])
                except (ValueError, TypeError, KeyError):
                    reset(cfg, key, key)
        for key in ("wifi_ssid", "wifi_password", "link_key", "follow_id", "follow_name", "follow_key"):
            if not isinstance(cfg.get(key), str) or len(cfg[key]) > 64:
                reset(cfg, key, key)
        try:
            restore_settings(dict(d), {k: cfg[k] for k in ("hr_rr", "follow_mode", "follow_offset") if k in cfg})
        except (ValueError, TypeError, KeyError):
            for key in ("hr_rr", "follow_mode", "follow_offset"):
                try:
                    restore_settings(dict(d), {key: cfg[key]})
                except (ValueError, TypeError, KeyError):
                    reset(cfg, key, key)
        _fix_pairs(cfg, d, reset, cfg, "")
        if cfg.get("pin_for_control") and not cfg.get("settings_pin"):
            reset(cfg, "pin_for_control", "pin_for_control")
        ps = cfg.get("profiles")
        if not isinstance(ps, list) or not 1 <= len(ps) <= profiles.MAX or not all(isinstance(p, dict) for p in ps):
            cfg.pop("profiles", None)
            fixed.append("riders")
        else:
            for n, p in enumerate(ps):
                if not isinstance(p.get("name"), str) or not p["name"].strip():
                    p["name"] = "Rider {}".format(n + 1)
                    fixed.append("rider name")
                for key in profiles.FIELDS:
                    if key not in p:
                        continue                         # profiles.ensure fills it from the top-level value
                    try:
                        p[key] = _check_one(key, p[key])
                    except (ValueError, TypeError, KeyError):
                        reset(p, key, "rider {}: {}".format(p["name"], key))
                _fix_pairs(p, d, reset, p, "rider {}: ".format(p["name"]))
        i = cfg.get("profile")
        if not isinstance(i, int) or isinstance(i, bool) or not (isinstance(cfg.get("profiles"), list)
                                                                and 0 <= i < len(cfg["profiles"])):
            if "profiles" in cfg:
                cfg["profile"] = 0
                fixed.append("selected rider")
        profiles.ensure(cfg)
        profiles.sync(cfg)                               # the active rider = the checked top-level values
    except Exception as e:                               # the check itself must never stop the fan
        print("checks.sanitize:", e)
    return fixed


def _fix_pairs(target, d, reset, where, prefix):
    try:
        if not target["hr_rest"] < target["hr_max"]:
            reset(where, "hr_rest", prefix + "hr_rest")
            reset(where, "hr_max", prefix + "hr_max")
    except (KeyError, TypeError):
        pass
    try:
        up, down = target["up_thresholds"], target["down_thresholds"]
        if not all(down[i] < up[i] for i in range(3)) or not all(up[i] < up[i + 1] and down[i] < down[i + 1]
                                                                  for i in range(2)):
            reset(where, "up_thresholds", prefix + "step levels")
            reset(where, "down_thresholds", prefix + "step levels")
    except (KeyError, TypeError, IndexError):
        pass
