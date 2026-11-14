"""Which MicroPython file the fan runs, and what it can do (MicroPython compatibility, release 1.1).

The project's MicroPython file has a label in its board name (micropython/build.sh): os.uname().machine reads
"Raspberry Pi Pico 2 W (WattWind MicroPython 2) with RP2350". The number says what the file has (FEATURES).
No label: build 1, the 1.0 file (3 Bluetooth connections, no pairing) or stock MicroPython from micropython.org
(1 connection): both count as old, the basics only. A number newer than this firmware knows counts as the newest
it knows (a newer file never takes anything away).

Every feature that needs a newer file checks here (or probes) at start and switches itself off with a page notice;
the basics run on every file. updater.start refuses a Wi-Fi update whose manifest "requires" a newer build.
Pure Python (os only), host-tested.
"""
import os

LABEL = "WattWind MicroPython "
OLD = 1
FEATURES = {
    1: {"connections": 3, "pairing": False},     # the 1.0 file (stock micropython.org: 1 connection, same treatment)
    2: {"connections": 6, "pairing": True},      # release 1.1: pairing + 6 connections
}


def machine():
    try:
        return os.uname().machine
    except Exception:
        return ""


def number(text=None):
    """The build number from the board name, or OLD (1) when there is no label."""
    if text is None:
        text = machine()
    i = text.find(LABEL)
    if i < 0:
        return OLD
    digits = ""
    for ch in text[i + len(LABEL):]:
        if "0" <= ch <= "9":
            digits += ch
        else:
            break
    return int(digits) if digits else OLD


def features(n=None):
    """What build n (default: this fan's) can do; a number newer than FEATURES counts as the newest known."""
    if n is None:
        n = number()
    known = [k for k in FEATURES if k <= n]
    return FEATURES[max(known)] if known else FEATURES[OLD]


def has(name, n=None):
    return bool(features(n).get(name))
