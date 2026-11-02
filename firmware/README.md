# How the WattWind firmware works

For developers. Users and builders: the [user manual](www/help.html) and the project site.

MicroPython on a Raspberry Pi Pico 2 W, about 4,700 lines of Python, no frameworks besides two small vendored
libraries (`lib/`: Microdot for the web server, aioble for Bluetooth). Everything except the hardware glue is plain
Python and is tested on a PC with pytest.

## The big picture

```
 heart-rate strap ─┐  Bluetooth                         Wi-Fi           phone / browser
 smart trainer ────┴──────────► ble_sensors ─┐                  ┌──────── web (Microdot, JSON API, the page)
                                             ▼                  ▼
   link (linked fans, UDP) ───────────►  state  ◄──────────  config / profiles (config.json)
                                             │
                                             ▼
                              control: fan_logic ──► relay.set_level()  ──► 4 relays ──► fan
                                             ▲
                     main: supervisor + hardware watchdog (resets if a critical task stops)
```

- **One asyncio task per job**, all started by `main.py`: `control` (the only one allowed to switch relays),
  `ble`, `wifi`, `web`, `link`, `console` (USB serial commands), plus a one-off file check.
- **They share one module, `state`**: sensor values, mode, level, Wi-Fi status, diagnostics. Tasks write what they
  own and read the rest; no locks are needed because asyncio switches tasks only at `await`.
- **Every task runs inside `supervised()`**: an exception is logged and the task restarts after 5 s. `control` is
  *critical*: it isn't restarted; instead its heartbeat stops, and the supervisor resets the Pico.
- **The supervisor loop** in `main()` feeds the 8 s hardware watchdog once a second, but only while every critical
  task has reported a heartbeat within 3 s. A frozen program (no `await`) is reset by the watchdog itself.
- **Relays are off at every start**: the first two lines of `main.py` import `relay` and call `relay.init()`, before
  anything that could fail.

## Modules

| File | Owns |
|---|---|
| `main.py` | boot sequence, update mode, applying a staged update, the quick-plug-in PIN reset, task supervision, watchdog, status log |
| `relay.py` | the relay pins; the **only** code that switches them (`set_level()`) |
| `fan_logic.py` | Auto: power / heart-rate scores, smoothing, thresholds, dwell times, stop and sensor-loss handling, nudge. Pure Python |
| `ble_sensors.py` | Bluetooth central: scans, connects heart rate + power at the same time, reconnects, picks the rider by strap |
| `ble_share.py` | Share heart rate (setting `hr_share`, off by default): the fan as a Bluetooth heart-rate sensor for one app or watch, passing on the strap's notifications |
| `ble_parse.py` | parsing of Heart Rate (0x2A37), Cycling Power (0x2A63) and FTMS Indoor Bike Data (0x2AD2) notifications; cadence from crank revolutions |
| `wifi.py` | home network, own access point as fallback, retries, mDNS hostname |
| `dns.py` | captive-portal DNS on the access point (every name resolves to the fan) |
| `web.py` | Microdot routes and JSON API (the setting rules are in `checks.py`); `FanApp` closes a connection that doesn't send its request within 10 s (or take its answer within 2 min), so stalled clients can't use up the Pico's few sockets |
| `link.py` | linked fans: leader broadcast, follower listening, pairing |
| `updater.py` | firmware update from the page: staging, checking, applying |
| `integrity.py` | SHA-256 check of every firmware file against `manifest.json` |
| `config.py` / `profiles.py` | settings in `config.json` with defaults; up to 5 rider profiles mirrored into the top-level settings |
| `checks.py` | the rules every setting must meet (used by the page, restore, and `sanitize()` at each start: a saved value that fails goes back to its default and the page names it). With main.py's crash counter (`crash_boots.txt`): after 3 error restarts in a row a safe start with default ride settings, nothing saved, so the page stays reachable |
| `detail.py` | Detailed recording (Settings → Maintenance), for finding a problem: 24 h of one line per second while riding (power, cadence, HR, level, target, mode, strap off), a minute line (time, free memory, the longest delay of the 100 ms control loop, Wi-Fi, chip, linked-fans packets), events (sensor data gaps over 2 s, level changes with the reason, restarts) and the settings fan_logic needs, so a ride can be replayed on the PC. Own two files (256 KB each, 1/6 of free flash at most), batched writes every 10 s, continues after a restart (`detail.json`), deleted 7 days of running after the end; a firmware update short of space deletes it |
| `logbook.py` | `log.txt` on flash: every start with its reason, every fan level change with its reason (`fan_logic.why`), a status line every 5 minutes while mode, level, Wi-Fi or a sensor changes (else every 30), Wi-Fi and sensor events, task crashes (error and line), page buttons, settings saved (names only), why the fan turned itself off, update results, security events (rate-limited); 128 KB, one old file kept (a full file replaces the older one: 4.5-9 busy days, weeks idle; LittleFS spreads the writes, so no flash wear concern). `GET /api/diagnostics` bundles it with status, settings (no secrets), flash, RAM and Wi-Fi state |
| `console.py` | USB serial commands for bench tests (`0`–`3`, `a`, `s`), non-blocking |
| `state.py`, `version.py` | shared runtime state; firmware version |
| `www/` | the page (`index.html`, plain HTML / CSS / JS, no external resources), the manual, the home-screen icon |

## Relay safety

The board has a master relay K0 (one mains wire) and three speed relays wired as an interlock chain K3 → K2 → K1
(the other wire): two speed windings can never be live at once, whatever the software does. On top of that:

- `relay.init()` sets each pin's value **before** making it an output, so no pin glitches high.
- `set_level()` switches **break-before-make**: all speed relays off, 100 ms, then the new one. From off: K0 first,
  100 ms, then the speed relay; to off the other way round. It blocks for those 100 ms on purpose.
- At most one level change per 2 s (`ms_until_allowed()`), in every mode.
- **Relay pins are never released (switched to input).** On the RP2350, erratum E9 keeps a released pin that was
  high at about 2 V, and that holds the relay on (measured on the board). A reset clears it.

## Auto (`fan_logic.py`)

Once per second, `FanLogic.update(now_s, power, cadence, hr)` returns the target level. Time is a parameter, so tests
simulate whole rides in milliseconds.

- **Scores:** `p_score = smoothed power / FTP`; `hr_score = (hr - rest) / (max - rest)`. Power uses an exponential
  moving average with two time constants (fast up, slow down: 12 s / 75 s with the Normal response). `demand` is the
  higher score, or only one of them if the rider's `use` setting says so; a missing sensor falls back to the other.
- **Levels** step one at a time with hysteresis (defaults up 0.45 / 0.70 / 0.88, down 0.38 / 0.63 / 0.81) and dwell
  times (15 s before up, 60 s before down).
- **Stopped** (cadence 0 or under 20 W for 5 s): hold, then one level down per minute. **Both sensors lost:** hold
  2 minutes, then step down. **Idle off** after 15 minutes without riding.
- **Nudge** (−2…+2 levels for this ride) and **maximum level** are applied on top; a + never starts the fan while
  you're not riding.

`tools/make_ride_chart.py` runs a workout through this code to draw the chart on the site.

## Bluetooth (`ble_sensors.py`)

aioble as a central. The fan needs **two connections at once** (strap and trainer), but MicroPython 1.29 compiles
BTstack with room for one; the project's own UF2 (`../micropython/`) raises it to 3 and changes nothing else.
Sensors are remembered by address, notifications older than 5 s count as missing, and reconnects back off
5 → 15 s. A heart-rate strap taken off may keep sending its last value for minutes (seen in the ride test), so
`ble_parse.HrContact` judges "worn" from what the sensor reports: the Heart Rate Measurement's sensor-contact bits
("not detected" = not worn, at once), else the RR intervals (a sensor that has sent them, remembered per address in `hr_rr` across reconnects and restarts,
and sends none for 5 s = not worn; worn again after RR intervals in 3 messages in a row, so a stray one doesn't count), else nothing (the 5 s rule and the disconnect). `fan_logic.basis` says which score decided
(power / hr / both), shown on the page next to demand. While a firmware update is coming in, the search pauses so Wi-Fi has the radio.

**Share heart rate (`ble_share.py`)**, off by default: the fan also acts as a peripheral (aioble `peripheral.py` +
`server.py`): Heart Rate service 0x180D with Heart Rate Measurement (notify) and Body Sensor Location (chest),
advertised as `WattWind-XXXX HR` (the link id + " HR", appearance 0x0341; the same name as GAP Device Name
0x2A00, which apps show after connecting: MicroPython's default there is "MPY BTSTACK"). `ble_sensors.on_hr` hands every fresh
strap notification to `ble_share.send()`, unchanged (beat times included); nothing while the strap is off or missing.
One receiver: no advertising while one is connected, so strap + trainer + receiver = the build's 3 connections.
BTstack switches advertising back on by itself when a connection ends (measured), so while sharing is off the task
stops it again for 5 s. Other fans never take a `WattWind… HR` name as their strap (`ble_share.is_share`). Not on a
follower; paused during a firmware update. No pairing / bonding: MicroPython 1.29 builds BTstack on the rp2 without
`MICROPY_PY_BLUETOOTH_ENABLE_PAIRING_BONDING` (only the NimBLE build has it), so the fan never answers a pairing
request. Receivers that connect without pairing work (MyWhoosh, Wahoo Bolt V2 / Roam V2); a Garmin Edge 1040
connects, gets data, then reports "pairing failed" (2026-11-02). Status: `hr_share` (off / waiting / connected), `hr_share_name`.

## Linked fans (`link.py`)

A leader broadcasts one UDP packet per second on port 47800: `WW2 <mac> <iv> <secret> <public>`. `<public>` is JSON
with the fan id and name only (every fan lists the leaders it hears, also before pairing). `<secret>` is JSON with
boot id, sequence number, level, heart rate, power, cadence and sensor state, encrypted with AES-128-CBC (MicroPython's
`cryptolib`, mbedTLS; PKCS#7 padding) under a fresh random 16-byte `<iv>` (both hex). `<mac>` is HMAC-SHA256 over
everything after it (encrypt-then-MAC; first 128 bits, hex) and is checked before anything is decrypted. Both keys come
from the pairing key: the HMAC uses it directly, AES uses HMAC(key, "WattWind link AES-128")[:16]. A follower accepts
only packets from its leader, signed with that key, and newer than the last one (boot id + sequence: no replays).
`WW1` (an older, unencrypted format from before 1.0.0, never released) is still listed but never followed. The host tests replace `cryptolib`
with `tests/cryptolib_standin.py`, which passes the same NIST SP 800-38A vector as the Pico. Silence for 5 s counts as sensor loss; same-level
followers then hold 60 s and step down one level a minute (`FollowLevel`). Pairing: the leader opens a 60 s window in
which `GET /api/link/key` answers; the follower fetches the key from the address it heard. "Unpair all" gives the
leader a new key.

## Firmware update over Wi-Fi (`updater.py`)

1. The page reads the release `.tar` in the browser and sends the new `manifest.json`. The fan compares it with its
   own and answers which files differ; only those are sent, in 4 KB pieces, into `update/`. Running files aren't
   touched, the fan is off and the Bluetooth search paused meanwhile; each piece is retried up to 5 times.
2. `finish()` checks every staged file **and every kept file** against the new manifest. Only if all match does it
   write `update_apply.json` and restart.
3. At the next start, before anything else is imported, `apply()` moves the staged files into place,
   `updater.py` and `manifest.json` last. A power cut halfway leaves the marker, so the next start finishes the job.

**Check for updates** (page only, not the fan): the browser asks `api.github.com/repos/<REPO>/releases/latest` (`wattwind/wattwind`)
when the button is pressed and compares the tag with the fan's version (`vcmp`, test versions count older). `REPO` is a
constant in `www/index.html`: a fork sets its own.

Flash: the Pico 2 W has about 2.5 MB for files; the firmware is about 460 KB, so even a full update fits.

## Web security

- **DNS rebinding:** on the home network the fan answers only requests addressed to its own names (its hostname, with
  `.local` or a usual router suffix, or its IP); others get 421. In access-point mode every name is answered, for
  the captive portal.
- **CSRF:** every command needs a JSON body (`application/json`); Microdot ignores other bodies, and the fan sends no
  CORS headers, so a foreign website can't make the browser send a command. Tests in `test_web.py` pin both.
- **PIN guessing:** two wrong PINs are free, then each try waits 1, 2, 4 … 60 s.
- **Private reads:** with a PIN set, the logbook and the diagnostics file need it too (`X-Pin` header); status stays open.
- **Erase everything** (`POST /api/erase`): `main.py` turns the fan off, deletes `config.json`, the logbooks and the
  quick-boot count, and restarts as new; `erased.txt` makes the page say so once.
- The whole check against ETSI EN 303 645, item by item, is in `SECURITY-CHECK.md` at the repo root.
- **Signed updates**: `make_update.py` signs `manifest.json` (Ed25519, the bytes as packed) and adds
  `manifest.sig`; the page sends the manifest text and the signature; `updater.verified_manifest()` checks it with
  the public key in `release_key.py` (`ed25519.py`: pure Python with its own SHA-512, ~1 s on a Pico 2 W) before
  anything is staged, and `finish()` checks that the staged `manifest.json` is byte for byte the signed one. Every file
  is then checked against that manifest, as before. Keys: `tools/make_keys.py` (private key outside the repo, path in
  the git-ignored `tools/signing_key_path.txt`); `tools/ed25519_sign.py` signs with the same curve code, checked
  against the RFC 8032 vectors. USB stays open (physical access = owner), so changing makers is one USB install.

## Other details

- **Update mode:** plugging in USB changes nothing; a Ctrl-C over the serial port does (Thonny, mpremote and
  MicroPico send one when they connect). `main()` gets a `KeyboardInterrupt`: relays off, `update_mode.txt` written,
  logbook line, `machine.reset()`. At the next start the flag plus a reset cause other than `PWRON_RESET` means
  update mode: nothing is started (no tasks, radio or watchdog), relays stay off, the REPL waits, so files can be
  copied without the watchdog resetting halfway. A power-up (all power off: USB *and* mains) deletes the flag; from
  a computer: `os.remove('update_mode.txt'); machine.reset()`. The next start reports *end of update mode*.
  To watch the running fan, use a serial terminal that sends no Ctrl-C (miniterm, PuTTY): the 1 s status line,
  plus the console keys of `console.py`. MicroPico's auto-connect stops the fan: this repo turns it off
  (`.vscode/settings.json`).
- **Soft reboot** (Ctrl-D, or a tool running a file): the CYW43 radio would still be on and BLE would hang, so
  `main.py` turns it into a hard reset first.
- **Quick plug-in reset:** three power-ups shorter than 10 s, then a fourth, reset the PIN and access point
  password (`quick_boots.txt`, counted only on real power-on resets).
- **File check:** at start every file is hashed (text files without `\r`, so Windows and Unix line endings match)
  and compared with `manifest.json`; the result is shown on the page and logged. It only reports.

## Working on it

```
cd firmware
python -m pytest tests          # host tests (fan_logic rides, parsing, web API, linked fans, updater, docs,
                                # main.py's boot and control loop and wifi.py on a virtual clock: tests/mpy_sim.py)
python ../tools/make_manifest.py   # after every change, before copying files to the Pico
python ../tools/make_update.py     # the .tar for "Firmware update" on the page (dist/)
```

Copy files with Thonny or `mpremote` (connecting puts the fan in update mode). Bump `version.py` with every upload,
so the page and the logbook show which build runs. `fan_logic.py`, `ble_parse.py`, `link.py` (its pure parts),
`updater.py`, `integrity.py`, `profiles.py` and `config.py` import nothing MicroPython-specific, which keeps them
testable on a PC.
