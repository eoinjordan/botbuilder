# Generator changes for the comb-feet variant

For whoever owns the part generator (`microduck-braccio-unoq/build.py` in the design directory).
This repository does not edit the generator.

Status: a proposal from the motion study (`docs/motion.md`), checked in simulation only.
It is not the owner's design. Nothing has been printed. The preset is `comb_feet` in `config/presets.json`;
the published geometry stays as the preset `drawn` and is not changed by any of this.

## Why

With a flat sole and no ankle the centre of mass cannot be moved over one foot, so the drawn robot cannot
lift a foot and hold it. If each sole reaches across the centreline, the centre of mass is already over
either foot. The two soles then have to interleave. Evidence and numbers: `docs/motion.md`, section
"Design changes and the evidence".

## What changes

One part per side: `left_shin_fixed_foot` and `right_shin_fixed_foot`. Only the sole plate changes.
The shin plate, the horn blank, the knee axis height (82 mm above the sole underside), the sole thickness
(5 mm) and the sole level stay as they are. No other part changes. The left and right shins stop being
mirror images.

In `build.py` the sole is now

    foot=profile(e,75,48,5,axes=(0,1)).translate([9,0,0])

a 75 by 48 mm plate from x = -28.5 to 46.5 and y = -24 to 24 in the shin part's coordinates (x towards the
toes, z up from the sole underside). Replace it by a union of rectangles, all 5 mm thick, underside at z = 0.

Coordinates below are x as in the part, and u = distance towards the other leg from the part's y = 0
(the robot's centreline is at u = 86). On the left shin as placed in this repository u = -y of the part; on
the right shin u = +y. Check the sign against the exported meshes: the fingers must point at the other leg.

| parameter | value (mm) | part | meaning |
|---|---|---|---|
| `COMB_THICKNESS` | 5 | both | sole thickness, unchanged |
| `COMB_BRIDGE` | x -17 to 17, u -6 to 30 | both | joins the foot of the shin plate to the rail; replaces the old plate under the shin |
| `COMB_RAIL` | x -30 to 64, u 30 to 44 | both | fore and aft rail the fingers grow from |
| `COMB_FINGER_WIDTH` | 14 | both | width of a finger along x |
| `COMB_FINGER_TIP` | u 118 | both | fingers run from the rail (u 44) to u 118, that is 32 mm past the centreline |
| `COMB_FINGERS_LEFT` | x -30 to -16 and x 50 to 64 | left shin | two fingers, heel end and toe end |
| `COMB_FINGERS_RIGHT` | x 10 to 24 | right shin | one finger, between the two of the left sole |

Resulting clearances at the stand pose, feet level and side by side:

- finger to finger along x: 26 mm each side (-16 to 10 and 24 to 50). The gait lets one foot lead the other by at most 22 mm
  (`MAX_STRIDE_MM` in `microduck/motions.py`), which leaves 4 mm.
- finger tip (u 118) to the other sole's rail (which is at u 128 to 142 seen from this side): 10 mm.
- the heel end stays 30 mm behind the knee axis, as now (28.5 mm). Do not lengthen it: the foot swings toes up
  and a longer heel digs in.

Things the generator owner will want to decide:

- Corners: the simulation uses plain rectangles. Rounded corners as on the present sole are fine; keep the
  finger width and the gaps.
- Stiffness: a 14 by 5 mm finger 74 mm long sags about 1.5 mm under the whole weight at its tip. A rib 3 mm
  high along the top of each finger and along the rail, or a 6 mm sole, is worth having. Keep the underside flat.
- `FOOT_STUDS`: the stud grid on the old sole top (first stud at x 22, y -12) no longer has a plate under it.
  Move it on to the rail or drop it.
- Print orientation: flat on the bed, underside down, as now.
- Mass: the model adds about 4 g per side for the left sole and 0 g for the right against the present 13 g plate
  (60 percent solid PLA).

## Checks to repeat after the change

1. `python scripts/regenerate.py` with the new STLs: the assembly test will then sweep the real soles. The
   hip roll range inward is set today by shin against shin (-52 degrees); with the fingers it will be smaller.
   The gait uses at most about 14 degrees of roll, both hips the same way.
2. Remove the `foot` override from the `comb_feet` preset (or keep the preset and compare): the generated
   `robot/microduck.xml` then carries the soles itself.
3. `python scripts/run_motion.py` and `pytest`.

## If the head end changes

The torso's mass and centre of mass come from `robot/microduck.xml`, which `scripts/regenerate.py` rebuilds from
the STLs, so a new head or camera mount is picked up by regenerating. To try a mass before the mesh exists, set
`head.extra_mass_g` and `head.position_mm` in `config/motion.json` and rerun `scripts/run_motion.py`.
`docs/motion.md` lists how far 20 g and 40 g at the head move each result.
