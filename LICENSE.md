# Licences

WattWind is © 2026 Gediminas Labutis. Different parts of the project are under different licences, each suited to
what it is:

| What | Licence | Full text |
|---|---|---|
| **Software:** `firmware/` (the fan's program and its page), `tools/`, and the MicroPython patch and build script in `micropython/` | MIT | [LICENSE-MIT.txt](LICENSE-MIT.txt) |
| **Hardware and mechanical designs**, in every form they are published in: the relay board (`hardware/`: KiCad schematic and PCB, footprints, Gerbers, the board's 3D model), the enclosure and the fan cable-entry parts (Fusion scripts, Fusion archives, STEP and print files) | CERN-OHL-P v2 | [LICENSE-CERN-OHL-P.txt](LICENSE-CERN-OHL-P.txt) |
| **Documentation and images:** the site and user manual (`docs/`), the Markdown documents, and the project's own photos, renders, drawings and video | CC BY 4.0 | [LICENSE-CC-BY-4.0.txt](LICENSE-CC-BY-4.0.txt) |

All three let you use, change, build and share it; they ask you to keep the copyright notice (and, for CC BY, to
credit the source). There is **no warranty** of any kind: building and using a device that switches mains voltage is
at your own risk. (The site's safety advice still applies: a built unit is not a certified product, so don't sell
built units.)

## Not covered by these licences

- **Third-party code** keeps its own licence: Microdot and aioble (`firmware/lib/`, MIT, their `LICENSE.txt`); the
  signature check in `firmware/ed25519.py` follows the reference code of RFC 8032 (BSD notice in the file).
- **The custom MicroPython file** (a release asset) contains MicroPython (MIT) and Raspberry Pi's Bluetooth (BTstack)
  and Wi-Fi (cyw43-driver) drivers, licensed for use with Raspberry Pi chips only. Their texts are in
  `micropython/LICENSES/` and must go with the file whenever it is passed on.
- **KiCad library 3D models:** the relay model in `hardware/3dmodels/` is KiCad's Finder 34.51 model with its colour
  changed (KiCad libraries: CC BY-SA 4.0 with an exception for designs that use them).
- **Other companies' material:** product names, logos, app icons and screenshots or artwork of their products belong to
  their owners and are marked where they appear. Garmin, Wahoo, Mean Well, Raspberry Pi, Finder and other names are
  trademarks of their owners; this project is not affiliated with or endorsed by them.
- **The WattWind name and logo.** Use them freely on your build, modified or not. If you publish a changed version,
  just say what you changed, so nobody mistakes it for the original.
