import os
import sys

# Make the project modules (config, relay, fan_logic, ...) and the vendored libraries in lib/
# importable under CPython.
FIRMWARE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FIRMWARE)
sys.path.insert(0, os.path.join(FIRMWARE, "lib"))

import pytest

# MicroPython's cryptolib (AES) doesn't exist in CPython: a tested stand-in takes its place (tests/cryptolib_standin.py)
import cryptolib_standin
sys.modules.setdefault("cryptolib", cryptolib_standin)


@pytest.fixture(autouse=True)
def _no_logbook_files(request, monkeypatch):
    """Code under test writes logbook lines (Wi-Fi, sensors, web): keep them out of the firmware folder. The
    logbook's own tests pass temporary paths and keep the real function."""
    if request.module.__name__.endswith("test_logbook"):
        return
    import logbook
    monkeypatch.setattr(logbook, "write", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _setup_gate(request, monkeypatch):
    """Most tests use the default settings (no PIN, default access point password), which the first-setup gate would
    refuse. They run with the gate off; tests marked @pytest.mark.setup_gate keep it."""
    if request.node.get_closest_marker("setup_gate"):
        return
    import web
    monkeypatch.setattr(web, "REQUIRE_SETUP", False)
