"""Pairing keys on flash (ble_bonds.py) and pairing in Share heart rate (ble_share.py), on the host.

The pairing MicroPython build hands BTstack's key store to Python (micropython/btstack-pairing.patch):
_IRQ_GET_SECRET (29) / _IRQ_SET_SECRET (30) with sec_type 0x57 and a 4-byte little-endian tag.
"""
import importlib
import json
import os
import struct
import sys
import types

import pytest

TLV = 0x57


def tag(a, b, c, d):
    """BTstack TLV tag (BTSTACK_TAG32) as the patch sends it: little-endian bytes."""
    return struct.pack("<I", (ord(a) << 24) | (ord(b) << 16) | (ord(c) << 8) | (d if isinstance(d, int) else ord(d)))


DEV0, DEV1 = tag("B", "T", "D", 0), tag("B", "T", "D", 1)
SMER, SMIR = tag("S", "M", "E", "R"), tag("S", "M", "I", "R")


class FakeBLE:
    """bluetooth.BLE of the pairing build: has gap_pair; records config() and gatts_write()."""
    def __init__(self):
        self.configs = []
        self.writes = []

    def gap_pair(self, conn):
        pass

    def config(self, **kw):
        self.configs.append(kw)

    def gatts_write(self, handle, data, send_update=False):
        self.writes.append((handle, bytes(data)))


class StockBLE:
    """bluetooth.BLE of the released build: no gap_pair."""
    def config(self, **kw):
        raise AssertionError("no pairing config on the stock build")

    def gatts_write(self, handle, data, send_update=False):
        raise AssertionError("handle 5 is not the Appearance on the stock build: never written")


@pytest.fixture
def bonds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    handlers = []
    ble = FakeBLE()
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=FakeBLE, UUID=lambda v: v))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(
        core=types.SimpleNamespace(ble=ble, register_irq_handler=lambda irq, shutdown: handlers.append(irq))))
    sys.modules.pop("ble_bonds", None)
    import ble_bonds
    return ble_bonds, handlers, tmp_path


def test_supported_only_on_the_pairing_build(monkeypatch):
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=StockBLE))
    sys.modules.pop("ble_bonds", None)
    import ble_bonds
    assert ble_bonds.supported() is False
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=FakeBLE))
    assert ble_bonds.supported() is True
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace())      # no BLE at all (host, odd build)
    assert ble_bonds.supported() is False


def test_install_registers_once_and_never_on_stock(bonds, monkeypatch):
    b, handlers, _ = bonds
    b.install()
    b.install()
    assert handlers == [b.irq]
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=StockBLE))
    sys.modules.pop("ble_bonds", None)
    import ble_bonds
    ble_bonds.install()
    assert handlers == [b.irq]                  # stock build: nothing registered


def test_set_then_get_through_the_irq_with_memoryviews(bonds):
    b = bonds[0]
    entry = bytes(range(60))
    assert b.irq(30, (TLV, memoryview(DEV0), memoryview(entry))) is True
    assert b.irq(29, (TLV, 0, memoryview(DEV0))) == entry
    assert b.irq(29, (TLV, 0, memoryview(DEV1))) is None           # not stored: None (BTstack: missing)
    assert b.irq(29, (0x01, 0, memoryview(DEV0))) is None          # another sec_type is another key


def test_kept_on_flash_across_a_restart(bonds):
    b, _, path = bonds
    er = os.urandom(16)
    b.irq(30, (TLV, SMER, er))
    b.irq(30, (TLV, DEV0, b"\x01" * 60))
    assert (path / "ble_bonds.json").exists() and not (path / "ble_bonds.json.tmp").exists()
    sys.modules.pop("ble_bonds", None)
    import ble_bonds                            # a fresh start reads the file
    assert ble_bonds.irq(29, (TLV, 0, SMER)) == er
    assert ble_bonds.count() == 1


def test_delete_and_index_lookups(bonds):
    b = bonds[0]
    b.irq(30, (TLV, DEV0, b"x" * 60))
    assert b.irq(30, (TLV, DEV0, None)) is True                    # delete_tag
    assert b.irq(29, (TLV, 0, DEV0)) is None
    assert b.irq(30, (TLV, DEV1, None)) is True                    # deleting a missing one is fine
    assert b.irq(29, (TLV, 0, None)) is None                       # lookup by index: unused, None


def test_unchanged_value_is_not_written_again(bonds, monkeypatch):
    b = bonds[0]
    b.irq(30, (TLV, SMIR, b"k" * 16))
    saves = []
    monkeypatch.setattr(b, "_save", lambda: saves.append(1) or True)
    b.irq(30, (TLV, SMIR, b"k" * 16))
    assert saves == []
    b.irq(30, (TLV, SMIR, b"j" * 16))
    assert saves == [1]


def test_count_is_paired_devices_only(bonds):
    b = bonds[0]
    b.irq(30, (TLV, SMER, b"e" * 16))
    b.irq(30, (TLV, SMIR, b"i" * 16))
    assert b.count() == 0                       # BTstack's own ER / IR keys are no paired device
    for i in range(4):
        b.irq(30, (TLV, tag("B", "T", "D", i), b"d" * 60))
    assert b.count() == 4


def test_damaged_file_starts_empty(bonds):
    b, _, path = bonds
    (path / "ble_bonds.json").write_text("{not json")
    assert b.irq(29, (TLV, 0, SMER)) is None
    assert b.count() == 0
    b.irq(30, (TLV, SMER, b"e" * 16))           # and is replaced by a good one
    assert isinstance(json.loads((path / "ble_bonds.json").read_text()), dict)


def test_full_flash_is_reported_not_raised(bonds, monkeypatch):
    b = bonds[0]

    def no_space(*a, **k):
        raise OSError(28, "no space")
    monkeypatch.setattr("builtins.open", no_space)
    assert b.irq(30, (TLV, SMER, b"e" * 16)) is False             # BTstack sees a failed store, nothing crashes


def test_forget(bonds):
    b, _, path = bonds
    b.irq(30, (TLV, DEV0, b"d" * 60))
    b.forget()
    assert not (path / "ble_bonds.json").exists() and b.count() == 0
    b.forget()                                  # twice is fine


def test_other_events_are_left_to_aioble(bonds):
    b = bonds[0]
    assert b.irq(1, (64, 1, b"")) is None       # connect
    assert b.irq(3, (64, 12)) is None           # gatts write


def test_encryption_update_reaches_the_callback(bonds):
    b = bonds[0]
    seen = []
    b.on_encryption = lambda h, enc, bonded: seen.append((h, enc, bonded))
    assert b.irq(28, (64, 1, 0, 1, 16)) is None
    assert seen == [(64, True, True)]
    b.on_encryption = lambda *a: 1 / 0          # a broken callback never breaks the Bluetooth stack
    assert b.irq(28, (64, 1, 0, 1, 16)) is None


# ------------------------------------------------------------------ Share heart rate with pairing


@pytest.fixture
def share(tmp_path, monkeypatch):
    """ble_share on the pairing build (FakeBLE) with aioble stand-ins."""
    monkeypatch.chdir(tmp_path)
    ble = FakeBLE()
    handlers = []
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=FakeBLE, UUID=lambda v: v))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(
        DeviceDisconnectedError=Exception, Service=lambda u: types.SimpleNamespace(chars=[]),
        Characteristic=lambda *a, **k: types.SimpleNamespace(write=lambda *a, **k: None),
        register_services=lambda *s: None, config=lambda **kw: None,
        core=types.SimpleNamespace(ble=ble, register_irq_handler=lambda irq, sd: handlers.append(irq))))
    import config
    import state
    importlib.reload(state)
    for m in ("ble_share", "ble_bonds"):
        sys.modules.pop(m, None)
    import ble_share
    return ble_share, state, ble, dict(config.DEFAULTS), handlers


def test_share_installs_the_key_store_on_import(share):
    bs, _, _, _, handlers = share
    assert handlers == [bs.ble_bonds.irq]       # registered before Bluetooth can start


def test_pairing_state(share):
    bs, _, _, cfg, _ = share
    assert bs.pairing(cfg) == "on"              # pairing build: always allowed (no setting, user 2026-11-03)
    assert "hr_share_pair" not in cfg


def test_apply_pairing_sets_bond_and_appearance(share):
    bs, _, ble, cfg, _ = share
    bs._apply_pairing(cfg)
    assert ble.configs[-1] == {"bond": True, "mitm": False, "io": 3, "le_secure": False}    # Just Works, kept
    assert ble.writes[-1] == (5, struct.pack("<H", 0x0341))       # GAP Appearance: heart rate belt


def test_apply_pairing_survives_a_stack_error(share):
    bs, _, ble, cfg, _ = share

    def broken(**kw):
        raise OSError(-1)
    ble.config = broken
    bs._apply_pairing(cfg)                      # printed, not raised: sharing goes on without pairing


def test_paired_only_while_a_receiver_is_connected(share):
    bs, state, _, _, _ = share
    bs._on_encryption(64, True, True)
    assert state.share_secure == ""             # nobody connected: ignored
    bs._rx[64] = {"conn": object(), "addr": "x", "sent": 0, "paired": False}
    bs._on_encryption(64, False, False)
    assert state.share_secure == ""             # not encrypted
    bs._on_encryption(65, True, True)
    assert state.share_secure == ""             # another link (a sensor): not a receiver
    bs._on_encryption(64, True, True)
    assert state.share_secure == "paired" and bs._rx[64]["paired"]
    bs._rx.clear()


def test_stock_build_never_touches_pairing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "bluetooth", types.SimpleNamespace(BLE=StockBLE, UUID=lambda v: v))
    monkeypatch.setitem(sys.modules, "aioble", types.SimpleNamespace(
        core=types.SimpleNamespace(ble=StockBLE(), register_irq_handler=lambda *a: pytest.fail("registered"))))
    import config
    for m in ("ble_share", "ble_bonds"):
        sys.modules.pop(m, None)
    import ble_share
    cfg = dict(config.DEFAULTS)
    assert ble_share.pairing(cfg) == "unsupported"
    ble_share._apply_pairing(cfg)               # StockBLE raises if config / gatts_write were called


# ------------------------------------------------------------------ settings, erase, manifest


def test_erase_everything_deletes_the_pairings_and_the_manifest_skips_them():
    here = os.path.dirname(os.path.abspath(__file__))
    main_src = open(os.path.join(here, "..", "main.py"), encoding="utf-8").read()
    users = main_src.split("USER_FILES = (", 1)[1].split(")", 1)[0]
    assert '"ble_bonds.json"' in users
    sys.path.insert(0, os.path.join(here, "..", "..", "tools"))
    try:
        import make_manifest
        assert "ble_bonds.json" in make_manifest.SKIP_FILES and "ble_bonds.json.tmp" in make_manifest.SKIP_FILES
    finally:
        sys.path.pop(0)


def test_backup_never_carries_the_keys():
    import checks
    assert not any("bond" in k or "pair" in k for k in checks.BACKUP_KEYS)   # keys belong to this fan only
