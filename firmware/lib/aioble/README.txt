aioble 0.6.2 (MIT licence, see LICENSE.txt), vendored unchanged from micropython-lib master
on 2026-10-24 (peripheral.py and server.py added 2026-11-02, same version):
https://github.com/micropython/micropython-lib/tree/master/micropython/bluetooth/aioble
Copied: __init__.py, core.py, device.py, central.py, client.py (the sensors: the fan as a central),
peripheral.py, server.py (heart rate sharing, ble_share.py: the fan as a heart-rate sensor).
l2cap.py and security.py are left out on purpose; __init__.py imports the missing ones inside try/except.
