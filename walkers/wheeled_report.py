# SPDX-License-Identifier: MIT
"""Write docs/wheeled-variants.md from reports/wheeled/ and give the summary
its wheeled entries.

    python -m walkers.wheeled_report
"""
from __future__ import annotations

import json
import sys

from . import model
from .model import ROOT

DOC = ROOT / "docs" / "wheeled-variants.md"
WHEEL_KINDS = ["LEGO", "TT stock", "printed solid with O-ring or band", "printed hub with TPU tyre"]


def load() -> tuple:
    with open(ROOT / "reports" / "wheeled" / "analysis.json", encoding="utf-8") as handle:
        analysis = json.load(handle)
    with open(ROOT / "reports" / "wheeled" / "sim.json", encoding="utf-8") as handle:
        sim = json.load(handle)
    return analysis, sim, model.load_json("wheeled.json")


def groups(analysis: dict) -> dict:
    """Default variants grouped by base and drive."""
    out = {}
    for vid in analysis["defaults"]:
        a = analysis["variants"][vid]
        out.setdefault((a["base"], a["drive"]), {})[(a["support"], a["wheels_at"])] = vid
    return out


def end_comparison(analysis: dict, sim: dict) -> dict:
    """Averages over the default variants, by which end the wheels are at."""
    out = {}
    for end in ("back", "front"):
        ids = [v for v in analysis["defaults"] if analysis["variants"][v]["wheels_at"] == end]
        n = len(ids)
        out[end] = {
            "mean_slope_deg": round(sum(sim["variants"][v]["slope"]["steepest_climbed_deg"] for v in ids) / n, 1),
            "mean_step_mm": round(sum(sim["variants"][v]["step"]["highest_climbed_mm"] for v in ids) / n, 1),
            "max_pitch_stopping_deg": round(max(max(abs(sim["variants"][v]["stop"]["max_pitch_deg"]),
                                                    abs(sim["variants"][v]["stop"]["min_pitch_deg"])) for v in ids), 1),
            "max_pitch_starting_deg": round(max(sim["variants"][v]["straight"]["max_pitch_deg"] for v in ids), 1),
            "mean_analytic_slope_deg": round(sum(analysis["variants"][v]["slope_limit_deg"] for v in ids) / n, 1),
        }
    for support in ("skid", "ball"):
        ids = [v for v in analysis["defaults"] if analysis["variants"][v]["support"] == support]
        n = len(ids)
        out[support] = {
            "mean_slope_deg": round(sum(sim["variants"][v]["slope"]["steepest_climbed_deg"] for v in ids) / n, 1),
            "mean_step_mm": round(sum(sim["variants"][v]["step"]["highest_climbed_mm"] for v in ids) / n, 1),
            "mean_drag_n": round(sum(analysis["variants"][v]["drag_n"] for v in ids) / n, 2),
            "mean_spin_fraction": round(sum(sim["variants"][v]["spin"]["fraction_of_ideal"] for v in ids) / n, 2),
        }
    return out


def summary_entries(analysis: dict, sim: dict, cfg: dict) -> list:
    entries = []
    for (base, drive), combos in groups(analysis).items():
        b, d = cfg["bases"][base], cfg["drives"][drive]
        first = analysis["variants"][combos[("skid", "back")]]
        kinds = [cfg["wheels"][w]["kind"] for w in b["wheels"][drive]]
        options = {}
        for (support, end), vid in combos.items():
            a, s = analysis["variants"][vid], sim["variants"][vid]
            options[f"{support}, wheels at the {end}"] = {
                "id": vid, "mass_g": a["mass_g"], "static_margin_mm": a["static_margin_mm"],
                "speed_m_s": s["straight"]["speed_m_s"], "max_slope_deg": s["slope"]["steepest_climbed_deg"],
                "max_step_mm": s["step"]["highest_climbed_mm"], "spin_deg_s": s["spin"]["yaw_rate_deg_s"],
                "model": f"robot/lego/wheeled/{vid}.xml"}
        entries.append({
            "id": f"{base}-{drive}-wheeled".replace("_", ""), "base": b["name"], "locomotion": "wheeled",
            "drive": d["name"], "drive_mount": d["mount"], "feedback": d["feedback"],
            "wheels": [k for k in WHEEL_KINDS if k in kinds],
            "default_wheel": cfg["wheels"][b["wheels"][drive][0]]["name"],
            "third_support": ["drag skid", "ball in a printed cup", "printed idler (analysed for drag only)"],
            "wheels_at": ["back", "front"], "recommended_wheels_at": "back",
            "chassis": f"stl/lego/{b['chassis']}/chassis.stl", "extra_printed_parts": "stl/lego/wheeled/",
            "mass_g": first["mass_g"],
            "balance": {"verdict": "centre of mass inside the wheel and support triangle" if first["stable"] else "outside the triangle",
                        "static_margin_mm": first["static_margin_mm"], "sideways_tilt_to_tip_deg": first["sideways_tilt_to_tip_deg"]},
            "ground_clearance_mm": first["ground_clearance_mm"], "top_speed_no_load_m_s": first["top_speed_no_load_m_s"],
            "power": b["power"], "signals": b["signals"] if "see the control" not in b["signals"] else d["signals"],
            "options": options, "controller_sketch": b["sketch"],
            "status": "analysed and simulated only; never printed, assembled or powered",
            "docs": "docs/wheeled-variants.md", "reports": ["reports/wheeled/analysis.json", "reports/wheeled/sim.json"],
        })
    return entries


def document(analysis: dict, sim: dict, cfg: dict) -> str:
    A, S = analysis["variants"], sim["variants"]
    cmp_ = end_comparison(analysis, sim)
    L = []
    add = L.append
    add("# Wheeled variants of every controller base")
    add("")
    add("Generated by `python -m walkers.wheeled_report` from `reports/wheeled/`. Edit the generator, not this file.")
    add("")
    add("> **Status: analysed and simulated only.** Nothing here has been printed, assembled or powered. The TT motor and "
        "servo cradles are drawn from typical dimensions, not from a maker's drawing. Assumed values are marked.")
    add("")
    add("Each controller base gets a wheeled build on the walker chassis: two driven wheels on the rear axle line "
        "(x = -16 mm) and a third support hanging from the two shelf holes at x = 92 mm, a wheelbase of 108 mm. "
        "**Wheels at the back** drives toward the support, the head's usual way round. **Wheels at the front** is the "
        "same build with the head pinned on facing the other way (its two holes are symmetric) and the drive reversed. "
        "The third support is a post with a tip: a drag skid, a ball in a printed cup, or a small printed idler.")
    add("")
    add("## Bases and drives")
    add("")
    add("| Base | Wheel drive | Feedback | Default wheel | Power | Signals |")
    add("|---|---|---|---|---|---|")
    for base, b in cfg["bases"].items():
        for drive in b["drives"]:
            d = cfg["drives"][drive]
            signals = b["signals"] if "see the control" not in b["signals"] else d["signals"]
            add(f"| {b['name']} | {d['name']}: {d['mount']} | {d['feedback']} | {cfg['wheels'][b['wheels'][drive][0]]['name']} | {b['power']} | {signals} |")
    add("")
    add("Every base has a sensible build from parts the owner has. Limits found on the way:")
    add("")
    add("- The six Braccio servos are position servos and cannot turn a wheel. The UNO Q and the plain Raspberry Pi use "
        "the 360-degree servos or TT motors instead.")
    add("- The M5Stack servo kit's own 24 mm wheels would put the side panels on the floor (the panel bottom is 12 mm "
        "below the axle). A printed 56 mm wheel on the servo horn is used.")
    add("- BaseX's documentation describes its four ports as LEGO motor ports and says nothing about a bare DC motor, so "
        "no TT build is offered for it; its two servo outputs can run the 360-degree servos.")
    add("- The EV3 31313 set has no ball caster. Its three 16.5 mm balls fit the printed cup. The 51515 set has "
        "neither a caster nor a ball: use the skid or a 12.7 mm steel ball.")
    add("")
    add("### The two non-LEGO drives")
    add("")
    add("| | 360-degree servo | TT gear motor |")
    add("|---|---|---|")
    sv, tt = cfg["drives"]["servo360"], cfg["drives"]["tt"]
    a_s, a_t = A[groups(analysis)[("unoq", "servo360")][("skid", "back")]], A[groups(analysis)[("unoq", "tt")][("skid", "back")]]
    s_s, s_t = S[a_s["id"]], S[a_t["id"]]
    rows = [
        ("Stall torque", f"{sv['stall_torque_nm']['value']} N m at 4.8 V", f"{tt['stall_torque_nm']['value']} N m at 6 V"),
        ("No-load speed", f"{sv['no_load_rpm']['value']:g} rpm", f"{tt['no_load_rpm']['value']:g} rpm (vendors: 160 to 250)"),
        ("Wheel", f"printed, {a_s['wheel_diameter_mm']} mm", f"stock, {a_t['wheel_diameter_mm']} mm"),
        ("Push at stall, both wheels", f"{a_s['motor']['wheel_force_at_stall_n']} N", f"{a_t['motor']['wheel_force_at_stall_n']} N"),
        ("Top speed, no load", f"{a_s['top_speed_no_load_m_s']} m/s", f"{a_t['top_speed_no_load_m_s']} m/s"),
        ("Speed in simulation", f"{s_s['straight']['speed_m_s']} m/s", f"{s_t['straight']['speed_m_s']} m/s"),
        ("Stall current, both", f"{a_s['motor']['stall_current_both_a']} A", f"{a_t['motor']['stall_current_both_a']} A (up to 5.6 A with some vendors)"),
        ("Mass, each", f"{sv['mass_g']['value']} g", f"{tt['mass_g']['value']} g (to 45 g)"),
        ("Robot mass, UNO Q", f"{a_s['mass_g']} g", f"{a_t['mass_g']} g"),
        ("Control signals", "one pulse output per wheel, no driver board", "an H-bridge board; one PWM and one or two direction lines per wheel"),
        ("Speed control", "open loop; the stop point must be trimmed", "open loop; an encoder version of the motor exists"),
        ("Steepest slope, wheels back / front (skid)", f"{s_s['slope']['steepest_climbed_deg']} / {S[groups(analysis)[('unoq', 'servo360')][('skid', 'front')]]['slope']['steepest_climbed_deg']} degrees",
         f"{s_t['slope']['steepest_climbed_deg']} / {S[groups(analysis)[('unoq', 'tt')][('skid', 'front')]]['slope']['steepest_climbed_deg']} degrees"),
        ("Highest step, wheels back / front (skid)", f"{s_s['step']['highest_climbed_mm']} / {S[groups(analysis)[('unoq', 'servo360')][('skid', 'front')]]['step']['highest_climbed_mm']} mm",
         f"{s_t['step']['highest_climbed_mm']} / {S[groups(analysis)[('unoq', 'tt')][('skid', 'front')]]['step']['highest_climbed_mm']} mm"),
    ]
    for r in rows:
        add(f"| {r[0]} | {r[1]} | {r[2]} |")
    add("")
    add("The servo has twice the torque and the TT motor more than twice the speed. Both have torque to spare on the "
        "level; slopes are limited by grip and by tipping, not by either motor. The TT wheel is larger, so it takes the "
        "higher step. The servo needs no driver board and two pins; the TT motor needs a driver and four to seven pins. "
        f"M5Stack's page: {sv['output']['note']}")
    add("")
    add("Sources for the figures: `walkers/config/wheeled.json`. The TT motor has no single maker; Adafruit's figures "
        f"are used and the spread between vendors is {tt['vendor_spread']}. Encoder option: {tt['encoder_option']['value']}.")
    add("")
    add("## Mass, balance and limits by calculation")
    add("")
    add("Level floor. `COM / wheelbase` is how far the centre of mass sits from the axle toward the support. The static "
        "margin is the distance from the centre of mass to the nearest edge of the triangle of the two wheels and the "
        "support. Skid, wheels at the back, default wheel:")
    add("")
    add("| Base and drive | Mass (g) | COM height (mm) | COM / wheelbase | Static margin (mm) | Sideways tilt to tip (deg) | Clearance (mm) | Top speed (m/s) | Torque on the level / stall | Push at stall (N) |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for (base, drive), combos in groups(analysis).items():
        a = A[combos[("skid", "back")]]
        add(f"| {cfg['bases'][base]['name']}, {cfg['drives'][drive]['name']} | {a['mass_g']} | {a['com_height_above_floor_mm']} | "
            f"{a['com_fraction_of_wheelbase']} | {a['static_margin_mm']} | {a['sideways_tilt_to_tip_deg']} | {a['ground_clearance_mm']} | "
            f"{a['top_speed_no_load_m_s']} | {a['torque_fraction_of_stall_level']} | {a['motor']['wheel_force_at_stall_n']} |")
    add("")
    fractions = [A[v]["com_fraction_of_wheelbase"] for v in analysis["defaults"]]
    axle_edge = sum(1 for v in analysis["defaults"] if abs(A[v]["static_margin_mm"] - A[v]["com_ahead_of_axle_mm"]) < 0.11)
    add(f"The centre of mass is {min(fractions)} to {max(fractions)} of the way from the axle to the support, so "
        f"{round(100 * (1 - max(fractions)))} to {round(100 * (1 - min(fractions)))} percent of the weight is on the driven "
        f"wheels. In {axle_edge} of the {len(fractions)} default builds the nearest edge of the triangle is the axle "
        f"line: the robot is closest to tipping backward over its wheels.")
    add("")
    add("### Which end the wheels should be at")
    add("")
    add("Accelerating moves load to the trailing end and braking to the leading end. The table gives the acceleration "
        "at which the support leaves the floor, against what the tyres and the motors can deliver (m/s2).")
    add("")
    add("| Base and drive | Wheels at | Tyres allow (accel) | Motors allow | Tyres allow (braking) | Support lifts when | at (m/s2) | Can it get there | Slope limit: torque / grip / tipping (deg) |")
    add("|---|---|---|---|---|---|---|---|---|")
    for (base, drive), combos in groups(analysis).items():
        for end in ("back", "front"):
            a = A[combos[("skid", end)]]
            when = "accelerating" if end == "back" else "braking"
            at = a["support_lifts_accelerating_m_s2"] if end == "back" else a["support_lifts_braking_m_s2"]
            add(f"| {cfg['bases'][base]['name']}, {cfg['drives'][drive]['name']} | {end} | {a['accel_limit_traction_m_s2']} | "
                f"{a['accel_limit_motor_m_s2']} | {a['brake_limit_traction_m_s2']} | {when} | {at} | "
                f"{'yes' if a['tips_before_it_slips'] else 'no'} | {a['slope_limit_torque_deg']} / {a['slope_limit_traction_deg']} / {a['slope_tips_at_deg']} |")
    add("")
    b_, f_ = cmp_["back"], cmp_["front"]
    add(f"- **Wheels at the back** puts the weight on the wheels when it matters: accelerating and climbing press them "
        f"down. In simulation these builds climb {b_['mean_slope_deg']} degrees on average against {f_['mean_slope_deg']} "
        f"with the wheels at the front. The price is the wheelie: a hard start lifts the support (pitch up to "
        f"{b_['max_pitch_starting_deg']} degrees in simulation), and a climb ends by tipping backward over the axle.")
    add(f"- **Wheels at the front** cannot wheelie, but accelerating and climbing unload the wheels, so grip sets the "
        f"limit, and hard braking lifts the support instead (pitch up to {f_['max_pitch_stopping_deg']} degrees when "
        f"stopping from full speed in simulation). The wheels meet a step before the support does.")
    add("- **Recommendation: wheels at the back**, with the drive ramped up over about a second, which is how the slope "
        "runs were made. Moving the batteries toward the support raises the tipping limit and costs grip.")
    add("")
    add("### Skid against roller")
    add("")
    fr = cfg["friction"]
    sk, bl = cmp_["skid"], cmp_["ball"]
    add(f"Assumed: a printed skid slides at a coefficient of {fr['skid']['value']} ({fr['skid']['range'][0]} to {fr['skid']['range'][1]}). "
        f"A ball in a plain printed cup does not roll freely: it slides in the cup, so its drag is the cup's friction, "
        f"{fr['ball_in_cup']['value']} ({fr['ball_in_cup']['range'][0]} to {fr['ball_in_cup']['range'][1]}). The printed "
        f"idler rolls at about {fr['rolling']['value']} but scrubs sideways in turns; it is analysed for drag only. "
        f"Mean drag on the level over the default builds: {sk['mean_drag_n']} N with the skid, {bl['mean_drag_n']} N with "
        f"the ball, against {min(A[v]['motor']['wheel_force_at_stall_n'] for v in analysis['defaults'])} to "
        f"{max(A[v]['motor']['wheel_force_at_stall_n'] for v in analysis['defaults'])} N of push at stall. In simulation the ball builds climb {bl['mean_slope_deg']} degrees "
        f"on average against {sk['mean_slope_deg']} with the skid, take steps of {bl['mean_step_mm']} mm against "
        f"{sk['mean_step_mm']} mm, and turn on the spot at {bl['mean_spin_fraction']} of the ideal rate against "
        f"{sk['mean_spin_fraction']}. The ball helps most where grip is short: wheels at the front on a slope.")
    add("")
    add("## Simulation")
    add("")
    add("One MuJoCo model per variant in `robot/lego/wheeled/`, generated by `python -m walkers.wheeled`: the chassis "
        "with everything fixed to it as one body, two wheels on hinges, and either a fixed dome (skid) or a ball on a "
        "ball joint whose friction torque is the cup friction at the ball radius. Motors: the LEGO motors run under a "
        "speed controller at 80 percent of no-load speed inside the stall-to-no-load torque line; the servos and TT "
        "motors are open loop, torque falling linearly with speed. Full drive in every run. Slopes and steps start "
        "with the drive ramped up.")
    add("")
    add("| Variant | Speed (m/s) | Of no-load | Spin (deg/s) | Arc radius (m) | Stop (m) | Pitch starting / stopping (deg) | Slope (deg) | fails by | Step (mm) | fails by |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for vid in analysis["defaults"]:
        s = S[vid]
        pitch_stop = max(abs(s["stop"]["max_pitch_deg"]), abs(s["stop"]["min_pitch_deg"]))
        add(f"| `{vid}` | {s['straight']['speed_m_s']} | {s['straight']['fraction_of_no_load_speed']} | {s['spin']['yaw_rate_deg_s']} | "
            f"{s['arc']['radius_m']} | {s['stop']['distance_m']} | {s['straight']['max_pitch_deg']} / {pitch_stop} | "
            f"{s['slope']['steepest_climbed_deg']} | {s['slope']['how'] or '-'} | {s['step']['highest_climbed_mm']} | {s['step']['how'] or '-'} |")
    add("")
    add("The arc is one wheel at full drive and the other at half; the ideal radius is three half-tracks "
        "(0.2 to 0.3 m). Slopes are tried in 2 degree steps and steps in 2 mm steps.")
    add("")
    if "recordings" in sim:
        add("![EV3 wheeled build driving and turning in simulation](images/wheeled-ev3-drive.gif)")
        add("")
        add("![EV3 wheeled build stopped by a step](images/wheeled-ev3-step.gif)")
        add("")
    add("## Wheels and tyres")
    add("")
    add("| Wheel | Kind | Rolling diameter (mm) | Width (mm) | Bore | Tread friction assumed |")
    add("|---|---|---|---|---|---|")
    for key, w in cfg["wheels"].items():
        f = fr[w["friction"]]
        add(f"| {w['name']} | {w['kind']} | {w['diameter_mm']} | {w['width_mm']} | {w['bore']} | {f['value']} ({f['range'][0]} to {f['range'][1]}) |")
    add("")
    add("No measured friction for these materials on laminate, tile or vinyl was found. Every coefficient is assumed "
        f"from generic tables: rubber and O-rings {fr['o_ring']['value']}, TPU 95A {fr['tpu']['value']}, the stock TT tyre "
        f"{fr['tt_tyre']['value']}, bare printed plastic {fr['pla']['value']}.")
    add("")
    add("**A bare printed wheel slips on a smooth floor. Fit an O-ring, a rubber band or the TPU tyre.** The same robot "
        "on each wheel option, skid, wheels at the back:")
    add("")
    add("| Variant | Tread | Friction | Wheel mass (g) | Speed (m/s) | Spin, of ideal | Slope (deg) | fails by | Step (mm) |")
    add("|---|---|---|---|---|---|---|---|---|")
    for vid in analysis["tyre_comparison"]:
        a, s = A[vid], S[vid]
        wheel_mass = round(a["mass_by_kind_g"]["wheel"] / 2, 1)
        add(f"| `{vid}` | {a['tyre'].replace('_', ' ')} | {a['friction']['wheel']} | {wheel_mass} | {s['straight']['speed_m_s']} | "
            f"{s['spin']['fraction_of_ideal']} | {s['slope']['steepest_climbed_deg']} | {s['slope']['how'] or '-'} | {s['step']['highest_climbed_mm']} |")
    add("")
    bare = [v for v in analysis["tyre_comparison"] if "-bare-" in v]
    shod = [v for v in analysis["tyre_comparison"] if "-bare-" not in v]
    add(f"With a ring or a TPU tyre the printed wheels climb {min(S[v]['slope']['steepest_climbed_deg'] for v in shod)} to "
        f"{max(S[v]['slope']['steepest_climbed_deg'] for v in shod)} degrees, the same as the LEGO and stock wheels to "
        f"within one 2 degree step. Bare, they climb {min(S[v]['slope']['steepest_climbed_deg'] for v in bare)} to "
        f"{max(S[v]['slope']['steepest_climbed_deg'] for v in bare)} degrees and the step limit drops as well. Between "
        f"rubber, O-ring and TPU the assumed differences are too small to change a limit by more than one step.")
    add("")
    o = cfg["o_rings"]
    add("### Printed solid wheel (the default printed option)")
    add("")
    add(f"One piece in PLA or PETG, printed flat face down without supports. O-ring sections: {o['standard']} "
        f"({o['source']}). {o['stretch']} ({o['stretch_source']}).")
    add("")
    add(f"- Groove: {o['groove']}.")
    add(f"- Rings: {o['rings']['d43']} for the 43 mm class, {o['rings']['d56']} for the 56 mm class, {o['rings']['d65']} for the 65 mm class.")
    add(f"- Rubber band version (`wheel_band_*`): {o['band_groove']}. The band is taken as 1 mm thick and brings the "
        f"wheel to the nominal diameter.")
    add("- Groove count, ring section, stretch and wheel diameter are parameters (`ORING`, `BAND`, `WHEELS` in the "
        "design's build.py), so the nearest ring to hand can be used.")
    add("")
    t = cfg["tpu"]
    add("### Hub with a TPU tyre")
    add("")
    add(f"For those who have flexible filament. Hardness: {t['hardness']['value']}. Design: {t['design']}. {t['printing']}")
    add("")
    add("### Bores")
    add("")
    add("- `cross`: Technic cross axle, the profile the walkers' fit coupon tests. For LEGO motors.")
    add(f"- `tt`: the TT motor's shaft, {tt['shaft']['value']} (assumed), in a 9 mm pocket with a 2.6 mm hole for the "
        f"retaining screw. Mounting: {tt['mounting_holes']['value']} (assumed).")
    add("- `horn`: a plain face with a 7.5 mm centre hole. The servo's spline is not documented well enough to print, "
        "so the wheel screws to the servo's own horn, using the horn as the drilling jig, as the biped's parts do.")
    add("- One fit piece per bore, and one each for the TT and servo cradles: print them first.")
    add("")
    add("## Control signals and power")
    add("")
    c = cfg["control"]
    add(f"- **UNO Q.** {c['unoq_pwm']['value']} ({c['unoq_pwm']['source']}). {c['braccio_pins']['value']}. {c['unoq_free']}")
    add(f"- **UNO Q with servos.** {c['unoq_servo']}")
    add(f"- **UNO Q with TT motors.** {c['unoq_tt']}")
    add(f"- **Raspberry Pi.** {c['pi_pwm']['value']} ({c['pi_pwm']['source']}). {c['pi_servo']} {c['pi_tt']}")
    add(f"- **BaseX.** {c['basex']['value']} ({c['basex']['source']}).")
    add("")
    add("| Driver board | Motor supply | Current | Pins | For the TT motor |")
    add("|---|---|---|---|---|")
    for d in c["drivers"]:
        add(f"| {d['name']} | {d['motor_supply']} | {d['current']} | {d['pins']} | {d['verdict']} |")
    add("")
    add("The driver sits on `driver_plate.stl`, a generic slotted plate, because boards vary.")
    add("")
    add("Controller sketches, syntax-checked and never run on hardware, in `walkers/controllers/`: `ev3_drive.py` "
        "(Pybricks, ports B and C), `hub51515_drive.py` (Pybricks, ports A and B), `buildhat_drive.py` (ports A and "
        "B), `pi_servo_drive.py` (GPIO12 and GPIO13) and `pi_tt_drive.py` (TB6612FNG). Each sets two wheel speeds. "
        "The servo and TT sketches are open loop: equal commands do not give a straight line. No sketch is given for "
        "the UNO Q or for BaseX: an Arduino sketch cannot be checked here, and BaseX's motor registers were not "
        "verified.")
    add("")
    add("## Unverified")
    add("")
    for line in [
        "Everything physical: no part printed, no motor in a cradle, no ring in a groove, no tyre on a hub.",
        "The TT motor's hole pattern and shaft flats, the servo's case size, and what kind of servo the owner's BALA-C ones are.",
        "Every friction coefficient. The limits that depend on grip (bare wheels, wheels at the front) move with them.",
        "All assumed masses: batteries, power banks, the hub's battery, wheels, the brick.",
        "The ball in its printed cup: snap fit, and the drag assumed for it.",
        "The TPU stretch and lip for any filament other than a 95A one, and the O-ring groove for rings off nominal size.",
        "PWM on the UNO Q pins the datasheet does not mark as PWM.",
        "Step results are from a rigid wheel on a square edge; a real tyre deforms.",
        "The motor models: straight torque lines from published stall and no-load figures.",
    ]:
        add(f"- {line}")
    add("")
    add("LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not sponsor or endorse this. "
        "Raspberry Pi is a trademark of Raspberry Pi Ltd. Arduino and UNO Q are trademarks of Arduino. M5Stack is a "
        "trademark of M5Stack Technology.")
    return "\n".join(L) + "\n"


def main() -> int:
    analysis, sim, cfg = load()
    DOC.write_text(document(analysis, sim, cfg), encoding="utf-8", newline="\n")
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
