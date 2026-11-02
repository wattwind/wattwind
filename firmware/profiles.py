"""Rider profiles: several people can share the fan, each with their own FTP, heart-rate range, fan response
and heart-rate strap.

cfg["profiles"] is a list of dicts with the keys in FIELDS plus "name"; cfg["profile"] is the index of the
active one. The active profile's values are mirrored in the normal top-level settings (cfg["ftp"], ...), so
the rest of the firmware (fan_logic, the Bluetooth sensors) reads them as before. Keep the two in step:
sync() after a top-level value changes, activate() to switch. Pure Python: host-tested.
"""

FIELDS = ("ftp", "hr_max", "hr_rest", "use", "response", "up_thresholds", "down_thresholds", "hr_addr")
MAX = 5
NAME_MAX = 16


def ensure(cfg):
    """Create the profile list from the current settings if there is none (first start, older config)."""
    ps = cfg.get("profiles")
    if not isinstance(ps, list) or not ps:
        p = {"name": "Rider 1"}
        for f in FIELDS:
            p[f] = _copy(cfg[f])
        cfg["profiles"] = [p]
        cfg["profile"] = 0
    i = cfg.get("profile")
    if not isinstance(i, int) or not 0 <= i < len(cfg["profiles"]):
        cfg["profile"] = 0
    for p in cfg["profiles"]:                # a profile saved by an older version may lack a field
        for f in FIELDS:
            if f not in p:
                p[f] = _copy(cfg[f])
    return cfg


def _copy(v):
    return list(v) if isinstance(v, list) else v     # the threshold lists must not be shared between riders


def sync(cfg):
    """Copy the top-level values into the active profile (after settings changed). A strap belongs to one
    rider only: giving it to the active rider takes it away from any other."""
    ps = cfg.get("profiles")
    if ps:
        i = cfg.get("profile", 0)
        p = ps[i]
        for f in FIELDS:
            p[f] = _copy(cfg[f])
        if p["hr_addr"]:
            for j, q in enumerate(ps):
                if j != i and q.get("hr_addr") == p["hr_addr"]:
                    q["hr_addr"] = ""


def activate(cfg, i):
    """Make profile i the active one: its values become the top-level settings."""
    sync(cfg)
    cfg["profile"] = i
    for f in FIELDS:
        cfg[f] = _copy(cfg["profiles"][i][f])


def owner_of(cfg, addr):
    """Index of the profile whose strap has this address, or None."""
    for i, p in enumerate(cfg.get("profiles") or []):
        if addr and p.get("hr_addr") == addr:
            return i
    return None


def name(cfg):
    ps = cfg.get("profiles") or []
    return ps[cfg.get("profile", 0)]["name"] if ps else ""


def check_name(n):
    if not isinstance(n, str) or not 1 <= len(n.strip()) <= NAME_MAX:
        raise ValueError("Rider name: 1 to {} characters".format(NAME_MAX))
    return n.strip()


def add(cfg, n, defaults):
    """New rider with the default values and no strap yet; becomes the active profile."""
    n = check_name(n)
    if len(cfg["profiles"]) >= MAX:
        raise ValueError("At most {} riders".format(MAX))
    p = {"name": n}
    for f in FIELDS:
        p[f] = _copy(defaults[f])
    p["hr_addr"] = ""
    sync(cfg)
    cfg["profiles"].append(p)
    activate(cfg, len(cfg["profiles"]) - 1)


def rename(cfg, i, n):
    cfg["profiles"][i]["name"] = check_name(n)


def delete(cfg, i):
    if len(cfg["profiles"]) <= 1:
        raise ValueError("The last rider can't be deleted")
    active = cfg["profile"]
    sync(cfg)
    del cfg["profiles"][i]
    if i == active:
        cfg["profile"] = 0
        for f in FIELDS:
            cfg[f] = _copy(cfg["profiles"][0][f])
    elif i < active:
        cfg["profile"] = active - 1
