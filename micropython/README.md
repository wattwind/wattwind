# MicroPython for the WattWind

The fan connects to a heart rate strap and a trainer **at the same time**. Stock MicroPython
for the Pico W / Pico 2 W allows only **one** BLE connection: its BTstack runs without malloc,
from fixed pools sized `MAX_NR_HCI_CONNECTIONS 1` and `MAX_NR_GATT_CLIENTS 1`
(`extmod/btstack/btstack_config_common.h`). A second `connect()` then fails with
`OSError(107)` (ENOTCONN: BTstack's `gap_connect` returns `GATT_CLIENT_NOT_CONNECTED` when it
can't allocate a connection, `lib/btstack/src/hci.c`).

This build is MicroPython **v1.29.0, unchanged except for those two limits, raised to 3**
(strap + trainer + one app or watch for Share heart rate). Cost: about 5 KB less RAM.

## Flashing

Hold BOOTSEL, plug in USB, copy the UF2 for your board to the `RPI-RP2` / `RP2350` drive:

| Board | File |
|---|---|
| Pico 2 W | `firmware/RPI_PICO2_W-v1.29.0-wattwind-ble3.uf2` |

The Pico W build (`RPI_PICO_W`) still builds and is kept for reference, but the project supports only the
Pico 2 W (since 2026-10-30).

Flashing MicroPython keeps the files on the Pico (the filesystem is not erased).
Check at the REPL: the banner should show `MicroPython v1.29.0-dirty` with the date the file was built (git marks
the patched source as "dirty"); the stock firmware shows plain `v1.29.0`.

## Files

| File | What |
|---|---|
| `btstack-3-connections.patch` | The only change: `ports/rp2/btstack_inc/btstack_config.h` |
| `build.sh` | Builds the UF2s in a throwaway Ubuntu 24.04 Docker container: clones v1.29.0, applies the patch, runs the standard `make` |
| `firmware/` | Built UF2s (git-ignored; to be published as GitHub release assets) and `firmware/licenses/` from the build |
| `LICENSES/` | The licences of what is inside the UF2 (MicroPython, BTstack, cyw43-driver, Pico SDK): **publish them with the UF2**; BTstack and cyw43-driver may only be used with Raspberry Pi chips |

## Building

Needs only [Docker](https://www.docker.com/) (Docker Desktop on Windows, started). From the
project root, in Git Bash on Windows or any Linux/macOS shell:

```bash
micropython/build.sh                 # Pico W and Pico 2 W
micropython/build.sh RPI_PICO_W      # one board
```

The container installs Ubuntu's ARM compiler, builds both UF2s into `micropython/firmware/`
and is deleted afterwards; nothing is installed on your PC. A build takes a few minutes.

Without Docker, on Linux: clone v1.29.0, apply `btstack-3-connections.patch`, then
`make -C mpy-cross && make -C ports/rp2 BOARD=RPI_PICO2_W submodules all`.

## Troubleshooting: freezes after Ctrl-D

If the console stops at `web: listening` and the web page never answers (while the router
shows the Pico as connected), the Pico was **soft-rebooted** (Ctrl-D, or Thonny / MicroPico
running or uploading files). That leaves the Wi-Fi/Bluetooth chip running from the previous
run, and starting it again hangs the board, with stock MicroPython too. `main.py` detects this
and does a hard reset, so you only see a short USB disconnect.
