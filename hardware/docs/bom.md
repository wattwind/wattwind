# BOM: WattWind relay board v3.0 / v3.1

v2.0 (2026-10-09) changed K0–K3 to Finder 34.51; v3.0 (2026-10-11) changed J1/J2 to universal
5.0/5.08 mm terminals; v3.1 only changed the back silkscreen. A v3.0 board was built with exactly these parts
(Finder relays, Phoenix MKDS terminals) on 2026-10-24 and has run the author's fan since: every footprint below fits
them. The **VERIFY** notes matter only if you buy a different part than the one named.

Symbol and footprint names were checked against the libraries installed with KiCad 10.0.6.
All VERIFY items below were checked against the real parts on 2026-10-07 (see `../DESIGN.md`): F1 drills changed to 1.4 mm, F1 locating hole removed (RV1 has since been removed).

**VERIFY** means the footprint exists in the library, but you must check it against the
datasheet of the exact part you buy before ordering the PCB.

LCSC part numbers are not filled in. Everything marked "LCSC: to verify" has to be searched
and checked on lcsc.com / JLCPCB parts before ordering.

Assembly: all parts are **through-hole (TH)** and hand-soldered; there are no SMD parts.

## Mains side (TH)

| Ref | Part | Value / rating | KiCad symbol | KiCad footprint | Notes |
|---|---|---|---|---|---|
| J1 | Terminal block, 2-pos, **5.0 or 5.08 mm**, single row | ≥ 250 VAC, ≥ 10 A, 0.75–2.5 mm² wire | `Connector:Screw_Terminal_01x02` | `WattWind:TerminalBlock_Universal_1x02_P5.04mm_5.0-5.08` (project library) | Default part: **Phoenix Contact MKDS 1,5/2-5,08 (1715721)**, screw, hole 1.3 mm, 250 V (III/3) / 400 V (III/2). Also fits: Phoenix PT 1,5/2-5,0-H (1935161; screw, M2.6, pin 1.0 mm, hole 1.3 mm), WAGO 236-102 (spring, 45°, "5/5.08 mm"), WAGO 250-502 (spring push-in with push-button, 45°, 5.0 mm, 0.75–1.5 mm² stranded without ferrule, 320 V III/3, 17.5 A; pin 0.5 × 0.75 mm, loose in 1.3 mm but solderable; body 8.3 mm behind the pin row, clears H1), generic 5.0 mm screw terminals (Degson DG301-5.0, "KF301-5.0"; check the rating), Metz Connect / Altech / RND 5.0–5.08 mm. Pads at 5.04 mm, drill 1.3 mm, oval 1.8 × 3.0 mm: 3.24 mm gap. Wire side towards the right board edge. **VERIFY** the pin size of the part you buy (pins must fit a 1.3 mm hole; CUI TB007 needs 1.6 mm and does not fit). Screw types: ferrules (0.75 mm², insulated) on stranded wire, never tinned ends; spring types take bare stranded wire. Wiring notes in `../README.md`. |
| J2 | Terminal block, 4-pos, **5.0 or 5.08 mm**, single row | as J1 | `Connector:Screw_Terminal_01x04` | `WattWind:TerminalBlock_Universal_1x04_P5.04mm_5.0-5.08` | Default part: **Phoenix Contact MKDS 1,5/4-5,08 (1715747)**. Same alternatives (PT 1,5/4-5,0-H 1935187, WAGO 236-104, WAGO 250-504, generic) and **VERIFY** as J1; outer pins of a 5.0 or 5.08 mm part land 0.12 mm off the pads, inside the hole play. Pin 1 = COM (right), then HIGH, MED, LOW. Wire side towards the top board edge. |
| F1 | Fuse holder 5×20 mm, PCB mount + fuse | 250 VAC; fuse **T1A 250 V**, slow-blow, ceramic body (high breaking capacity, marked "H"), for fans up to ~100 W; **T2A** for fans up to 185 W (relay motor rating, the board's limit) | `Device:Fuse` | `Fuse:Fuseholder_Cylinder-5x20mm_Schurter_0031_8201_Horizontal_Open` | Checked with the part: pin pitch 22.5 mm OK. The real holder has **no locating pin**, so the footprint's 2.7 mm NPTH in the middle is unused (harmless; may be deleted on the board). Legs measured 1.15 mm, too tight for the 1.3 mm drill: set both pad drills to **1.4 mm** on the board (pads stay 3 × 3 mm). Many generic "BLX-A" holders have a different pitch or no locating pin. An open holder should get a snap-on cover. Closed alternative: `Fuse:Fuseholder_Cylinder-5x20mm_Schurter_FAB_0031-355x_Horizontal_Closed`. LCSC: to verify |
| PS1 | Mean Well IRM-02-5 | 5 V 400 mA, 85–264 VAC in, reinforced isolation | `Converter_ACDC:IRM-02-5` | `Converter_ACDC:Converter_ACDC_MeanWell_IRM-02-xx_THT` | **VERIFY** against the Mean Well drawing: AC pins 15.2 mm apart, AC to DC side 28.0 mm, DC pins 7.6 mm apart, pin drills 0.8 / 0.76 mm. LCSC: to verify |
| K0 | Finder **34.51.7.005.0010** | SPDT, 6 A 250 VAC, 5 V DC sensitive coil 170 mW (130 Ω, ~38 mA), AgNi contacts | `Relay:FINDER-34.51` | `WattWind:Relay_SPDT_Finder_34.51_Vertical` (= `Relay_THT` footprint, white 3D model) | Master relay, now **single pole**: switches MAINS_B only (the speed chain switches MAINS_A). Contact pads stay at the library 2.4 mm (2.6 mm gap at 5 mm pitch; allowed by a 2.5 mm DRC exception for relay pads only). **VERIFY** the pin grid against the Finder 34 datasheet: coil pins 3.75 mm apart, contacts 12/11/14 at 11.25 / 16.25 / 21.25 mm from A1, drills 1.0 / 1.3 mm. Must-operate ≈ 0.7 × 5 V = 3.5 V; coil sees about 4.5 V (VSYS minus U1's drop). Plain AgNi contacts (the .5010 gold-flash version only helps for tiny signal loads; at mains the gold burns off). LCSC: to verify |
| K1, K2, K3 | Finder **34.51.7.005.0010** | as K0 | `Relay:FINDER-34.51` | `WattWind:Relay_SPDT_Finder_34.51_Vertical` (= `Relay_THT` footprint, white 3D model) | **Must be SPDT (changeover, 34.51)**: an SPST-NO version has no NC contact, which breaks the interlock chain. Same pad edit and **VERIFY** as K0. LCSC: to verify |

## Low-voltage side

| Ref | Part | Value / rating | KiCad symbol | KiCad footprint | Assy | Notes |
|---|---|---|---|---|---|---|
| A1 | Raspberry Pi **Pico 2 W**, soldered directly on its 2× 1×20 pin headers | | `MCU_Module:RaspberryPi_Pico_W` | `Module:RaspberryPi_Pico_Common_THT` | TH | The symbol's default footprint is the SMD version, so change it. This footprint has 40 TH pads (drill 1.0 mm) and an antenna keep-out. **VERIFY** that the keep-out covers the Pico W antenna area. Buy a Pico 2 WH (headers pre-soldered) or a Pico 2 W plus 2× 1×20 2.54 mm male headers, and solder it onto the board (the older Pico W has the same footprint but is not supported). RP2350 erratum E9: a relay pin left floating can hold a relay on; the firmware never releases them (a later board revision may add 4.7 k pull-downs). Female header sockets also fit (Pico removable), but raise it ~8.5 mm: set the enclosure's user parameter `PicoSocketHeight`. |
| U1 | Toshiba **TBD62003APG**, 7-ch DMOS sink driver, DIP-16 | 50 V, 500 mA/ch, built-in clamp diodes | `Transistor_Array:ULN2003A` (pin-compatible; set the value to TBD62003A) | `Package_DIP:DIP-16_W7.62mm` | TH | Chosen over the ULN2003A for its low output drop (about 0.2 V instead of about 1 V), which keeps about 4.5 V on the coils. The library has no TBD62003A symbol. A DIP-16 socket is optional (the footprint fits one). **VERIFY** in the datasheet that the input "on" threshold is met by 3.3 V GPIO. TME/LCSC: to verify |
| D1 | 1N5819 Schottky | 1 A, 40 V | `Diode:1N5819` | `Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal` | TH | Cathode band towards VSYS. TME/LCSC: to verify |
| C1, C4 | Electrolytic capacitor | 100 µF, ≥ 16 V | `Device:C_Polarized` | `Capacitor_THT:CP_Radial_D6.3mm_P2.50mm` | TH | **VERIFY** the can diameter and lead pitch. LCSC: to verify |
| C2, C3, C5 | Ceramic capacitor | 100 nF, 50 V, X7R | `Device:C` | `Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm` | TH | **VERIFY**: lead pitch 5.0 mm (many MLCCs are 5.08 or 2.54 mm; both 5.0/5.08 fit). TME/LCSC: to verify |
| H1, H2, H3 | Mounting hole M3 | | `Mechanical:MountingHole` | `MountingHole:MountingHole_3.2mm_M3` | — | NPTH. Keep ≥ 6 mm from mains copper (a DRC rule checks this); nylon screw and washer if closer than 7 mm. |

## Off-board

| Part | Notes |
|---|---|
| Cable fan ↔ box | 6 cores, 0.75 mm², 300/500 V flexible **power** cable (not LiYY-type control cable: those are signal cables, often 300/300 V), **without the green-and-yellow striped earth core** (plain green or yellow cores are fine; e.g. Lapp ÖLFLEX CLASSIC 110 6 X 0.75, YSLY-OZ 6 × 0.75): L, N to J1; COM, LOW, MED, HIGH from J2. The fan keeps its own cord with PE connected inside the fan; no earth in the box. With a 7G cable: the green-and-yellow core to PE at the fan end, insulated (end cap / Wago) in the box, never used for anything else |
| Enclosure | must be insulating, or earthed with the board fully covered; strain relief on the cable (M16 gland; cable diameter within its clamping range) |

## Power budget (5 V)

| Load | Current |
|---|---|
| Pico 2 W (Wi-Fi + BLE active) | up to ~150 mA |
| K0 coil + one speed relay coil (the firmware never energizes more) | 2 × ~38 mA = ~80 mA |
| **Total** | **~230 mA**, within the IRM-02-5's 400 mA and a USB port's 500 mA |
