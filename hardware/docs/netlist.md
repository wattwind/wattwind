# Netlist: WattWind relay board v3.0

Every part, pin and net. Use it to draw the schematic, then tick off each net against the
finished schematic (section 3).

Net classes are assigned automatically by net-name patterns in `wattwind.kicad_pro`, so
**use exactly these net names**. `GND` and `+3V3` have library power symbols (`power:GND`,
`power:+3V3`). Use global labels for everything else, including `VSYS` and `+5V_PSU`.

| Net class | Nets | Rules |
|---|---|---|
| **Mains** | `MAINS_A_IN`, `MAINS_A_FUSED`, `MAINS_B_IN`, `MOTOR_COMMON`, `CHAIN_K2_COM`, `CHAIN_K1_COM`, `TAP1`, `TAP2`, `TAP3`, `MAINS_K0_NC`, `MAINS_K1_NC` | track 1.5 mm (= min), 3 mm between mains nets (2.5 mm pad to pad within K0–K3), 3 mm to the board edge, 8 mm clearance and creepage to everything else |
| **LV_Power** | `VSYS`, `+5V_PSU`, `GND`, `+3V3` | track ≥ 0.8 mm |
| **LV** | everything else | track 0.3 mm |

> **Unused relay contacts get a net, not a no-connect flag.** K0's NC contact and K1's NC
> contact are live mains metal (each one touches its COM whenever the relay is off). If they
> have a `MAINS_*` net, DRC keeps 8 mm between them and the LV side. With a no-connect flag they
> would have no net and DRC would not protect them. Put a global label on each of these pins;
> nothing else connects to it.

Pin numbers below are the **KiCad symbol pin numbers** (checked in KiCad 10.0.6 libraries).
Relay numbering (Finder 34.51, symbol `Relay:FINDER-34.51`): `11` = COM, `12` = NC, `14` = NO, `A1`/`A2` = coil.

## 1. Mains side

### J1: mains input, 2-pos terminal, 5.0/5.08 mm (e.g. Phoenix MKDS 1,5/2-5,08) (`Connector:Screw_Terminal_01x02`)
| Pin | Net |
|---|---|
| 1 | `MAINS_B_IN` |
| 2 | `MAINS_A_IN` |

### F1: fuse, 5×20 mm slow-blow (`Device:Fuse`)
| Pin | Net |
|---|---|
| 1 | `MAINS_A_IN` |
| 2 | `MAINS_A_FUSED` |

### PS1: Mean Well IRM-02-5 (`Converter_ACDC:IRM-02-5`)
| Pin | Symbol name | Net |
|---|---|---|
| 1 | AC/N | `MAINS_A_FUSED` |
| 2 | AC/L | `MAINS_B_IN` |
| 3 | -Vo | `GND` |
| 4 | +Vo | `+5V_PSU` |

The AC input is not polarity-sensitive; the L/N names on the symbol don't matter here.

### K0: master relay, Finder 34.51.7.005.0010, SPDT (`Relay:FINDER-34.51`)
K0 switches MAINS_B; the speed chain (K3 → K2 → K1) switches MAINS_A. When everything is off,
both fan wires are disconnected.

| Pin | Function | Net |
|---|---|---|
| 11 | COM | `MAINS_B_IN` |
| 14 | NO | `MOTOR_COMMON` |
| 12 | NC (unused) | `MAINS_K0_NC` |
| A1 | coil + | `VSYS` |
| A2 | coil − | `K0_COIL` |

### K3: HIGH speed, Finder 34.51.7.005.0010, SPDT (`Relay:FINDER-34.51`)
| Pin | Function | Net |
|---|---|---|
| 11 | COM | `MAINS_A_FUSED` |
| 14 | NO | `TAP3` |
| 12 | NC | `CHAIN_K2_COM` |
| A1 | coil + | `VSYS` |
| A2 | coil − | `K3_COIL` |

### K2: MEDIUM speed, Finder 34.51.7.005.0010, SPDT (`Relay:FINDER-34.51`)
| Pin | Function | Net |
|---|---|---|
| 11 | COM | `CHAIN_K2_COM` |
| 14 | NO | `TAP2` |
| 12 | NC | `CHAIN_K1_COM` |
| A1 | coil + | `VSYS` |
| A2 | coil − | `K2_COIL` |

### K1: LOW speed, Finder 34.51.7.005.0010, SPDT (`Relay:FINDER-34.51`)
| Pin | Function | Net |
|---|---|---|
| 11 | COM | `CHAIN_K1_COM` |
| 14 | NO | `TAP1` |
| 12 | NC (end of chain) | `MAINS_K1_NC` |
| A1 | coil + | `VSYS` |
| A2 | coil − | `K1_COIL` |

### J2: fan output, 4-pos terminal, 5.0/5.08 mm (e.g. Phoenix MKDS 1,5/4-5,08) (`Connector:Screw_Terminal_01x04`)
| Pin | Net | Fan wire |
|---|---|---|
| 1 | `MOTOR_COMMON` | common |
| 2 | `TAP3` | HIGH |
| 3 | `TAP2` | MEDIUM |
| 4 | `TAP1` | LOW |

> J2 pin order (v3.0, 2026-10-11): the single-row terminal reads LOW, MED, HIGH, COM from left
> to right on the board, in line with K1, K2, K3, K0, so the fan-out routes without crossings
> (v2.0 had pin 1 = TAP3, pin 2 = COM for its staggered terminal). J1 polarity is unknown anyway,
> so its pin order changes nothing electrically.

## 2. Low-voltage side

### A1: Raspberry Pi Pico 2 W, soldered directly on its pin headers (`MCU_Module:RaspberryPi_Pico_W`)
GPIO assignments come from the firmware (`firmware/relay.py`). If you change one here, change the firmware too.

| Pin | Name | Net | Firmware |
|---|---|---|---|
| 20 | GPIO15 | `RELAY_K1_IN` | `relay.SPEED_PINS[0] = 15` |
| 19 | GPIO14 | `RELAY_K2_IN` | `relay.SPEED_PINS[1] = 14` |
| 16 | GPIO12 | `RELAY_K3_IN` | `relay.SPEED_PINS[2] = 12` |
| 15 | GPIO11 | `RELAY_K0_IN` | `relay.K0_PIN = 11` |
| 3, 8, 13, 18, 23, 28, 38 | GND | `GND` | |
| 33 | AGND | `GND` | |
| 36 | 3V3 | `+3V3` | 3.3 V output (max ~300 mA) |
| 39 | VSYS | `VSYS` | power input |
| 40 | VBUS | no connect | USB 5 V, reaches VSYS through the Pico's own diode |
| 30 | RUN | no connect | |
| 35 | ADC_VREF | no connect | |
| 37 | 3V3_EN | no connect | |
| all other GPIOs | | no connect | GP23, GP24, GP25, GP29 are internal on the Pico 2 W and not on the header |

### D1: 1N5819 Schottky, PSU into VSYS (`Diode:1N5819`)
| Pin | Name | Net |
|---|---|---|
| 2 | A | `+5V_PSU` |
| 1 | K | `VSYS` |

### U1: TBD62003A relay driver (symbol `Transistor_Array:ULN2003A`, pin-compatible)
| Pin | Name | Net |
|---|---|---|
| 1 | I1 | `RELAY_K1_IN` |
| 2 | I2 | `RELAY_K2_IN` |
| 3, 4 | I3, I4 | `GND` |
| 5 | I5 | `RELAY_K3_IN` |
| 6 | I6 | `RELAY_K0_IN` |
| 7 | I7 | `GND` |
| 8 | GND | `GND` |
| 9 | COM | `VSYS` (enables the built-in flyback diodes, required) |
| 10 | O7 | no connect |
| 11 | O6 | `K0_COIL` |
| 12 | O5 | `K3_COIL` |
| 13, 14 | O4, O3 | no connect |
| 15 | O2 | `K2_COIL` |
| 16 | O1 | `K1_COIL` |

Channels chosen for the layout (2026-10-10, revised): U1 sits so its pins 1, 2, 3, 5, 6 are
exactly above the Pico's pins 20, 19, 18, 16, 15 (GP15, GP14, GND, GP12, GP11): the four control
tracks and the GND tie for the unused inputs are straight vertical drops. Channels 1, 2, 5, 6 drive
K1, K2, K3, K0; O5 sits just right of K3's coil, so the coil tracks stay short.

### Decoupling
| Ref | Part | + / pin 1 | − / pin 2 | Where |
|---|---|---|---|---|
| C1 | 100 µF electrolytic | `VSYS` | `GND` | near the relay coils |
| C2 | 100 nF | `VSYS` | `GND` | near the relay coils |
| C3 | 100 nF | `VSYS` | `GND` | next to U1 pin 9 (COM) and pin 8 (GND) |
| C4 | 100 µF electrolytic | `VSYS` | `GND` | at the Pico, short tracks to A1.39 (VSYS) and A1.38 (GND) |
| C5 | 100 nF | `VSYS` | `GND` | as close as possible to A1.39 / A1.38 |

### H1, H2, H3: M3 mounting holes (`Mechanical:MountingHole`), no net.
H1 top (4 mm from the top edge), H2 bottom-left (4 mm from the left and bottom edges), H3 top-left
(4 mm from the left and top edges, added 2026-10-10); H1 / H4 of the
earlier revisions removed 2026-10-10 and the rest renumbered.

### ERC power flags
Add a `PWR_FLAG` on `VSYS` (driven only through D1, a passive pin), on `+5V_PSU` and on `GND`
if ERC reports "input power pin not driven".

## 3. Net check list

| Net | Class | Connections |
|---|---|---|
| `MAINS_A_IN` | Mains | J1.2, F1.1 |
| `MAINS_A_FUSED` | Mains | F1.2, K3.11, PS1.1 |
| `MAINS_B_IN` | Mains | J1.1, K0.11, PS1.2 |
| `MOTOR_COMMON` | Mains | K0.14, J2.1 |
| `CHAIN_K2_COM` | Mains | K3.12, K2.11 |
| `CHAIN_K1_COM` | Mains | K2.12, K1.11 |
| `TAP3` | Mains | K3.14, J2.2 |
| `TAP2` | Mains | K2.14, J2.3 |
| `TAP1` | Mains | K1.14, J2.4 |
| `MAINS_K0_NC` | Mains | K0.12 only |
| `MAINS_K1_NC` | Mains | K1.12 only |
| `+5V_PSU` | LV_Power | PS1.4, D1.A |
| `VSYS` | LV_Power | D1.K, A1.39, U1.9, K0.A1, K1.A1, K2.A1, K3.A1, C1+, C2, C3, C4+, C5 |
| `GND` | LV_Power | PS1.3, A1 GND pins (3, 8, 13, 18, 23, 28, 33, 38), U1.3, U1.4, U1.7, U1.8, C1−, C2, C3, C4−, C5 |
| `+3V3` | LV_Power | A1.36 only (no load on the board) |
| `RELAY_K0_IN` | LV | A1.15, U1.6 |
| `RELAY_K3_IN` | LV | A1.16, U1.5 |
| `RELAY_K2_IN` | LV | A1.19, U1.2 |
| `RELAY_K1_IN` | LV | A1.20, U1.1 |
| `K0_COIL` | LV | U1.16, K0.A2 |
| `K3_COIL` | LV | U1.15, K3.A2 |
| `K2_COIL` | LV | U1.14, K2.A2 |
| `K1_COIL` | LV | U1.13, K1.A2 |

Earth is not on the PCB or in the box: the fan keeps its own cord with PE connected inside the fan. One 6-core cable runs fan ↔ box (L, N → J1; J2 → COM, LOW, MED, HIGH).
