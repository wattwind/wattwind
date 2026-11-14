"""MicroPython build check (mpbuild.py, updater.check_requires, make_manifest "requires"): MicroPython
compatibility. A 1.1+ fan refuses a Wi-Fi update that needs a newer MicroPython file, before anything changes."""
import json
import os
import sys
import types

import pytest

import mpbuild
import updater

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.parametrize("machine, n", [
    ("Raspberry Pi Pico 2 W with RP2350", 1),                                   # stock micropython.org / the 1.0 file
    ("Raspberry Pi Pico 2 W (WattWind MicroPython 2) with RP2350", 2),          # the 1.1 release file
    ("Raspberry Pi Pico W (WattWind MicroPython 2) with RP2040", 2),
    ("Raspberry Pi Pico 2 W (WattWind MicroPython 17) with RP2350", 17),
    ("Raspberry Pi Pico 2 W (WattWind MicroPython ) with RP2350", 1),           # damaged label: old
    ("", 1),
])
def test_number_from_the_board_name(machine, n):
    assert mpbuild.number(machine) == n


def test_number_reads_os_uname(monkeypatch):
    monkeypatch.setattr(mpbuild.os, "uname", lambda: types.SimpleNamespace(
        machine="Raspberry Pi Pico 2 W (WattWind MicroPython 2) with RP2350"), raising=False)
    assert mpbuild.number() == 2 and mpbuild.has("pairing")


def test_no_uname_counts_as_old(monkeypatch):
    def broken():
        raise AttributeError
    monkeypatch.setattr(mpbuild.os, "uname", broken, raising=False)
    assert mpbuild.number() == 1


def test_features():
    assert mpbuild.features(1) == {"connections": 3, "pairing": False}
    assert mpbuild.features(2) == {"connections": 6, "pairing": True}
    assert mpbuild.features(99) == mpbuild.features(max(mpbuild.FEATURES))   # newer file: never less
    assert mpbuild.features(0) == mpbuild.features(1)
    assert not mpbuild.has("pairing", 1) and mpbuild.has("pairing", 2)


def test_build_script_label_matches_the_table():
    """build.sh's MP_BUILD is a number mpbuild knows (raise both together)."""
    src = open(os.path.join(HERE, "..", "..", "micropython", "build.sh"), encoding="utf-8").read()
    line = [l for l in src.splitlines() if l.startswith("MP_BUILD=")][0]
    n = int(line.split("=")[1].split()[0])
    assert n in mpbuild.FEATURES
    assert mpbuild.LABEL.strip() in src


# ------------------------------------------------------------------ the updater


def _manifest(req=None):
    m = {"version": "9.9.9", "files": {"main.py": "a" * 64}}
    if req is not None:
        m["requires"] = req
    return m


def test_no_requires_installs_on_any_file():
    updater.check_requires(_manifest(), mp_build=1)          # every release up to 1.1 has none


def test_requires_newer_file_is_refused_with_what_to_do():
    with pytest.raises(updater.UpdateError) as e:
        updater.check_requires(_manifest({"mp_build": 2}), mp_build=1)
    msg = str(e.value)
    assert "WattWind MicroPython 2" in msg and "over USB" in msg and "Nothing was changed" in msg


def test_requires_met_or_exceeded():
    updater.check_requires(_manifest({"mp_build": 2}), mp_build=2)
    updater.check_requires(_manifest({"mp_build": 2}), mp_build=3)


@pytest.mark.parametrize("bad", [{"mp_build": "2"}, {"mp_build": 0}, {"mp_build": True}, {"mp_build": -1}])
def test_bad_requires_is_refused(bad):
    with pytest.raises(updater.UpdateError):
        updater.check_requires(_manifest(bad), mp_build=5)


def test_start_refuses_before_touching_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "ROOT", str(tmp_path) + "/")
    (tmp_path / "update").mkdir()
    (tmp_path / "update" / "left.py").write_text("an earlier unfinished update")
    m = _manifest({"mp_build": 2})
    with pytest.raises(updater.UpdateError):
        updater.start(m, {"main.py": 10, "manifest.json": 10}, free=10 ** 7, mp_build=1)
    assert (tmp_path / "update" / "left.py").exists()       # refused first: nothing removed or written


# ------------------------------------------------------------------ the manifest writer


def _make_manifest():
    sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
    try:
        import make_manifest
        return make_manifest
    finally:
        sys.path.pop(0)


def test_manifest_writes_requires_only_when_needed(tmp_path):
    mm = _make_manifest()
    (tmp_path / "version.py").write_text('VERSION = "1.2.0"\nMP_BUILD_NEEDED = 1\n')
    (tmp_path / "main.py").write_text("print(1)\n")
    mm.main(str(tmp_path))
    assert "requires" not in json.loads((tmp_path / "manifest.json").read_text())
    (tmp_path / "version.py").write_text('VERSION = "1.2.0"\nMP_BUILD_NEEDED = 2\n')
    mm.main(str(tmp_path))
    assert json.loads((tmp_path / "manifest.json").read_text())["requires"] == {"mp_build": 2}


def test_this_firmware_runs_on_the_old_file():
    """1.1's basics run on the 1.0 MicroPython file: it must not require a newer one."""
    import version
    assert getattr(version, "MP_BUILD_NEEDED", 1) == 1
