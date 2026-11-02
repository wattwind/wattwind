# WattWind against ETSI EN 303 645 (consumer IoT security baseline)

Checked against **ETSI EN 303 645 V3.1.3 (2024-09)**, provision by provision, for firmware 1.0.0 (2026-11).
EN 303 645 is the baseline behind the EU radio rules (EN 18031) and the UK PSTI law. A DIY build isn't bound by
it; this is the yardstick for "what would a good commercial product do". Provision 5.0-1 asks for a recorded
reason for every item not met: that is the "Why" column.

**Shall** = mandatory in the standard, **should** = recommended. Status: **OK** met, **Part** partly met,
**Gap** not met (to do), **Accepted** not met on purpose (reason given), **N/A** doesn't apply.

"Associated services" in the standard means a cloud or app of the maker. WattWind has none: the page is served by
the fan itself, and nothing leaves the home network except the time query (NTP, for logbook times). (Check for
updates is the phone's browser asking GitHub when the button is pressed, not the fan: 5.3-5.)

## 5.1 No universal default passwords

| # | | Status | Why / what |
|---|---|---|---|
| 5.1-1 | shall | OK | The default `wattwind` only exists before the first setup (the factory state the standard allows): the page's setup card makes the user choose an own access point password and PIN before any setting can change, and the password can't be set back to the default. The PIN reset and Erase everything return to that state |
| 5.1-2 | shall | N/A | No pre-installed per-device passwords |
| 5.1-2A | should | OK | Machine-to-machine (linked fans) uses a random 128-bit key from `os.urandom`, not a password |
| 5.1-3 | shall | Part | Link: HMAC-SHA256. PIN and passwords travel over plain HTTP, protected only by the Wi-Fi's WPA2 (see 5.5) |
| 5.1-4 | shall | OK | PIN and access point password can be changed on the page |
| 5.1-5 | shall | OK | Wrong PINs: 2 free, then 1, 2, 4 ... 60 s wait. Wi-Fi password guessing is WPA2's job |

## 5.2 Means to manage reports of vulnerabilities

| # | | Status | Why / what |
|---|---|---|---|
| 5.2-1 | shall | OK | `SECURITY.md`: how to report a problem (GitHub private vulnerability reporting), what is in scope. **No promised timelines**: a best-effort hobby project makes no promises |
| 5.2-2 | should | **Accepted** | No promised time to act on a report: best effort |
| 5.2-3 | should | OK | `SECURITY.md` lists the software inside (MicroPython 1.29 with BTstack and cyw43-driver, Microdot, aioble) and their own security pages |

## 5.3 Keep software updated

| # | | Status | Why / what |
|---|---|---|---|
| 5.3-1, 5.3-2 | should, shall | OK | Every firmware file can be updated from the page, signed and checked (5.3-10). MicroPython itself needs USB |
| 5.3-3 | shall | OK | Settings → Firmware update: pick the file, the fan does the rest |
| 5.3-4A, 5.3-4B | should | **Accepted** | No automatic updates: no server, and a hobby device that updates itself while you ride isn't wanted. The fan keeps working if an update fails (nothing changes until all files check out) |
| 5.3-5 | should | OK | **Check for updates** (Maintenance): the page (the browser, not the fan) asks GitHub for the latest release when pressed and links to it; nothing sent but the request. Plus GitHub's own release emails (Watch → Releases), in the manual. Not automatic: privacy (the fan only asks the internet for the time) |
| 5.3-6A, 5.3-6B | should | N/A | No automatic updates or notifications |
| 5.3-7 | shall | OK | Ed25519 signature over the manifest (RFC 8032; test vectors pass on PC and Pico), SHA-256 per file |
| 5.3-8 | shall | **Accepted** | No promise of timely security updates: best effort, stated on the site |
| 5.3-9 | should | OK | The fan checks the signature with the release public key (`release_key.py`) before staging anything, and that the staged manifest is the signed one; every file is checked against it |
| 5.3-10 | shall | OK | Same: Wi-Fi updates without a valid signature are refused (logbook line). The trust relationship is the public key shipped with the firmware; USB stays open on purpose (5.7-1) |
| 5.3-11 | should | Part | Release notes (CHANGELOG, planned) say what an update fixes |
| 5.3-12 | should | OK | The page says the fan is off during the update; it takes about a minute |
| 5.3-13 | shall | **Accepted** | The site states it plainly: no guaranteed support period and no promise of updates for new problems or threats; best effort |
| 5.3-14, 5.3-15A/B | should | N/A | The software can be updated |
| 5.3-16 | shall | OK | The page shows firmware version and board; the PCB carries the board name and version |

## 5.4 Securely store sensitive security parameters

| # | | Status | Why / what |
|---|---|---|---|
| 5.4-1 | shall | **Accepted** | Wi-Fi password, PIN and link key are plain text in `config.json` on the Pico's flash. Reading them needs the USB port inside the closed box (physical access = owner). The RP2350's flash encryption / secure boot would lock out the builder (decided not to use) |
| 5.4-2 | shall | N/A | No hard-coded per-device identity used for security |
| 5.4-3 | shall | OK | The default `wattwind` in the source is the factory-state password only (5.1-1); it is replaced at first setup. The update-signing key in the source is the *public* key, which is fine there |
| 5.4-4 | shall | OK | Link keys are random per fan. Update checking uses a public key only (nothing secret on the fan) |

## 5.5 Communicate securely

| # | | Status | Why / what |
|---|---|---|---|
| 5.5-1 | shall | **Accepted** | The page uses plain HTTP. HTTPS on the fan would need a self-signed certificate (browser warnings on every visit) and much of the Pico's RAM. The radio link is encrypted by WPA2 (home network or the fan's own access point). Linked fans: AES-128-CBC + HMAC-SHA256 |
| 5.5-2 | should | OK | Crypto from MicroPython's built-in libraries (mbedTLS / hashlib), not home-made |
| 5.5-3 | should | OK | The link packets carry a protocol tag (`WW2`), so a new algorithm can come with a new tag |
| 5.5-4 | should | **Accepted** | Fan buttons and status work without a PIN by default (the fan is used from a phone on the bike). "PIN for the fan buttons" makes them need it |
| 5.5-5 | shall | OK | A settings PIN is required at first setup and can't be removed; settings, Wi-Fi, updates, backup, logbook and erase need it. Before setup, only the setup itself, restore (to move a fan), reboot and erase are open |
| 5.5-6, 5.5-7 | should, shall | **Accepted** | PIN, Wi-Fi password, a backup with secrets and the link key (only during the 60 s pairing window) cross the network in plain HTTP, inside WPA2. Someone already on the home network could capture them; that is the accepted risk of a device without HTTPS |
| 5.5-8 | shall | OK | Link keys: made on the fan, replaced by "Unpair all". Release key: made once on the maker's PC (`tools/make_keys.py`), kept outside the repo, one backup; lost or leaked: a new pair, installed over USB once |

## 5.6 Minimize exposed attack surfaces

| # | | Status | Why / what |
|---|---|---|---|
| 5.6-1 | shall | OK | Open: HTTP 80, UDP 47800 (linked fans), mDNS; DNS 53 only while the access point is up. Bluetooth: a connectable heart-rate sensor (GATT server: Heart Rate Measurement notify + Body Sensor Location read, nothing writable but the notify subscription) only while Share heart rate is on (off by default). No telnet, WebREPL or other debug service on Wi-Fi |
| 5.6-2 | shall | OK | With a PIN set, the logbook, the diagnostics file and the detailed recording (per-second heart rate, started by the user, 24 h, deleted 7 days later) need it (network name, IP, sensor addresses, events). Still open: status (it drives the page and the fan buttons) and `/api/config` (settings without secrets, shown to fill the form) |
| 5.6-3 | should | OK | USB is the only physical interface, inside the box |
| 5.6-4A | shall | **Accepted** | USB REPL (MicroPython's serial console) is the builder's way in: needs opening the box. Stopping the program over USB turns the relays off (update mode) |
| 5.6-4B | should | OK | The USB port is inside the enclosure, behind the USB plug part |
| 5.6-5, 5.6-6 | should | OK | Only the services the fan needs; no unused libraries shipped |
| 5.6-7, 5.6-8 | should | N/A | MicroPython has one process and doesn't use the RP2350's memory protection |
| 5.6-9 | should | OK | Version control, 383 host tests (2026-10-31; main.py and wifi.py too, on a virtual clock), every firmware file compile-tested, manifest check |

## 5.7 Ensure software integrity

| # | | Status | Why / what |
|---|---|---|---|
| 5.7-1 | should | **Accepted** | No secure boot: it would lock builders out of their own device (decided 2026-10-30) |
| 5.7-2 | should | Part | At every start all files are hashed against `manifest.json`; changed files show on the page and in the logbook. It only reports (changes by the owner over USB are normal). Updates over Wi-Fi are signed (5.3-10) |

## 5.8 Ensure that personal data is secure

| # | | Status | Why / what |
|---|---|---|---|
| 5.8-1 | should | Part | Live values (heart rate, power) go to the page over plain HTTP inside WPA2 |
| 5.8-2 | shall | OK | Heart rate counts as health data. The linked-fans packets are encrypted (AES-128-CBC, random IV per packet) and signed (HMAC-SHA256, encrypt-then-MAC); only the fan id and name are readable. The page still uses plain HTTP inside WPA2 (5.5-1). The strap itself sends heart rate unencrypted over Bluetooth (the standard Heart Rate profile; outside WattWind's control). Share heart rate (off by default, opt-in on the page) passes it on the same way, unencrypted like a strap, to one app or watch that connects; the manual's Your data says so. Left open: the key crosses plain HTTP once, in the 60 s pairing window |
| 5.8-3 | shall | OK | The manual lists what it senses: heart rate, power, cadence (Bluetooth sensors), the chip temperature |

## 5.9 Make systems resilient to outages

| # | | Status | Why / what |
|---|---|---|---|
| 5.9-1, 5.9-2 | should | OK | Works without Wi-Fi (sensors and auto keep running), falls back to its own access point, starts with relays off after a power cut, hardware watchdog |
| 5.9-3 | should | OK | Wi-Fi retries back off (2 min, then every 5 min); Bluetooth reconnects back off 5 → 15 s |

## 5.10 Examine system telemetry data

| # | | Status | Why / what |
|---|---|---|---|
| 5.10-1 | should | N/A | The fan sends no telemetry; the logbook stays on the fan |

## 5.11 Make it easy for users to delete user data

| # | | Status | Why / what |
|---|---|---|---|
| 5.11-1 | shall | OK | Settings → **Erase everything** (PIN): config, riders, straps, Wi-Fi, PIN, link keys, logbooks; the fan restarts as new. Without the PIN: delete `config.json` over USB |
| 5.11-2 | should | N/A | No associated services |
| 5.11-3 | should | OK | The manual: Settings → Erase everything, and "Your data" |
| 5.11-4 | should | OK | After the restart the page shows "Everything was erased" (the one-time notice) |

## 5.12 Make installation and maintenance easy

| # | | Status | Why / what |
|---|---|---|---|
| 5.12-1 | should | OK | Captive portal, a few choices, sensors found automatically |
| 5.12-2 | should | OK | The first setup asks for the secure settings itself; the manual explains it |
| 5.12-3 | should | OK | The page warns about the default access point password and while no PIN is set |

## 5.13 Validate input data

| # | | Status | Why / what |
|---|---|---|---|
| 5.13-1A, 5.13-1B | shall | OK | Every setting and API body is checked (types, ranges, lengths); tests pin it. Bluetooth and link packets are parsed defensively (bad packets dropped) |

## 6 Data protection

| # | | Status | Why / what |
|---|---|---|---|
| 6-1 | shall | OK | "Your data" in the manual: what the fan stores (riders' FTP and heart-rate range, strap and trainer addresses, Wi-Fi, logbook without heart rate or power values), that it stays on the fan, what leaves it (the NTP time query, the linked-fans broadcast on the home network, encrypted; with Share heart rate on, the heart rate over Bluetooth to the one app or watch connected, like a strap), the Detailed recording (per-second heart rate and power, only when the user starts it, 24 h, deleted 7 days later) and how to erase it (5.11) |
| 6-2, 6-3A, 6-3B | shall | N/A | No processing based on consent; nothing is sent to the maker or any service. The two things the user turns on (Share heart rate, Detailed recording) are off until chosen, explained next to their switch and in "Your data" |
| 6-4, 6-5 | should, shall | N/A | No telemetry |
| 6-6 | shall | OK | Only what the fan needs is kept; the logbook drops old files by itself and holds no ride data. Ride data is kept only in a Detailed recording the user starts (24 h, deleted 7 days later, or at once with Delete) |
| 6-7, 6-8 | should | N/A | No aggregation or data collection |

## To do (from this check)

| Priority | Item | Provisions |
|---|---|---|
| Done | ~~Signed updates~~ (Ed25519) | 5.3-7, 5.3-9, 5.3-10 |
| Done | ~~First setup asks for an own access point password and a PIN~~ | 5.1-1, 5.4-3, 5.5-5, 5.12-2 |
| Done | ~~Erase everything~~, ~~logbook and diagnostics need the PIN~~, ~~no-PIN hint~~, ~~"Your data"~~ | 5.11, 5.6-2, 5.12-3, 6-1 |
| Done | ~~`SECURITY.md`~~ (how to report, no promised timelines, the software inside) | 5.2-1, 5.2-3 |
| Done | ~~"A newer version exists" check~~ (Check for updates, browser asks GitHub) | 5.3-5 |
| Done | ~~Heart rate in the linked-fans broadcast~~: encrypted | 5.8-2 |
