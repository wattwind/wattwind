# Placement plan: WattWind relay board v3.0

**Done 2026-10-10 (v2.0), terminals re-placed 2026-10-11 (v3.0)** (`wattwind.kicad_pcb`, 65 × 82 mm,
DRC clean). Actual layout, board origin at top-left (172.5, 43.0):

| Area | Parts |
|---|---|
| Top edge | H3 (top-left, 4 mm from both edges), J2 (pads in one row at y = 52.2, pin 1 at x = 199.7, wire entry up), "230 VAC / UNPLUG BEFORE TOUCHING", H1 (4 mm from the top edge), J1 (pads at x = 228.3, wire entry to the right edge); HV symbol under H3. Terminal strip ends at y ≈ 57.7; everything below it is the v2.0 layout moved down 2 mm |
| Mains zone | Relays left to right K1, K2, K3, K0 (pins 14 at y = 65.05, pitches 10 / 10 / 6 mm); F1 horizontal under J1; PS1 under F1 |
| Mains / LV boundary | y ≈ 79.8 (dashed line on B.Silkscreen) |
| LV zone | C1, C2, U1, C3 in a row under the relays (U1 outputs under the coils); D1 right of K0; Pico along the bottom edge (USB right); C4, C5 and H2 bottom-left (H2 4 mm from the left and bottom edges) |

Mains routing: J2 → relay pins 14 on F.Cu (fan-out without crossings thanks to the J2 pin order);
chain links in the two 10 mm gaps (F.Cu); `MAINS_A_FUSED` from K3 pin 11 up the K2–K3 gap, across
above the relays to F1, then under PS1 to PS1 pin 1 (B.Cu); `MAINS_B_IN` from J1 under the middle of
the fuse to PS1 pin 2 and K0 pin 11 (F.Cu).

The plan below is the original reasoning; where it differs from the table above, the table wins.

This was a plan only (for v1.0). v2.0 changed the relays (Finder 34.51, 5 mm wide, 28 mm long,
all four single pole), v3.0 the terminals (universal 5.0/5.08 mm); the zone idea below is unchanged. Sizes are approximate. Check every
part against its datasheet (see `bom.md`).

## Idea

The board is split into two zones by one straight boundary:

- **Mains zone** along the **top edge**: both mains terminals, the fuse, and the
  contact side of the relays and PS1.
- **LV zone** along the **bottom edge**: Pico W, driver, low-voltage connectors.
- **Isolation strip ≥ 8 mm** between them. No copper of any kind in the strip, and milled slots
  where parts cross it.

The relays and PS1 **straddle the boundary**: each has its low-voltage pins at one end and its
mains pins at the other, so they are placed with the LV pins pointing down and the mains pins
pointing up. In the library footprints the gap is large: about 9 mm from coil to contact pads
on the Finder 34.51 relays (pins in one line: A2, A1, then 12, 11, 14), and about 25.7 mm from AC to DC pins on PS1.

```
                      TOP EDGE: mains cables
 +--------------------------------------------------------------------------------+
 |  J2 fan out (4-pos)                                    J1 mains in   F1 fuse     |
 |  [COM T1 T2 T3]                                        [A  B]       [=======]   |
 |                                                                                  |
 |   K1        K2        K3        K0                               PS1 AC pins     |
 |  contacts  contacts  contacts  contacts                           o      o      |
 |   o o o     o o o     o o o     o o o                                           |   MAINS ZONE
 |   =slot=    =slot=    =slot=    =slot=                            ==slot==      |   (no pours)
 | - - - - - - - - - - - - - - boundary, 8 mm isolation strip - - - - - - - - - -  |
 |   coil      coil      coil      coil                              PS1 DC pins    |   LV ZONE
 |   o  o      o  o      o  o      o  o                              o      o       |   (GND pour ok)
 |                                                                                  |
 |                                  U1    C3      C1 C2    D1                       |
 |                                                                                  |
 |[antenna]=== Pico W (A1) =========[ USB ]                                 H4    |
 |  ^ left edge, pins 1-20 face up       ^ keep clear for USB plug                 |
 +--------------------------------------------------------------------------------+
                      BOTTOM EDGE: low-voltage connectors
```

## Zones and edges

| Edge / zone | What goes there |
|---|---|
| Top edge (mains) | **J1** mains in and **J2** fan out, wire entry facing out of the board. Keep them close together so both mains cables leave on the same side (one strain relief). |
| Mains zone | F1 next to J1 (the first thing after the terminal). PS1 AC pins. Relay contact pins. |
| Boundary | One straight line with an 8 mm wide strip with no copper on either layer. Draw it on the silkscreen. |
| LV zone | Relay coil pins, U1, C1–C3, D1, Pico W. |
| Left edge (LV corner) | **Pico W antenna end**, flush with or overhanging the board edge. |

## Part by part

- **Relays (updated 2026-10-10).** Pin 11 (COM) sits between pins 14
  and 12, so a 1.5 mm track can only leave it sideways, and only into a gap of ≥ 7.5 mm between
  pad columns (relay pitch ≥ 10 mm) or on the outer side of an end relay. Order left to right
  **K1, K2, K3, K0** at 10 / 10 / 6 mm pitch: the K1–K2 gap carries `CHAIN_K1_COM`, the K2–K3 gap
  carries `CHAIN_K2_COM` (F.Cu) and `MAINS_A_FUSED` from K3 pin 11 (B.Cu), K0 pin 11 leaves on the
  right towards PS1. J2 sits above the relays; its pins read LOW, MED, HIGH, COM left to right
  (pin 1 = COM on the right), in line with K1, K2, K3, K0: a fan-out without crossings.
  U1's outputs (pins 16 → 13) run K0, K1, K2, K3 from left to right, so with the relays in chain
  order some coil tracks cross. That is fine: they are thin LV tracks, use a via or two on B.Cu.
  Don't reorder the relays to suit the coil tracks; that makes the mains tracks longer instead.
- **Relay contact pads (K0–K3):** keep the library 2.4 mm pads. At 5 mm pitch the gap is 2.6 mm,
  allowed by a 2.5 mm DRC exception for relay pads only. Never route a track between them.
- **J1 / J2 (universal 5.0/5.08 mm, v3.0):** one row at 5.04 mm, oval 1.8 × 3.0 mm pads, 3.24 mm
  between neighbouring pads. Don't widen the pads (1.8 mm is the limit for the 3 mm rule).
  Wire entry facing out of the board edge.
- **F1:** right after J1.
- **PS1:** AC pins up (mains), DC pins down (LV). It is tapped before K0, so put it near F1.
- **D1, C1, C2:** between PS1's DC pins and the relay coil row. VSYS runs along the LV side of the
  relays, close to the boundary but outside the 8 mm strip:
  D1 → C1/C2 → relay coil pins (A1) → U1 pin 9, with a branch to Pico pin 39.
  - C1 (100 µF) is the reservoir for the coil switch-on current (~40 mA step) and the flyback
    energy U1 returns to VSYS; without it VSYS can dip and reset the Pico. C2 (100 nF) catches
    the fast spikes C1 is too slow for. Put them side by side near the relays, GND pads straight
    into the pour. **C1 is polarized:** + to VSYS. It is ~11 mm tall: check the enclosure.
- **U1:** centred under the relay coil row. Its outputs (pins 13–16) face the coils and its inputs
  (pins 1–4) face the Pico.
  - **C3** (100 nF) right at the end of U1 by pins 8 (GND) and 9 (COM/VSYS), which sit opposite
    each other at the same end of the DIP: short tracks to both. It gives the coil turn-off
    pulse coming out of COM a short local path to GND.
- **Pico W (A1):**
  - Lay it parallel to the bottom edge, with the **antenna end at the left board edge** and the
    USB end towards the middle. Only this way round does the pin 1–20 row face up towards U1
    (both the Pico and the DIP number their pins counter-clockwise from the top).
  - **No copper (either layer), parts or mounting hole** under or near the antenna. The
    footprint has a keep-out; extend it to the board edge.
  - Leave about 20 mm free on the **USB end** so a micro-USB plug fits.
  - **C4** (100 µF) + **C5** (100 nF) right at pins 39 (VSYS) and 38 (GND), next to each other near
    the USB end, just outside the Pico outline: they buffer Wi-Fi transmit bursts at the far end
    of the long VSYS track, and are the bulk capacitor near the source on USB power. Keep them out
    of the USB plug area and clear of H4. C4 is polarized: + to VSYS.
  - (2026-10-10) Pico pins 20, 19, 16, 15 (GP15, GP14, GP12, GP11) sit right under U1 pins 1, 2,
    5, 6, and pin 18 (GND) under U1 pin 3: all straight vertical tracks (see `netlist.md`).
- **Mounting holes H1, H2, H3 (M3):** see the table at the top. Mains-zone corners only if ≥ 6 mm from
  any mains copper (DRC checks this); use nylon M3 hardware there if closer than 7 mm.

## Milled slots (Edge.Cuts, ≥ 1 mm wide)

| Where | Purpose |
|---|---|
| Under each relay K0–K3, across the body between the coil row and the first contact row (about 7–8 mm from the coil pins), extending 2 mm beyond the pads on both sides | creepage coil ↔ contacts |
| Under PS1, between the AC and DC pin rows | creepage AC ↔ DC |
| Along the boundary between parts, wherever copper on either side comes within about 10 mm of the strip | creepage mains ↔ LV |
| (optional) between `MAINS_A` and `MAINS_B` nets at J1 (5.04 mm pitch, 3.24 mm gap) and between K0 and K3 | extra margin between the two mains conductors |

Draw slots as closed outlines (e.g. rounded rectangles) on Edge.Cuts. JLCPCB's minimum
slot width is about 1 mm; check their current capabilities.

## Copper

- **Mains zone:** no pours on either layer. Mains tracks 1.5 mm (= min), ≥ 3 mm apart. Use both
  layers if needed, but keep every mains via ≥ 8 mm from LV copper.
- **LV zone:** GND pour on B.Cu (and F.Cu if you like), clipped at the 8 mm strip. Draw a
  rule area (keep-out for zones and tracks) over the whole mains zone and the strip, so a pour
  can never spill across.
- VSYS / GND / +5V_PSU / +3V3 ≥ 0.8 mm (net class `LV_Power`).

## Silkscreen

- High-voltage warning in the mains zone: "⚠ 230 VAC: DISCONNECT MAINS BEFORE OPENING", plus
  a lightning-bolt graphic, e.g. `Symbol:Symbol_HighVoltage_Triangle_8x7mm_SilkScreen`. Use a
  `_SilkScreen` variant, not `_Copper`: copper would be netless metal in the mains zone.
- A dashed boundary line along the isolation strip.
- Terminal labels on every pin: J1 pin 1 `B`, pin 2 `A` plus a vertical `MAINS`; J2 pins 1–4 `COM` / `HIGH` / `MED` / `LOW`
  (left to right on the board LOW, MED, HIGH, COM).
- Relay names K0 (MASTER), K1 (LOW), K2 (MED), K3 (HIGH).
- Bottom side (2026-10-10): fan wiring diagram under PS1 (tapped winding: LOW / MED / HIGH taps,
  HIGH nearest the main winding, COM = motor common, each labelled with its J2 pin; the fan's run
  capacitor stays in the fan) and a note under the Pico: 230 VAC 3-speed fan, max 100 W with T1A / 185 W with T2A,
  shaded-pole or PSC, remove the fan's own speed switch.
- F1: fuse rating, "T1A 250V".
- Board name and version: "WattWind relay board v1.0".
