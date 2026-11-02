import json

import config


def _plain(cfg):          # the loaded config also holds the rider profiles (made from the defaults)
    assert cfg["profiles"][0]["ftp"] == config.DEFAULTS["ftp"] and cfg["profile"] == 0
    return {k: v for k, v in cfg.items() if k not in ("profiles", "profile")}


def test_first_boot_creates_file(tmp_path):
    path = str(tmp_path / "config.json")
    assert _plain(config.load(path)) == config.DEFAULTS
    assert json.load(open(path)) == config.DEFAULTS


def test_file_overrides_defaults(tmp_path):
    path = str(tmp_path / "config.json")
    json.dump({"ftp": 300}, open(path, "w"))
    cfg = config.load(path)
    assert cfg["ftp"] == 300
    assert cfg["hr_max"] == config.DEFAULTS["hr_max"]


def test_damaged_flag_for_the_page(tmp_path):
    """main.py shows a one-time page message when config.load() had to start from defaults."""
    path = str(tmp_path / "config.json")
    config.damaged = False
    config.load(path)                                  # missing: created, not damaged
    assert config.damaged is False
    open(path, "w").write("{not json")
    config.load(path)
    assert config.damaged is True
    config.damaged = False


def test_damaged_file_starts_with_defaults(tmp_path):
    # power cut while saving: empty or half-written file must not stop the fan from starting
    path = str(tmp_path / "config.json")
    for damaged in ("", '{"ftp": 3', "[1, 2]"):
        open(path, "w").write(damaged)
        assert _plain(config.load(path)) == config.DEFAULTS
        assert open(path + ".bad").read() == damaged
        assert json.load(open(path)) == config.DEFAULTS


def test_save_replaces_file_and_leaves_no_temp(tmp_path):
    path = str(tmp_path / "config.json")
    config.save({"ftp": 200}, path)
    config.save({"ftp": 210}, path)
    assert json.load(open(path)) == {"ftp": 210}
    assert not (tmp_path / "config.json.tmp").exists()
