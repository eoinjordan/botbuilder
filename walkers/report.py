# SPDX-License-Identifier: MIT
"""Write docs/lego-walkers.md and reports/variants/summary.json from the
assembly and simulation reports.

    python -m walkers.report
"""
from __future__ import annotations

import json
import sys

from . import model
from .model import BUILDS, ROOT

DOC = ROOT / "docs" / "lego-walkers.md"
SUMMARY = ROOT / "reports" / "variants" / "summary.json"
REPO = "https://github.com/eoinjordan/botbuilder"

PIXY = {
    "owner_has": "a standard Pixy2 with the pan-tilt kit and a separately bought EV3 cable (stated by the owner; not the LEGO edition)",
    "hardware": "The LEGO edition and the standard Pixy2 are the same board. Charmed Labs' developer said any Pixy2 can be "
                "used with the EV3 given the LEGO firmware and the cable.",
    "firmware": "Two ways to use it. With the LEGO firmware (loaded with PixyMon) the camera works with the EV3 blocks "
                "over the LEGO sensor protocol. With the stock firmware it answers on plain I2C, which is what the "
                "ev3dev and MicroPython libraries use: Charmed Labs' Python page says to run the stock version and set "
                "the interface to I2C, address 0x54.",
    "mount": "The LEGO edition's right-angle brackets are not in the standard hardware bag, so the perforated face of "
             "camera_head.stl has nothing to pin to. camera_head_pantilt.stl carries the pan-tilt base plate on a slotted "
             "top platform instead. Charmed Labs publish no drawing of the plate, so the 72 x 56 mm platform is an "
             "assumption to check against the kit.",
    "servos": "The pan-tilt servos plug into the Pixy2 and are driven by it. The LEGO firmware has no servo command "
              "for the EV3 (a forum reply from Charmed Labs). The stock firmware's serial protocol has setServos (packet "
              "type 18, two values 0 to 511) and is the same over I2C, so an EV3 running Pybricks or ev3dev could send it "
              "as raw I2C. Nobody is documented doing that from an EV3, and the same reply suggests feeding the Pixy2 "
              "from USB so the servos have enough power. Treat pan-tilt from the EV3 as untested.",
    "sources": ["https://forum.pixycam.com/t/is-pixy-2-compatible-with-mindstorms/5775",
                "https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:python",
                "https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:porting_guide",
                "https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:assembling_pantilt_mechanism",
                "https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:mounting_pixy_with_lego"],
}

UNVERIFIED = [
    "Everything physical. No part has been printed; no axle, pin, gear or motor has been tried in one.",
    "Every assumed value in the table above, above all the masses LEGO does not publish (brick, motors) and the pan-tilt kit.",
    "The motor envelopes are boxes inside catalogue sizes. Real motors have pin holes and curves the boxes ignore, and the "
    "brackets that hold them are not designed.",
    "The 0.2 mm between the cranks and the idler axle's bush, and the 1.2 mm between cranks and legs, are nominal; printed "
    "parts and bush positions will vary by more than that.",
    "Gear backlash, axle flex in 5.35 mm printed bearings, and the pins' play are not in the simulation. The legs are held "
    "exactly upright there; on the robot they will rock by the play in two pins 32 mm apart.",
    "Floor friction, and the contact of a flat rigid sole on a real floor that is not flat.",
    "The motor model: a straight line from stall torque to no-load speed from LEGO's figures, with an ideal controller.",
    "The controller sketches: syntax-checked, never run. Motor directions and the homing poses are guesses to confirm.",
    "Pan-tilt from the EV3, and the standard Pixy2 on the LEGO firmware with the owner's cable.",
    "The Build HAT build on a battery: the design is tethered to the 8 V adapter and the cable's pull is not modelled.",
]


def load(name: str) -> dict:
    with open(ROOT / "reports" / "lego" / name, encoding="utf-8") as handle:
        return json.load(handle)


def components_table(comp: dict) -> list:
    rows = ["| Part | Item | Value | From | Source or reason |", "|---|---|---|---|---|"]
    for key, part in comp.items():
        if key.startswith("_"):
            continue
        name = part.get("name", key)
        for item, v in part.items():
            if not isinstance(v, dict) or "class" not in v:
                continue
            value = v.get("value", "see envelope" if item == "envelope" else "")
            if isinstance(value, list):
                value = " x ".join(f"{x:g}" for x in value)
            why = v.get("source") or v.get("why", "")
            if v.get("note"):
                why = f"{why} ({v['note']})" if why else v["note"]
            if v.get("source") and v.get("why"):
                why = f"{v['source']} ({v['why']})"
            rows.append(f"| {name} | {item.replace('_', ' ')} | {value} | {v['class']} | {why} |")
    return rows


def summary(assembly: dict, sim: dict) -> dict:
    out = {"_comment": "One entry per controller base and locomotion type, for the configurator. Generated; do not edit.",
           "status": "Analysed and simulated only. Nothing has been assembled.",
           "entries": []}
    drive = {"ev3-pixy2": "two EV3 large motors (ports B and C), one per side, 1:1 to the rear crank axle",
             "pi-zero-2w-51515": "two 51515 medium angular motors (Build HAT ports A and B), one per side, 1:1 to the rear crank axle"}
    base = {"ev3-pixy2": "LEGO EV3 brick", "pi-zero-2w-51515": "Raspberry Pi Zero 2 W with Build HAT"}
    for build in BUILDS:
        a, s = assembly["builds"][build], sim["builds"][build]
        st = a["stability"]
        out["entries"].append({
            "id": f"{build}-walker", "base": base[build], "locomotion": "crank walker", "build": build,
            "title": model.TITLES[build], "drive": drive[build],
            "mass_g": a["mass"]["total_g"], "size_mm": a["size_mm"],
            "balance": {"verdict": "statically stable at every crank phase" if st["stable_at_every_phase"] else "tips",
                        "min_margin_mm": st["min_margin_mm"], "tilt_to_tip_deg": st["tilt_to_tip_deg"]},
            "walk": {"speed_mm_s_at_60_rpm": next(r["speed_mm_s"] for r in s["forward"]["runs"] if r["rpm"] == 60),
                     "fastest_steady_mm_s": s["forward"]["fastest_steady_speed_mm_s"],
                     "turns": False, "max_step_mm": s["steps"]["highest_climbed_mm"],
                     "max_slope_up_deg": s["slopes"]["uphill"]["steepest_walked_deg"]},
            "printed_parts": f"stl/lego/{build}/", "controller_sketch": {
                "ev3-pixy2": "walkers/controllers/ev3_walker.py", "pi-zero-2w-51515": "walkers/controllers/buildhat_walker.py"}[build],
            "status": "analysed and simulated only; never printed, assembled or powered",
            "docs": "docs/lego-walkers.md", "reports": ["reports/lego/assembly.json", "reports/lego/sim.json"],
        })
    return out


def document(assembly: dict, sim: dict, comp: dict, manifest: dict) -> str:
    g = assembly["gear_mesh"]
    L = []
    add = L.append
    add("# Two LEGO-motor crank walkers: assembly test and simulation")
    add("")
    add("Generated by `python -m walkers.report` from `reports/lego/assembly.json` and `reports/lego/sim.json`. Edit the "
        "generator, not this file.")
    add("")
    add("> **Status: analysed and simulated only.** Nothing here has been printed, assembled or powered. No walking "
        "controller has run on hardware. Dimensions and masses the makers do not publish are assumed and listed below.")
    add("")
    add("Two walkers of the owner's design that share one mechanism and differ in what drives and controls them:")
    add("")
    add("| Build | Controller | Motors | Camera | Printed parts |")
    add("|---|---|---|---|---|")
    add("| `ev3-pixy2` | EV3 brick strapped to the deck | two EV3 large motors, ports B and C | Pixy2 | `stl/lego/ev3-pixy2/` |")
    add("| `pi-zero-2w-51515` | Raspberry Pi Zero 2 W with the Build HAT | two 51515 medium angular motors, ports A and B | Camera Module 2 | `stl/lego/pi-zero-2w-51515/` |")
    add("")
    add("![the EV3 build as placed for the test](images/lego-ev3-pixy2-iso.png)")
    add("")
    add("## The mechanism")
    add("")
    add("Each side panel carries three parallel axles 16 mm apart on the 8 mm Technic grid. Inside the panel a 16-tooth gear "
        "sits on each; the middle one idles, so the two outer axles turn the same way at the same speed. Outside the panel "
        "each outer axle carries a crank of 12 mm radius. The leg is pinned to the two crank tips, 32 mm apart, so it does "
        "not rotate: every point of it moves on a 12 mm circle and the flat sole stays level. The two legs are half a "
        "turn apart. The lower foot carries the robot and moves back 24 mm under it while the other swings forward 24 mm "
        "above the floor, so one crank turn moves the robot 48 mm. One motor per side drives the rear axle directly.")
    add("")
    add("The feet overlap under the body: each sole has two fingers that reach 10.5 mm past the centreline, the left "
        "foot's at 70 mm fore and aft, the right foot's at 27 mm, so they pass each other.")
    add("")
    add("## Parts and facts")
    add("")
    add("`maker` is the maker's own published figure, `third-party` a parts catalogue or reseller, `assumed` a value "
        "nobody publishes with the reason it was chosen. Source: `walkers/config/components.json`.")
    add("")
    L.extend(components_table(comp))
    add("")
    add("Figures looked for and not found: any mass from LEGO for the brick or the motors, the pin-hole patterns of the "
        "motors and the brick, Philo's motor measurements (his site refused the request), the Build HAT's mass and "
        "per-port current limit, the pan-tilt kit's size and mass.")
    add("")
    add("### Power")
    add("")
    add("- EV3 build: the brick's own cells. Six AA cells are assumed; the 7.4 V rechargeable pack is lighter and makes "
        "the brick deeper.")
    add("- Pi build: the design README assumes the Build HAT and its supported 8 V supply. That supply is a mains "
        "adapter (8 V, 6 A, 48 W, barrel jack), and it powers the Raspberry Pi as well, so as designed the robot walks "
        "on a tether. A battery of 7.2 V to 8.5 V on the barrel jack is inside the product brief's range; six NiMH AA "
        "cells are assumed as an option and treated as ballast in the balance test. Not tested.")
    add("")
    add("### The Pixy2")
    add("")
    add(f"The owner has {PIXY['owner_has']}.")
    add("")
    for key in ("hardware", "firmware", "mount", "servos"):
        add(f"- {PIXY[key]}")
    add("")
    add("Sources: " + ", ".join(PIXY["sources"]) + ".")
    add("")
    add("## Digital assembly")
    add("")
    add("Frame: x forward, y left, z up, origin on the centre axle midway between the panels. The printed parts are the "
        "STLs in `stl/lego/`; bought parts are boxes of their published or assumed size. Overlaps are exact mesh "
        "intersections.")
    add("")
    add("### Placements the design leaves open")
    add("")
    for build in BUILDS:
        add(f"`{build}`:")
        add("")
        for note in assembly["builds"][build]["placements"]:
            add(f"- {note}")
        add("")
        add(f"![{build}: drive train with the chassis hidden](images/lego-{build}-drive.png)")
        add("")
        add(f"![{build} from the left](images/lego-{build}-left.png)")
        add("")
    add("### Interference")
    add("")
    for build in BUILDS:
        inter = assembly["builds"][build]["interference"]
        n = len(inter["rest"]) + len(inter["cycle"])
        add(f"- `{build}`: {n} overlapping pairs. Checked at rest and at {inter['phases_checked']} crank phases, "
            f"{inter['pairs_per_phase']} pairs per phase: both legs and all four cranks against each other and against "
            f"{', '.join(inter['fixed_parts'])}.")
        for row in inter["rest"] + inter["cycle"]:
            add(f"  - {row['a']} with {row['b']}: {row['volume_mm3']} mm3")
    add("")
    add("The floor is included: the lowest fixed part is "
        + " and ".join(f"{assembly['builds'][b]['clearances']['lowest fixed part above the floor']['min_gap_mm']} mm (`{b}`)" for b in BUILDS)
        + " above it at the lowest point of the walk.")
    add("")
    add("Smallest gaps over the cycle:")
    add("")
    add("| Pair | " + " | ".join(f"`{b}` (mm)" for b in BUILDS) + " |")
    add("|---|---|---|")
    for key in assembly["builds"][BUILDS[0]]["clearances"]:
        add(f"| {key} | " + " | ".join(str(assembly["builds"][b]["clearances"][key]["min_gap_mm"]) for b in BUILDS) + " |")
    add("")
    add("The tight one is the idler axle. The cranks sweep across its outboard end, 8 mm from the panel. A full bush there "
        "is 7.8 mm long and leaves 0.2 mm. Use a half bush, or stop the axle flush and retain it from inside.")
    add("")
    add("### Gear mesh")
    add("")
    add(f"Measured from `gear_16t_print_6.stl`: {g['teeth']} teeth, tip radius {g['tip_radius_mm']} mm, root radius "
        f"{g['root_radius_mm']} mm, tooth {g['tooth_thickness_at_pitch_mm']} mm thick on the 16 mm pitch circle, circular "
        f"pitch {g['circular_pitch_mm']} mm. That is module {g['module_mm']:g}, the Technic pitch, and two 16-tooth gears "
        f"of module 1 belong {g['standard_centre_distance_mm']:g} mm apart: the axle spacing, with {g['centre_distance_error_mm']:g} mm "
        f"of error. Turned through one tooth in mesh the printed gears overlap by {g['overlap_through_one_tooth_mm3']} mm3. "
        f"Backlash is {g['backlash_per_mesh_mm']} mm per mesh ({g['backlash_per_mesh_deg']} degrees), so the two cranks of a "
        f"side can differ by {g['crank_to_crank_play_deg']} degrees through the two meshes. The leg ties the cranks together "
        f"everywhere except where they lie along the pivot row, which is where the feet change over; the gears carry them "
        f"through there. Tip to root clearance {g['tip_to_root_clearance_mm']} mm. A stock 16-tooth gear has the same pitch "
        f"and is 7.8 mm wide against the printed {g['thickness_mm']:g} mm, as the design README notes.")
    add("")
    add("![three printed gears in mesh](images/lego-gear-mesh.png)")
    add("")
    add("### Mass and centre of mass")
    add("")
    for build in BUILDS:
        a = assembly["builds"][build]
        m = a["mass"]
        add(f"`{build}`: {m['total_g']} g ({', '.join(f'{k} {v} g' for k, v in m['by_kind_g'].items())}); "
            f"{m['total_if_printed_solid_g']} g if printed solid. Size {a['size_mm'][0]:g} x {a['size_mm'][1]:g} x "
            f"{a['size_mm'][2]:g} mm. Centre of mass at x {a['centre_of_mass_mm'][0]}, y {a['centre_of_mass_mm'][1]}, "
            f"z {a['centre_of_mass_mm'][2]} mm, {a['stability']['com_height_above_floor_mm']} mm above the floor.")
        add("")
        add("| Item | Mass (g) | From | At x, y, z (mm) |")
        add("|---|---|---|---|")
        for row in m["items"]:
            add(f"| {row['name']} | {row['mass_g']} | {row['from']} | {row['at_mm'][0]}, {row['at_mm'][1]}, {row['at_mm'][2]} |")
        add("")
    add("### Balance through the crank cycle")
    add("")
    add("At each phase the lower foot is on the floor (both when level). The robot is statically balanced if the centre "
        "of mass is over that foot's outline. The margin is the distance from the centre of mass to the nearest edge.")
    add("")
    add("| Phase (deg) | On the floor | " + " | ".join(f"`{b}` margin (mm)" for b in BUILDS) + " |")
    add("|---|---|---|---|")
    rows = [assembly["builds"][b]["stability"]["phases"] for b in BUILDS]
    for i, row in enumerate(rows[0]):
        add(f"| {row['phase_deg']} | {' and '.join(row['on_floor'])} | " + " | ".join(str(r[i]["margin_mm"]) for r in rows) + " |")
    add("")
    for build in BUILDS:
        a = assembly["builds"][build]
        st, win, pl = a["stability"], a["com_window"], a["placement"]
        add(f"`{build}`: balanced at every phase, smallest margin {st['min_margin_mm']} mm at {st['at_phase_deg']} degrees. "
            f"A tilt of {st['tilt_to_tip_deg']} degrees uses it up. For the centre of mass to stay over the stance foot at "
            f"every phase it must lie between x {win['x_range_mm_at_com_y'][0]:g} and {win['x_range_mm_at_com_y'][1]:g} mm and "
            f"between y {win['y_range_mm_at_com_x'][0]:g} and {win['y_range_mm_at_com_x'][1]:g} mm.")
        add("")
        for key, v in a["variants"].items():
            add(f"- {key}: {v['mass_g']} g, centre of mass x {v['com_mm'][0]} mm, smallest margin {v['min_margin_mm']} mm.")
        add("")
        if build == "ev3-pixy2":
            add(f"**Where the brick must sit.** The brick is {pl['mass_g']:g} g of {a['mass']['total_g']} g. With the motors "
                f"pointing backward, its centre may be anywhere from x {pl['x_range_balanced_mm'][0]:g} to "
                f"{pl['x_range_balanced_mm'][1]:g} mm before the robot tips; from {pl['x_range_with_5_mm_margin_mm'][0]:g} to "
                f"{pl['x_range_with_5_mm_margin_mm'][1]:g} mm keeps 5 mm; from {pl['x_range_at_full_margin_mm'][0]:g} to "
                f"{pl['x_range_at_full_margin_mm'][1]:g} mm keeps the full {pl['full_margin_mm']} mm, which the sideways reach of "
                f"the finger tips sets. The deck holds it between {pl['x_range_fully_on_deck_mm'][0]:g} and "
                f"{pl['x_range_fully_on_deck_mm'][1]:g} mm without overhang, so centred on the deck is right and no ballast "
                f"is needed. Sideways it must be centred: 10 mm off centre uses 4 mm of the 10 mm. With the motors pointing "
                f"forward instead the margin is {a['variants']['motors forward, pantilt']['min_margin_mm']} mm: do not.")
            b = a["battery_sensitivity"]
            add("")
            add(f"With the rechargeable pack ({b['rechargeable pack']['mass_g']} g in all) the margin is "
                f"{b['rechargeable pack']['min_margin_mm']} mm.")
        else:
            w = a["with_battery_pack"]
            add(f"**Ballast.** None is needed. If a {pl['mass_g']:g} g battery pack is added between the panels it may sit from "
                f"x {pl['x_range_balanced_mm'][0]:g} to {pl['x_range_balanced_mm'][1]:g} mm; at x 0 the robot is {w['mass_g']} g "
                f"with a margin of {w['min_margin_mm']} mm.")
        add("")
        add(f"![{build}: soles and centre of mass from above](images/lego-{build}-balance.png)")
        add("")
    add("So a crank walker with two flat interleaving feet does stand on one foot at a time, because each foot reaches "
        "under the centre of mass. The reach is the limit: 10.5 mm past the centreline, about 4 to 6 degrees of lean. "
        "Longer fingers would buy margin directly.")
    add("")
    add("## Simulation")
    add("")
    add("One MJCF model per build, written by `python -m walkers.mjcf` from the same placement data "
        "(`robot/lego/<build>.xml`). The chassis with everything fixed to it is one free body. On each side the rear "
        "crank is a hinge driven by the motor, the leg hangs from the rear crank tip on a second hinge, and the front "
        "crank is a third hinge. Two equality constraints close the loop: a connect constraint pins the front crank tip "
        "to the leg, and a joint constraint holds the front crank at the rear crank's angle, which is what the three "
        "gears do. Without the gear constraint the linkage is free to fold at its two change points. Backlash is not "
        "modelled. The soles are convex pieces of the real outline; feet touch only the floor and the step.")
    add("")
    s0 = sim["builds"][BUILDS[0]]["model"]["motor"]
    add("Motors: a torque source behind a controller that advances a crank angle reference at the commanded speed and "
        "corrects the error, as the controller sketches do. The torque is clipped to the motor's line from stall torque "
        "at rest to zero at no-load speed (LEGO's figures), ratio 1 to the crank. Joint friction "
        f"{s0['joint_friction_nm']} N m per crank axle (assumed). Floor friction 0.4 (assumed), 1 ms step.")
    add("")
    for build in BUILDS:
        s = sim["builds"][build]
        add(f"### `{build}`")
        add("")
        add(f"![{build} walking at 60 rpm in simulation](images/lego-{build}-walk.gif)")
        add("")
        for key, text in s["verdict"].items():
            add(f"- **{key.capitalize()}.** {text}")
        add("")
        add("Straight ahead, both sides in phase opposition, 10 s:")
        add("")
        add("| Crank rpm | Ideal (mm/s) | Speed (mm/s) | Slip | Max tilt (deg) | Heading change (deg) | No foot down | Peak torque (N m) | Fell |")
        add("|---|---|---|---|---|---|---|---|---|")
        for r in s["forward"]["runs"]:
            add(f"| {r['rpm']:g} | {r['ideal_speed_mm_s']} | {r['speed_mm_s']} | {r['slip_fraction']} | {r['max_tilt_deg']} | "
                f"{r['yaw_change_deg']} | {r['feet']['none_fraction']} | {r['torque']['peak_nm']} | {'yes' if r['fell'] else 'no'} |")
        add("")
        add("Floor friction at 60 rpm: " + "; ".join(
            f"{r['friction']:g}: {r['speed_mm_s']} mm/s, slip {r['slip_fraction']}" for r in s["friction"]) + ".")
        add("")
        add("Different speeds on the two sides (left at 60 rpm, 12 s):")
        add("")
        add("| Right rpm | Forward (m) | Sideways (m) | Heading change (deg) | Max tilt (deg) | Fell |")
        add("|---|---|---|---|---|---|")
        for r in s["turning"]:
            add(f"| {r['right_rpm']:g} | {r['distance_forward_m']} | {r['drift_left_m']} | {r['yaw_change_deg']} | "
                f"{r['max_tilt_deg']} | {'yes, ' + str(r['fell_how']) if r['fell'] else 'no'} |")
        add("")
        ss = s["start_stop"]
        add(f"Starting from rest with no ramp: tilt {ss['step_start']['max_tilt_deg']} degrees, peak torque "
            f"{ss['step_start']['torque']['peak_nm']} N m. Stopping from 60 rpm in mid stance: coasts "
            f"{ss['stop_mid_stance']['coast_after_stop_mm']} mm, tilt {ss['stop_mid_stance']['max_tilt_after_stop_deg']} degrees; "
            f"at the changeover: {ss['stop_at_handover']['coast_after_stop_mm']} mm, "
            f"{ss['stop_at_handover']['max_tilt_after_stop_deg']} degrees. It stays up in both.")
        add("")
        add("Slopes at 60 rpm (steepest walked, then what happened one step steeper):")
        add("")
        for key in ("uphill", "downhill", "left_side_high", "right_side_high"):
            v = s["slopes"][key]
            last = v["runs"][-1]
            what = (f"fell {last['fell_how']}" if last["fell"] else
                    f"speed {last['speed_mm_s']} mm/s, tilt {last['max_tilt_deg']} degrees") if not last["walks"] else "not reached"
            add(f"- {key.replace('_', ' ')}: {v['steepest_walked_deg']} degrees; at {last['deg']}: {what}.")
        add("")
        st = s["steps"]
        last = st["runs"][-1]
        add(f"Step: highest climbed {st['highest_climbed_mm']} mm. At {last['height_mm']} mm: "
            + ("climbed." if last["climbed"] else (f"fell {last['fell_how']}." if last["fell"] else
                                                    f"stopped after {last['distance_forward_m']} m.")))
        add("")
        add("Phase error between the sides (right side offset from half a turn), 60 rpm:")
        add("")
        add("| Error (deg) | Speed (mm/s) | Max tilt (deg) | Fell |")
        add("|---|---|---|---|")
        for r in s["phase_errors"]["runs"]:
            add(f"| {r['phase_error_deg']} | {r['speed_mm_s']} | {r['max_tilt_deg']} | {'yes' if r['fell'] else 'no'} |")
        add("")
    add("### What the simulation says")
    add("")
    add("- **It walks.** At moderate crank speeds both builds walk straight at the kinematic speed with almost no slip. "
        "The feet change over when their speed relative to the body is zero, so the walk asks little of the floor: "
        "friction down to 0.1 makes no difference.")
    add("- **There is a speed limit, and it is the bounce.** The body drops and is caught twice per turn. Above about 90 rpm "
        "the feet leave the floor, the heading wanders and the tilt grows. The motors' full speed is not usable.")
    add("- **It cannot steer.** A leg on parallel cranks only translates. A foot on the floor moves the body straight "
        "forward or back; it cannot turn it. With different speeds on the two sides the legs drift through every phase "
        "relation and the robot slows without turning. Steering needs something this design does not have: a way to "
        "turn a foot or the body on it.")
    add("- **It tips sideways easily.** The lateral margin is the 10.5 mm the finger tips reach past the centreline. "
        "A cross slope of a few degrees or a step of a few millimetres under one edge of a foot is enough.")
    add("- **Phase errors cost speed, not balance.** The walk slows as the sides leave phase opposition and stops when "
        "they are in phase, where both feet are always down and the robot only bobs. Holding the phase within about 20 "
        "degrees keeps 98 percent of the speed. Encoders of 1 degree are ample; the homing pose matters more.")
    add("")
    add("## Controller sketches")
    add("")
    add("Both are documentation with code: syntax-checked by the tests, never run on hardware.")
    add("")
    add("- `walkers/controllers/ev3_walker.py`: Pybricks for the EV3 (the first target the owner's mindstorms-robot-creator "
        "generates for the EV3 family, with the same imports). Large motors on ports B (left) and C (right), as the design "
        "README says; port A is the optional head motor. The EV3 encoders are relative, so the phase is set by hand at "
        "the start (left foot down, right foot up, press the centre button); after that both motors track one angle "
        "reference with `track_target`, the right 180 degrees ahead.")
    add("- `walkers/controllers/buildhat_walker.py`: the `buildhat` library. 51515 motors on Build HAT ports A (left) and B "
        "(right); C is the optional head motor. These motors have absolute encoders, so the program homes itself with "
        "`run_to_position` to two stored offsets, then runs both sides and trims the right side's speed by the phase "
        "error.")
    add("")
    add("## Printing")
    add("")
    add(f"The STLs are in `stl/lego/` with `stl/lego/manifest.json` (purpose, quantity, triangle count, volume, bounding "
        f"box, SHA-256 and the design commit of each): {len(manifest['files'])} files, {manifest['total_bytes'] / 1e6:.2f} MB. "
        f"Print the fit coupon first.")
    add("")
    add("| File | Print | Purpose | Volume (cm3) | Box (mm) |")
    add("|---|---|---|---|---|")
    for f in manifest["files"]:
        box = " x ".join(f"{v:g}" for v in f["bounding_box_mm"])
        add(f"| `{f['file']}` | {f['print_quantity']} | {f['purpose']} | {f['volume_cm3']} | {box} |")
    add("")
    add("The legs, soles, neck and head outlines started from the convex outlines of meshes in the same Microduck part "
        "pack as the biped's plates (see NOTICE). Those meshes are not in this repository.")
    add("")
    add("## Unverified")
    add("")
    for line in UNVERIFIED:
        add(f"- {line}")
    add("")
    add("## Regenerating")
    add("")
    add("    python -m walkers.manifest --design-dir /path/to/microduck-lego    copy the STLs, write the manifest")
    add("    python -m walkers.assembly        assembly test and pictures (about five minutes)")
    add("    python -m walkers.mjcf            MuJoCo models")
    add("    python -m walkers.experiments     simulation and recordings (about three minutes)")
    add("    python -m walkers.report          this document and reports/variants/summary.json")
    add("")
    add("LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not sponsor or endorse this. "
        "Raspberry Pi is a trademark of Raspberry Pi Ltd. Pixy2 is a product of Charmed Labs.")
    return "\n".join(L) + "\n"


def main() -> int:
    assembly, sim = load("assembly.json"), load("sim.json")
    comp = model.load_json("components.json")
    with open(ROOT / "stl" / "lego" / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)
    DOC.write_text(document(assembly, sim, comp, manifest), encoding="utf-8", newline="\n")
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary(assembly, sim), indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {DOC.relative_to(ROOT)} and {SUMMARY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
