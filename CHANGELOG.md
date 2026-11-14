# Changelog

What changed in each release, and what builders need to do. Versions follow [semver](https://semver.org): a fix
raises the last number (1.0.1), a new feature the middle one (1.1.0).

## 1.1.0 (2026-11-14)

### Firmware
- **Share heart rate pairs with a Garmin Edge.** Apps and bike computers that ask to pair now pair once, without a
  code, and reconnect by themselves after the fan restarts or loses power (tested with an Edge 1040). The keys are
  kept on the fan; Erase everything deletes them. Settings → Sensors says whether this fan can pair.
- **CORE body temperature sensor** (optional): a third sensor next to strap and trainer. The page shows your core
  temperature and heat strain; **Heat from CORE** (per rider, on by default) keeps the fan at least at level 2 from
  heat strain 3 and at level 3 from 7 while you ride (both values adjustable per rider). The fan sends CORE your strap's heart rate when it has none, and
  reads CORE's temperature from its signal while it isn't connected. Linked fans get the values too.
- New MicroPython file `RPI_PICO2_W-v1.29.0-wattwind-mp2.uf2` ("WattWind MicroPython 2"): the 1.0 file plus Bluetooth
  pairing and room for more connections (`micropython/btstack-pairing.patch`). The fan shows which file it runs
  (the line at the bottom of Settings), and later updates that need a newer file are refused with a clear message before
  anything changes.
- Share heart rate stays one app or watch at a time: with more, the Pico's radio can't reconnect a dropped strap
  (measured).
- **Sensors in Settings:** the chosen sensors show their name, whether they are connected, and their signal (dBm, with
  *weak* below -90); Find sensors shows the signal of connected sensors too.
- **Detailed recording** also keeps a CORE's skin temperature and quality, and the heat settings.
- **Linked fans:** a follower shows the leader's sensors as *HR / power / CORE via …*, and the heart-rate dot only
  while heart rate arrives.
- On the 1.0 MicroPython file with strap, trainer and CORE (all 3 connections in use), Settings → Sensors says that no
  app or watch can connect for Share heart rate.
- Settings opens with every group closed.
- Tested with a real CORE 2: strap, trainer, CORE and a Garmin Edge on Share heart rate at once.

**Builders:** the firmware updates over Wi-Fi as usual and works on the 1.0 MicroPython file too, only without
pairing. For a Garmin Edge, install the new MicroPython file once over USB (box open; settings, riders and the
logbook stay). CORE works on either file; with a CORE, Share heart rate needs the new file (the old one's 3
connections are taken by strap, trainer and CORE).

Release files: the new MicroPython file with its licence texts, the signed update file `wattwind-update-1.1.0.tar`,
and the board's Gerber ZIP and the enclosure print files (unchanged since 1.0.0).

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
