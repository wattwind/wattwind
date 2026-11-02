"""Every firmware file compiles. main.py, wifi.py and others aren't imported by the other tests (they need the
Pico), so a syntax error there would otherwise only show up on the fan, where it would stop it from starting."""
import glob
import os

import pytest

FIRMWARE = os.path.join(os.path.dirname(__file__), "..")


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(FIRMWARE, "*.py"))), ids=os.path.basename)
def test_compiles(path):
    with open(path, encoding="utf-8") as f:
        compile(f.read(), path, "exec")
