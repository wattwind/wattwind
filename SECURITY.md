# Security

## Reporting a problem

If you find a security problem in WattWind (the firmware, its web page, the linked-fans messages, the update
signing, or anything else that could let someone control a fan or read data they shouldn't), please report it
**privately**: on this repository's **Security** tab, choose **Report a vulnerability**. Please don't open a public
issue for it.

Useful in a report: the firmware version (bottom of Settings on the fan's page), what an attacker needs (same Wi-Fi,
Bluetooth range, physical access), and the steps to reproduce it.

## What to expect

WattWind is a hobby project, shared as it is. Reports are read and taken seriously, and fixes are made on a
best-effort basis, but there is **no promised response time, support period or guaranteed update**. Fixes come out as
a new release; the fan's page can check for one (Settings → Maintenance → Check for updates), and **Watch → Custom →
Releases** on this repository sends an email when one comes out.

Only the latest release is supported.

## Scope and design

How the design handles each point of the consumer-IoT security baseline ETSI EN 303 645, including what is left out on
purpose and why (plain HTTP inside your Wi-Fi's encryption, USB open to whoever opens the box): see
[SECURITY-CHECK.md](SECURITY-CHECK.md).

Physical access is out of scope: whoever can open the box and connect USB can install any firmware. That is
intentional, so owners keep control of their own fan.

## Software inside

| Component | Version | Where it comes from |
|---|---|---|
| MicroPython | 1.29.0, Bluetooth connection limit raised from 1 to 3 ([patch](micropython/btstack-3-connections.patch)) | <https://micropython.org> |
| BTstack (Bluetooth) and cyw43-driver (Wi-Fi), inside MicroPython | as in MicroPython 1.29.0 | Raspberry Pi / BlueKitchen |
| Microdot (web server) | vendored in `firmware/lib/microdot/` | <https://github.com/miguelgrinberg/microdot> |
| aioble (Bluetooth) | vendored in `firmware/lib/aioble/` | <https://github.com/micropython/micropython-lib> |

A security fix in one of these is taken into a new WattWind release when it affects the fan.
