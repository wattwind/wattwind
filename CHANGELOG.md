# Changelog

What changed in each release, and what builders need to do. Versions follow [semver](https://semver.org): a fix
raises the last number (1.0.1), a new feature the middle one (1.1.0).

## 1.0.0 (2026-11-02): first public release

The first published version. Nothing to do for builders: follow the
[build guide](https://wattwind.github.io/wattwind/build.html).

- **Firmware 1.0.0** for the Raspberry Pi Pico 2 W, with the project's MicroPython file
  (`RPI_PICO2_W-v1.29.0-wattwind-ble3.uf2`: MicroPython 1.29.0 with up to 3 Bluetooth connections).
- **Relay board v3.1** (Gerber ZIP `wattwind-v3.1-gerbers.zip`).
- **Enclosure V2** (print files for a Pico soldered on or in 8.5 mm sockets; the Fusion script for other choices).
- **Site and user manual:** <https://wattwind.github.io/wattwind/>.

Release files: the MicroPython file with its licence texts, the Gerber ZIP, the enclosure print files (3MF, STL,
STEP, Fusion archive) and the signed update file `wattwind-update-1.0.0.tar` (for Settings → Maintenance → Firmware
update; a new fan gets its firmware by USB as in the build guide).
