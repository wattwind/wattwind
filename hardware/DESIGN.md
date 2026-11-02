# WattWind relay board: design decisions

Why the board is the way it is. For anyone changing it, reviewing it, or designing their own. The parts are in
`docs/bom.md`, every pin and net in `docs/netlist.md`, the layout in `docs/placement.md`, how to make the Gerbers in
`README.md`.

| Version | Board | Relays | Terminals J1 / J2 |
|---|---|---|---|
| v1.0 | 100 × 100 mm | Omron G2RL-1 / G2RL-2 | Degson 7.5 mm |
| v2.0 | 65 × 80 mm | Finder 34.51 × 4 | Degson DG250-3.5 (staggered 3.5 mm) |
| v3.0 | 65 × 82 mm | Finder 34.51 × 4 | any 5.0 / 5.08 mm single-row terminal |
| **v3.1** | 65 × 82 mm | as v3.0 | as v3.0; only the back silkscreen changed (logo, name, version) |

v1.0 and v2.0 were prototypes and are not published. v3.0 was built and has run a fan since 2026-10-24; v3.1 is
electrically identical.

## Mains circuit

| Decision | Why | Rejected |
|---|---|---|
| **Plug polarity unknown: wires A and B, not L and N** | A Schuko or French plug goes in either way round, so the board can't rely on which wire is live | Assuming L on a fixed terminal |
| **Fan cut on both wires when off.** K0 (single pole) switches wire B; the speed chain switches wire A, and with all speed relays off wire A ends at K1's unused NC contact | Same isolation as a double-pole switch, with four identical single-pole relays. A single welded contact can't run the fan while it is off: two would have to fail | K0 in series with the chain on wire A (the fan's common would stay live) |
| **Speed relays as a priority interlock chain** K3 → K2 → K1 through the NC contacts | Two speed windings can never be powered at once, whatever the software does. That is why the relays must be changeover (SPDT) | Three independent relays guarded only by software |
| **Fuse in wire A** (5×20 mm, ceramic, slow-blow, high breaking capacity): **T1A for fans up to ~100 W, T2A up to 185 W** | T1A: a ~50 W floor fan draws ~0.25 A, with about 2× margin for motor start. 185 W is the Finder 34.51's single-phase motor rating (0.185 kW at 230 VAC, AC15 300 VA): the board's real limit even with a bigger fuse. Tracks and terminals carry more. Where the plug is polarized, put live on A so the fuse and the speed relays sit in it | Glass fuses (low breaking capacity) |
| **120 V: halve the watts** (T1A ~50 W, T2A ~95 W; untested) | Relay contacts care about current, and the same fan draws about twice as much at 120 V. The relay is the same UL-listed part (6 A 250 Vac general purpose, at most 40 °C around it); its motor rating is given for 230 V only | — |
| **Power module tapped before the relays** | The electronics stay powered with the fan off | — |
| **No MOV** | The IRM-02-5 has its own input surge protection and isolates the low-voltage side; a MOV across the input does nothing for contact arcing, and a worn one fails short and blows the fuse | A 275 VAC MOV after the fuse (v1.0) |
| **No RC snubbers, no LEDs** | A floor fan is a small inductive load on 6 A contacts; AC arcs put themselves out; K0 never breaks current (the firmware opens the speed relay first). A load test with a real fan motor showed no problem. State is shown on the web page | Snubber footprints across each winding; relay LEDs |
| **No earth on the board** | The fan keeps its own cord with its protective earth connected inside the fan; the box is plastic and nothing in it is earthed. One 6-core cable runs fan ↔ box | Mains cord into the box and earth joined there (a cable has only one green-and-yellow core, which must not carry anything else) |

## Clearances (rules in `wattwind.kicad_dru`, net classes in `wattwind.kicad_pro`)

| Rule | Value | Why |
|---|---|---|
| Mains ↔ low voltage | **8 mm** clearance and creepage | Reinforced insulation at 250 V (IEC 60664-1, pollution degree 2), with margin |
| Mains ↔ mains (different nets) | 3 mm | Above the 2.5 mm functional creepage at 250 V, PD2, material group III |
| Relay contact pads | 2.5 mm (library pads, 2.6 mm gap) | Functional insulation between COM and NC / NO: 2.5 mm meets IEC 60664-1, and Finder rates the relay at 250 VAC with this pitch. The library pads keep a 0.55 mm ring for hand soldering. The exception applies only pad to pad inside K0–K3 |
| Mains copper ↔ board edge | 3 mm | Enough next to a plastic enclosure; a metal one would need 8 mm |
| Mounting holes ↔ mains copper | ≥ 6 mm from the hole edge | A screw is touchable metal; a metal M3 head or washer reaches 1.2–1.9 mm past the hole, so closer than 7 mm the screw must be nylon (the build uses nylon screws and washers everywhere) |
| Mains tracks | 1.5 mm | Carries several amps; wider tracks would come closer than 3 mm to the neighbouring relay pads |
| Unused relay contacts | get a mains net (`MAINS_K0_NC`, `MAINS_K1_NC`) | They are live metal whenever the relay is off; with a no-connect flag DRC would not protect them |

DRC notes (KiCad 10): the rules use `hasNetclass()` because every net also matches the `LV` pattern `*`; when several
rules match, the last one in the file wins. Run DRC with `--all-track-errors`, or kicad-cli lists only the first
violation per track. Expected results: DRC 0 violations with 3 commented exclusions (F1 library mismatch, Pico outline
at the edge); ERC 4 expected findings (2 × `isolated_pin_label` for the two live NC nets, 2 × power output to power
output on GND, from the Pico's GND / AGND pins and PS1 -Vo). Anything else is a real problem.

## Parts

| Decision | Why | Rejected |
|---|---|---|
| **Finder 34.51.7.005.0010** (SPDT, 5 V sensitive coil 170 mW, AgNi) | Small (5 mm wide), widely stocked, changeover contacts for the interlock, low coil current (~38 mA) | The .5010 gold-flash version (gold only helps at tiny signal loads, at mains it burns off); Omron G2RL (bigger, v1.0) |
| **Toshiba TBD62003APG** relay driver (DIP-16, ULN2003 pin-compatible) | DMOS: about 0.2 V drop instead of ~1 V, so the coils get about 4.5 V from VSYS, well above their must-operate voltage (~3.5 V). Built-in flyback diodes (COM pin to VSYS). 3.3 V GPIO meets its input threshold (V_IH min 2.5 V) | ULN2003 (Darlington drop leaves the coils marginal) |
| **Relay coils and driver on VSYS** (after D1) | The whole board, relays included, works on USB power alone: every stage before mains can be tested on a computer's USB port | Coils on the power module's +5 V only |
| **Mean Well IRM-02-5 + 1N5819 into VSYS** | 5 V 400 mA with reinforced isolation; the Schottky lets USB and the module both be connected (the Pico has its own diode on VBUS). Budget: Pico 2 W ~150 mA + K0 and one speed coil ~80 mA = ~230 mA | — |
| **Universal terminal pads: 5.04 mm pitch, 1.3 mm drill, oval 1.8 × 3.0 mm** | Halfway between the 5.0 and 5.08 mm standards: the outer pin of a 4-pole part is at most 0.12 mm off, inside the hole's play. Screw (Phoenix MKDS, PT, generic) and spring (WAGO 236, 250) parts all fit, and the 3.24 mm pad gap meets the 3 mm rule. The courtyard covers the largest listed part | 5.0 or 5.08 mm only; the staggered DG250-3.5 of v2.0 (sold almost only by one distributor) |
| **Pico soldered on its pin headers** (a Pico 2 WH) | Low, nothing to work loose, fewer parts; female sockets fit the same footprint if wanted (the enclosure script has a parameter for them) | Sockets as the default (+8.5 mm height) |
| **C4 100 µF + C5 100 nF at the Pico's VSYS** | The VSYS track is shared with the relay coils and the next capacitor is far away; local capacitors buffer the Wi-Fi bursts | — |
| **No external pull-downs on the relay inputs** | The GPIOs reset with their pull-downs on, so the relays are off until the firmware runs, and the firmware drives the pins from its first line. On the Pico 2 W (RP2350 erratum E9) a pin released to input can float at ~2 V and hold a relay on, so the firmware never releases them; 4.7 k pull-downs would make that independent of the firmware (an idea for a later revision) | 100 k pull-downs (too weak for E9) |
| **No button, no temperature sensor, no spare header** | Everything is on the web page; the chip's own temperature sensor watches the box | DS18B20 and a push button (v1.0 drafts) |
| **All parts through-hole** | Hand-solderable by anyone; a bare PCB from any maker, no assembly service | SMD with factory assembly |

## Layout (`docs/placement.md`)

| Decision | Why |
|---|---|
| **Two zones split by one straight line**: mains along the top, low voltage along the bottom, the boundary marked on the silkscreen | The 8 mm rule is easy to keep and to see; mains wires in the box stay on the mains half |
| **Relays K1, K2, K3, K0 left to right, 10 / 10 / 6 mm apart; J2 left to right LOW, MED, HIGH, COM** | The two 10 mm gaps carry the chain links; a middle relay's pin 11 is boxed in otherwise. With this J2 order the fan-out from J2 to the relays has no crossings |
| **Relay GPIOs GP15, GP14, GP12, GP11 on driver channels 1, 2, 5, 6** | Pico pins 20, 19, 16, 15 sit straight under driver pins 1, 2, 5, 6, and the driver outputs under the relay coils: every control track short and straight, no vias. The firmware (`firmware/relay.py`) is the source of truth for these numbers; the schematic and `docs/netlist.md` follow it |
| **Pico along the bottom edge, USB at the right edge, antenna end at the left** | Fits 65 × 82 mm; nothing but the board edge near the antenna (copper keep-out under it); USB reachable from the right |
| **J1 → F1 → PS1 stacked at the right edge** | Shortest mains path; wire A runs from F1 under PS1 (between its AC and DC pins) to its input |
| **Three mounting holes, the fourth corner on a post under the Pico** | That corner is taken by the Pico and its USB end; the enclosure supports the board there with a post under the Pico, where the underside has no pads |
| **Board 82 mm long** (v2.0: 80) | Room for the deepest terminal (WAGO 236) at J1 without moving the checked lower half |
| **Wiring diagram, fan limits and the mains / SELV line on the back silkscreen** | Whoever opens the box later sees how it is wired without the docs |

## Schematic

Every connection is a global label (or a GND / +3V3 power symbol) placed directly on the pin, no wires, with net names
exactly as in `docs/netlist.md`, so the schematic can be checked against the netlist net by net. PWR_FLAGs on
`VSYS`, `MAINS_A_FUSED` and `MAINS_B_IN`. U1 uses KiCad's `ULN2003A` symbol with the value TBD62003A (the library has
no TBD62003A symbol). The Pico symbol is the Pico W one: same footprint and pins as the Pico 2 W.

## Enclosure (`enclosure/WattWindEnclosureV2/`)

| Decision | Why | Rejected |
|---|---|---|
| **Lid screwed from underneath** (4 × M3 × 25 through the corner columns into inserts in the lid) | Nothing to unscrew on top: opening needs a tool and taking the box off the fan, as a cover over mains parts should | Screws on top of the lid (V1) |
| **No USB opening by default** | A mains box shouldn't have an opening a child can poke into; updates go over Wi-Fi (signed), and USB jobs are rare. `UsbOpening` = 1 adds one with a press-fit plug | An opening as the default |
| **Generated by a script, checked against the board's 3D model** | Change a number (inserts, sockets, clearances, labels) and the whole box rebuilds and reports any collision | A fixed model |
| **Rating plate engraved underneath**, voltage and fan power following the fuse and the mains voltage | The label always matches the build | — |
| **Flame-retardant (UL94 V-0) filament** | It is a mains enclosure; PLA, PETG, ABS and ASA are HB or not rated | — |
