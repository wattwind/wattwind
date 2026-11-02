import config
import profiles


def make():
    return profiles.ensure(dict(config.DEFAULTS, ftp=250, hr_addr="aa:aa:aa:aa:aa:aa"))


def test_existing_settings_become_rider_1():
    cfg = make()
    assert cfg["profile"] == 0 and cfg["profiles"][0]["name"] == "Rider 1"
    assert cfg["profiles"][0]["ftp"] == 250 and cfg["profiles"][0]["hr_addr"] == "aa:aa:aa:aa:aa:aa"


def test_add_switch_and_keep_values_apart():
    cfg = make()
    profiles.add(cfg, "Anna", config.DEFAULTS)
    assert cfg["profile"] == 1 and cfg["ftp"] == config.DEFAULTS["ftp"] and cfg["hr_addr"] == ""
    cfg["ftp"] = 180                       # Anna edits her FTP in Settings
    profiles.sync(cfg)
    profiles.activate(cfg, 0)
    assert cfg["ftp"] == 250 and cfg["hr_addr"] == "aa:aa:aa:aa:aa:aa"
    profiles.activate(cfg, 1)
    assert cfg["ftp"] == 180 and profiles.name(cfg) == "Anna"


def test_owner_of_strap():
    cfg = make()
    profiles.add(cfg, "Anna", config.DEFAULTS)
    cfg["hr_addr"] = "bb:bb:bb:bb:bb:bb"
    profiles.sync(cfg)
    assert profiles.owner_of(cfg, "bb:bb:bb:bb:bb:bb") == 1
    assert profiles.owner_of(cfg, "aa:aa:aa:aa:aa:aa") == 0
    assert profiles.owner_of(cfg, "cc:cc:cc:cc:cc:cc") is None and profiles.owner_of(cfg, "") is None


def test_delete_and_limits():
    cfg = make()
    for n in ("B", "C", "D", "E"):
        profiles.add(cfg, n, config.DEFAULTS)
    try:
        profiles.add(cfg, "F", config.DEFAULTS)
        assert False
    except ValueError:
        pass
    profiles.activate(cfg, 2)                     # C active
    profiles.delete(cfg, 0)                       # delete before the active one: index shifts
    assert profiles.name(cfg) == "C" and cfg["profile"] == 1
    profiles.delete(cfg, 1)                       # delete the active one: first becomes active
    assert cfg["profile"] == 0 and profiles.name(cfg) == "B"
    for _ in range(2):
        profiles.delete(cfg, 0)
    try:
        profiles.delete(cfg, 0)
        assert False
    except ValueError:
        pass
    for bad in ("", "x" * 17, None):
        try:
            profiles.add(cfg, bad, config.DEFAULTS)
            assert False
        except ValueError:
            pass


def test_thresholds_are_per_rider():
    cfg = make()
    profiles.add(cfg, "Anna", config.DEFAULTS)
    cfg["up_thresholds"] = [0.40, 0.62, 0.80]            # Anna runs hot
    profiles.sync(cfg)
    profiles.activate(cfg, 0)
    assert cfg["up_thresholds"] == config.DEFAULTS["up_thresholds"]
    profiles.activate(cfg, 1)
    assert cfg["up_thresholds"] == [0.40, 0.62, 0.80]
    assert config.DEFAULTS["up_thresholds"] == [0.45, 0.70, 0.88]   # defaults untouched


def test_strap_moves_to_the_rider_it_is_given_to():
    cfg = make()                           # Rider 1 has aa:..
    profiles.add(cfg, "Anna", config.DEFAULTS)
    cfg["hr_addr"] = "aa:aa:aa:aa:aa:aa"   # Anna picks the same strap with "Use for HR"
    profiles.sync(cfg)
    assert cfg["profiles"][1]["hr_addr"] == "aa:aa:aa:aa:aa:aa" and cfg["profiles"][0]["hr_addr"] == ""
    assert profiles.owner_of(cfg, "aa:aa:aa:aa:aa:aa") == 1
