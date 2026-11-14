"""Bluetooth pairing keys on flash, for Share heart rate with receivers that pair (Garmin Edge).

Only with the pairing MicroPython build (micropython/build.sh PAIRING=1, btstack-pairing.patch): that build
hands BTstack's key store to Python as _IRQ_GET_SECRET / _IRQ_SET_SECRET events (sec_type 0x57, a 4-byte tag).
This module keeps them in ble_bonds.json, so a paired watch or bike computer reconnects after the fan restarts
without pairing again. The file holds up to 4 paired devices (BTstack replaces the least recently used) and
BTstack's own random keys (ER / IR), made once per fan. Erase everything deletes it; backups leave it out.

On the stock build nothing here does anything: supported() is False and no events come.
Pure Python apart from the optional aioble import in install(), so it runs in the host tests.
"""

import binascii
import json
import os

FILE = "ble_bonds.json"
_IRQ_ENCRYPTION_UPDATE = 28
_IRQ_GET_SECRET = 29
_IRQ_SET_SECRET = 30
TLV_TYPE = 0x57                  # btstack-pairing.patch WATTWIND_TLV_SECRET_TYPE
GAP_APPEARANCE_HANDLE = 5        # btstack-pairing.patch BTSTACK_GAP_APPEARANCE_HANDLE (pairing build only)
_DEVICE_TAG_END = "445442"       # BTstack device database tags 'B' 'T' 'D' + index, stored little-endian

_replace = getattr(os, "replace", None) or os.rename   # MicroPython has only rename (LittleFS replaces)
_store = None                    # {"<type>:<key hex>": "<value hex>"}, loaded on first use
_installed = False
on_encryption = None             # optional callback(conn_handle, encrypted, bonded), set by ble_share


def supported():
    """True on the pairing MicroPython build (it has gap_pair; the stock build doesn't)."""
    try:
        import bluetooth
        return hasattr(bluetooth.BLE, "gap_pair")
    except Exception:
        return False


def _load():
    global _store
    if _store is not None:
        return _store
    try:
        with open(FILE) as f:
            data = json.load(f)
        _store = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        _store = {}              # none yet, or damaged: start empty (receivers pair again)
    return _store


def _save():
    tmp = FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_store, f)
        _replace(tmp, FILE)
        return True
    except OSError as e:
        print("bonds: not saved", repr(e))
        return False


def _key(sec_type, key):
    return "{}:{}".format(sec_type, binascii.hexlify(bytes(key)).decode())


def get(sec_type, key):
    value = _load().get(_key(sec_type, key))
    if value is None:
        return None
    try:
        return binascii.unhexlify(value)
    except (ValueError, TypeError):
        return None


def put(sec_type, key, value):
    """Store (value bytes) or delete (value None). True when it is on flash."""
    store = _load()
    k = _key(sec_type, key)
    if value is None:
        if k not in store:
            return True
        del store[k]
    else:
        v = binascii.hexlify(bytes(value)).decode()
        if store.get(k) == v:
            return True          # unchanged: no flash write
        store[k] = v
    return _save()


def count():
    """Paired devices kept (the ER / IR keys don't count)."""
    return sum(1 for k in _load() if k.endswith(_DEVICE_TAG_END))


def forget():
    """Delete every pairing (takes effect at the next start)."""
    global _store
    _store = {}
    try:
        os.remove(FILE)
    except OSError:
        pass


def irq(event, data):
    """aioble IRQ handler: answers BTstack's key store; anything else is left to the other handlers."""
    if event == _IRQ_GET_SECRET:
        sec_type, _index, key = data
        if key is None:          # lookup by index: not used by the pairing build
            return None
        return get(sec_type, key)
    if event == _IRQ_SET_SECRET:
        sec_type, key, value = data
        return put(sec_type, key, None if value is None else bytes(value))
    if event == _IRQ_ENCRYPTION_UPDATE and on_encryption is not None:
        conn_handle, encrypted, _authenticated, bonded, _key_size = data
        try:
            on_encryption(conn_handle, bool(encrypted), bool(bonded))
        except Exception as e:
            print("bonds: encryption callback", repr(e))
    return None


def install():
    """Register with aioble before Bluetooth starts (BTstack reads the keys while starting). Idempotent."""
    global _installed
    if _installed or not supported():
        return
    import aioble
    aioble.core.register_irq_handler(irq, None)
    _installed = True
