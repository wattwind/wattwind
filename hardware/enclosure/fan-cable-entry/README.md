# Fan cable entry

Printed parts that hold the fan ↔ box cable in the fan's old speed-switch hole, without drilling. They are made
for the author's fan (a double-D hole, 9.7 × 12 mm, in a 1.2 mm metal housing): an example to adapt to yours, since
every fan's hole, wall and room inside differ. The sizes are user parameters (see Changing sizes).

**On the author's fan:** the **outer adapter** with an M16 gland outside, and the **inner clamp** inside
(see Inner clamp below; photos in the build guide, "Cable entry: an example"). The script has two other versions:
an **inner adapter** with a second gland instead of the clamp (for fans with more room inside), described next,
and **threaded** adapters.

## Two adapters with glands

Each adapter holds one standard M16 cable gland. No locknuts and no printed threads.

- **Inner adapter** (inside the fan): its D step rests on the flat area around the hole, and its D key
  goes through the hole and 8 mm out. The inner gland sits in its plain hole with the thread pointing
  out. **It stops the cable being pulled out.**
- **Outer adapter**: its D nose rests on the flat area outside, and its pocket fits over the key. The
  pocket is deeper than the key, so the adapter presses on the wall, not on the key. The outer gland
  sits in its plain hole with the thread pointing in. **It stops the cable being pushed in.**
- The key keeps both adapters from turning. It carries no load, and it lines the sharp metal edge of the
  hole.

## Threaded version

The design also contains **Inner adapter (threaded)** and **Outer adapter (threaded)**. They have the same
shape, but the glands screw in (M16 × 1.5, printed on the glands) instead of sitting in plain holes. Each
gland and its adapter become one unit, and the key stops the outer adapter turning while you tighten
its gland. Fitting is the same, except that you screw the inner adapter onto the inner gland (turning
it around the cable) before pushing the key through. Extra parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `ThreadClr` | 0.2 mm | printed thread widened by this; raise it if the gland is too tight |
| `LeadIn` | 0.8 mm | 45° countersink at the thread mouth |
| `KeyChamfer` | 0.5 mm | chamfer on the key tip and the cable bore end |

Both versions sit in the same place: hide one set in the browser to see the other.

## Inner clamp (when the fan has little room inside)

**Inner clamp (split, no gland)** replaces the inner adapter and its gland. It stands only 13 mm above the
wall (`StepH` + `ClampL`) instead of about 40 mm. It has two halves, split between the hole's round sides
so that each half keeps a flat of the key:

- The key goes through the hole, and the D step rests on the inner wall.
- A clamp block has a cable channel (`ClampBore`, 7 mm). A 1 mm gap between the halves (`SplitGap`)
  means two M3 screws really squeeze the sheath.
- Use **M3 × 12 to 14** screws: the heads sit in counterbores in half A, the nuts in pockets in half B.

It holds pull through the D step against the inner wall. The outer adapter and its gland still hold
push. To fit it: close the halves around the cable (sheath through), push the key into the hole, and
tighten both screws evenly. Print each half lying on its flat split face, with no supports.

| Parameter | Default | Meaning |
|---|---|---|
| `ClampL` | 10 mm | clamp block length above the step |
| `ClampBore` | 7 mm | cable channel |
| `SplitGap` | 1 mm | gap between the halves (max squeeze) |
| `ScrewX` | 8 mm | screws either side of the axis |
| `ScrewHole`, `HeadD`, `HeadSeat` | 3.4, 6.4, 5.5 mm | M3 clearance, head counterbore, its seat |
| `NutW`, `NutH`, `NutSeat` | 5.9, 6.8, 5.5 mm | M3 nut pocket, its seat |

## Fitting

1. Put the inner gland on the cable, thread pointing towards the hole, and tighten it on the cable sheath.
2. From inside the fan, put the inner adapter on the cable and push its key through the hole. Pull the
   cable from outside until the gland seats in the adapter.
3. Outside, slide on the outer adapter (pocket first) and then the outer gland (thread first).
4. Push both home and tighten the outer gland.

The cable's outer sheath must run through both glands into the fan. Keep the fan's own earth wire
connected to its metal housing as it was.

## Printing

- PETG, 4 walls, no supports.
- **Inner adapter:** stand it on its round end, with the gland hole down and the key up.
- **Outer adapter:** stand it on its D nose. The round body is wider than the nose, so it overhangs
  by up to 2.45 mm about 4 mm above the bed. Most printers manage that without supports. If yours
  droops, set `OverhangChamfer` to 2.5 mm: the body then slopes down to the nose at 45°, with no
  overhang. It doesn't change the fit.

## Changing sizes

Run `FanCableEntry.py` in Fusion (Utilities → Scripts and Add-Ins → +, pick this folder, Run). It builds a
new parametric design. Every size is a user parameter (Modify → Change Parameters) and the parts update
straight away. The ones you are most likely to change:

| Parameter | Default | Meaning |
|---|---|---|
| `KeyClr` | 0.15 mm | key in the fan hole, per side |
| `PocketClr` | 0.2 mm | outer pocket over the key, per side |
| `GlandClr` | 0.25 mm | gland thread in its hole, per side |
| `RestClr` | 0.3 mm | D step / nose smaller than the flat area, per side |
| `KeyOut` | 8 mm | key length outside the hole |
| `CableBore` | 7.6 mm | cable bore |
| `OverhangChamfer` | 0 mm (off) | outer adapters: 45° underside to the nose; 2.5 mm removes the overhang |
| `GlandThreadD`, `GlandThreadL` | 15.8, 8 mm | your gland (measured) |
| `HoleFlat`, `HoleRound`, `WallT`, `RestMargin` | 9.7, 12, 1.2, 5 mm | your fan's hole |

For printing, export each body with Right-click → Save as Mesh (3MF). Print exports are git-ignored.
