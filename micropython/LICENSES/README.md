# Licences of the custom MicroPython (the UF2)

The WattWind UF2 (`micropython/firmware/RPI_PICO2_W-v1.29.0-wattwind-ble3.uf2`, published as a release asset) is
MicroPython v1.29.0 with one small change (`btstack-3-connections.patch`). Like every MicroPython build for the
Pico W / Pico 2 W, it contains code under these licences, and **this folder must be published with the UF2**
(their terms ask for the notices to go with binary copies):

| File | Component | In short |
|---|---|---|
| `MicroPython.txt` | MicroPython | MIT (and the licences of its parts listed there) |
| `BTstack.txt` | BTstack (Bluetooth) | Raspberry Pi's licence: use and distribution **only with Raspberry Pi's Pico W / Pico 2 W products** (the UF2 runs on nothing else) |
| `cyw43-driver.txt` | Wi-Fi / Bluetooth chip driver | Raspberry Pi device terms: **only with Raspberry Pi chips**; keep the notice |
| `pico-sdk.txt` | Raspberry Pi Pico SDK | BSD-3-Clause |

The texts are taken from the exact versions MicroPython v1.29.0 uses (commits named in each file).
`build.sh` also copies the licence files out of each build into `micropython/firmware/`, next to the UF2.
