# SPDX-License-Identifier: MIT
"""docs/motion.md from reports/motion.json."""
from __future__ import annotations

TITLE = {"comb": "Comb soles (the robot as built)", "flat_feet": "Flat soles (comparison)"}


def _table(header, rows) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _yes(value) -> str:
    return "yes" if value else "no"


def _range(pair, unit="") -> str:
    return "none" if not pair else f"{pair[0]} to {pair[1]}{unit}"


def _fell(run: dict) -> str:
    return f"fell {run['fell_how']} at {run['fell_at_s']} s" if run.get("fell") else "stayed up"


def _rest(r: dict) -> str:
    if r["fell"]:
        return f"falls {r['fell_how']}"
    on = ", ".join(r["on_the_floor"]) or "nothing"
    parts = "; ".join(f"{k} ({v} mm3)" for k, v in r["mesh_interference_mm3"].items()) or "none"
    stops = ", ".join(r["at_travel_stop"]) or "no joint"
    return (f"sinks {r['torso_drop_mm']} mm and comes to rest at hip pitch {r['joints_deg']['hip_pitch']}, knee {r['joints_deg']['knee']} degrees, "
            f"body pitched {r['pitch_deg']} degrees; on the floor: {on}; at a servo travel stop: {stops}; parts overlapping in the meshes there: {parts}")


def _path(worst: dict) -> str:
    if not worst:
        return "none"
    return "; ".join(f"{pair} up to {v['mm3']} mm3 (at hip pitch {v['at_hip_pitch_deg']}, knee {v['at_knee_deg']} degrees)" for pair, v in worst.items())


def steps_sentence(walk: dict) -> str:
    n = walk["nominal"]
    if n["fell"]:
        return f"The gait falls {n['fell_how']} at {n['fell_at_s']} s."
    kind = ("It truly steps" if walk["truly_steps"] else "It does not truly step")
    return (f"{kind}. {n['steps']} swings with a sole wholly off the floor in {n['seconds']:.0f} s "
            f"({round(100 * n['step_fraction'])} percent of the steps the gait commands), median clearance {n['median_clearance_mm']} mm "
            f"for {n['median_swing_s']} s, the swinging foot moving {n['step_length_mm']} mm while the standing foot slips "
            f"{n['stance_slip_mm_per_step']} mm. One foot carries the load {round(100 * n['single_support_fraction'])} percent of the time, "
            f"both {round(100 * n['double_support_fraction'])} percent, neither {round(100 * n['flight_fraction'])} percent. "
            f"Forward speed {n['speed_mm_s']} mm/s, heading drift {n['yaw_rate_deg_s']} deg/s. "
            f"Peak torque {n['peak_torque_fraction']} of the limit (margin {n['torque_margin']}). "
            f"The meshes of the two legs overlapped in {round(100 * n['legs_touching_fraction'], 2)} percent of the ticks; the legs were inside the "
            f"clearance rule's margin of each other, measured on the angles the joints reached, in {round(100 * n['legs_within_margin_fraction'], 1)} percent.")


def preset_section(p: str, r: dict, out: dict) -> list:
    walk, n, env = r["walk"], r["walk"]["nominal"], r["walk"]["envelope"]
    gait = walk["gait"]
    tag = p.replace("_", "-")
    rec = out.get("recordings", {})
    md = [f"## {TITLE.get(p, p)}", "", out["robot_presets"][p], "",
          f"Mass {r['stand']['mass_kg']} kg, torso {r['stand']['torso_height_mm']} mm above the floor at the stand pose. "
          f"Slow one-foot test (lift a foot, hold 2.5 s): {'holds on either foot' if r['one_foot_test']['stands_on_one_foot'] else 'does not hold'}"
          f" (clearance {r['one_foot_test']['left']['lifted_foot_clearance_mm']} and {r['one_foot_test']['right']['lifted_foot_clearance_mm']} mm).", "",
          "### Walking", "", steps_sentence(walk), "",
          f"Gait of `microduck/gait.py`, parameters `{gait['params']}`.",
          f"Search: seed {gait['search']['seed']}, {gait['search']['generations']} generations of {gait['search']['population']}, "
          f"{gait['search']['simulated_runs']} simulated runs, {gait['search']['wall_clock_s']} s of wall clock.", ""]
    if not n["fell"]:
        md += [_table(["joint", "peak torque (N m)", "limit (N m)", "peak / limit", "time at limit", "peak speed (deg/s)", "limit (deg/s)"],
                      [(j, d["peak_torque_nm"], d["torque_limit_nm"], d["peak_torque_fraction"], d["time_at_torque_limit_fraction"],
                        d["peak_speed_deg_s"], d["speed_limit_deg_s"]) for j, d in n["demand"].items()]), "",
               f"Peak estimated supply current {n['peak_supply_current_a']} A; the 4 A limit was active {round(100 * n['supply_limited_fraction'], 1)} percent of the time.", ""]
    lh, ht, rb = walk["long_horizon"], walk["half_timestep"], walk["robustness"]
    md += [f"Long run: {_fell(lh)} over {lh['seconds']:.0f} s" + ("" if lh["fell"] else f", {lh['path_speed_mm_s']} mm/s along its path, heading drift "
                                                                   f"{lh['yaw_rate_deg_s']} deg/s ({lh['yaw_deg']} deg in all" + (": with no steering it walks a curve)" if abs(lh["yaw_deg"]) > 30 else ")")) + ".",
           f"Numerical check at half the time step: {_fell(ht)}" + ("" if ht["fell"] else f", {ht['speed_mm_s']} mm/s, {round(100 * ht['step_fraction'])} percent of steps, "
                                                                    f"clearance {ht['median_clearance_mm']} mm, peak torque {ht['peak_torque_fraction']} of the limit") + ".", "",
           f"Robustness: {rb['runs']} runs of {rb['seconds_each']:.0f} s over floor friction 0.3 to 1.0, mass 0.9 to 1.1 times, and two disturbed starts "
           f"(1.5 deg tilt, 0.03 m/s push). {rb['fell']} fell; {rb['stepping_runs']} of {rb['runs']} stepped by the test above; the leg meshes overlapped in "
           f"{rb['runs_with_legs_touching']} runs; worst peak torque {rb['worst_peak_torque_fraction']} of the limit.", "",
           _table(["floor friction", "runs", "fell", "stepping", "speed (mm/s)", "heading change in 30 s (deg)", "worst peak torque / limit"],
                  [(b["floor_friction"], b["runs"], b["fell"], b["stepping_runs"], _range(b["speed_mm_s"]), _range(b["yaw_deg"]), b["peak_torque_fraction"])
                   for b in rb["by_friction"]]), "",
           "Head mass (a point mass added at the head, `config/motion.json`):", "",
           _table(["case", "mass (kg)", "outcome", "speed (mm/s)", "heading change in 30 s (deg)", "steps made", "clearance (mm)", "peak torque / limit"],
                  [(h["case"], h["mass_kg"], _fell(h), h.get("speed_mm_s"), h.get("yaw_deg"), h.get("step_fraction"), h.get("median_clearance_mm"),
                    h.get("peak_torque_fraction")) for h in walk["head_sensitivity"]]), ""]
    if f"{p}_walk" in rec:
        md += [f"![walk]({rec[f'{p}_walk']})", ""]

    md += ["### Turning, backing and the envelope", "",
           "There is no yaw joint. The turn input is the control page's: the left step is scaled by forward minus turn and the right by forward plus turn.",
           "Any turn comes from the soles scrubbing on the floor.", "",
           "Yaw rate (deg/s) at floor friction 0.6, by forward and turn input; a dash is a point that fell, had the leg meshes overlap or was refused at some friction:", "",
           _table(["forward (rows), turn (columns)", *[str(t) for t in env["tested_turn"]]],
                  [(f, *[(next(g for g in env["grid"] if g["forward"] == f and g["turn"] == t)["yaw_rate_deg_s"]
                          if next(g for g in env["grid"] if g["forward"] == f and g["turn"] == t)["ok_at_every_friction"] else "-")
                         for t in env["tested_turn"]]) for f in env["tested_forward"]]), "",
           "Forward speed (mm/s) at the same points:", "",
           _table(["forward (rows), turn (columns)", *[str(t) for t in env["tested_turn"]]],
                  [(f, *[next(g for g in env["grid"] if g["forward"] == f and g["turn"] == t)["speed_mm_s"] for t in env["tested_turn"]])
                   for f in env["tested_forward"]]), "",
           "How the yaw rate follows the turn input at full forward:", "",
           _table(["floor friction", "deg/s per unit of turn", "deg/s at zero turn", "rises with every step of the input", "fit R squared"],
                  [(mu, v["deg_s_per_unit_turn"], v.get("deg_s_at_zero_turn"), _yes(v["monotonic"]), v["r_squared"]) for mu, v in env["turning"]["1.0"].items()]), "",
           ("Turning is proportional at full forward: the yaw rate rises with every step of the input at every tested friction and a straight line fits it."
            if env["turn_is_proportional_at_full_forward"] else
            ("Turning is not proportional, but full left and full right go the right way at every tested friction."
             if env["full_turn_goes_the_right_way_at_every_friction"] else
             "Turning is not reliable: full left and full right do not go the right way at every tested friction.")),
           f"Turning on the spot (forward 0, turn -1 and +1): {env['turn_on_the_spot_yaw_rate_deg_s'][0]} and {env['turn_on_the_spot_yaw_rate_deg_s'][1]} deg/s.", "",
           f"Envelope for the control page: forward {env['forward_range']}, turn {env['turn_range']}. A point passes if it stayed up at friction "
           f"{env['tested_floor_friction']} for {env['seconds_each']:.0f} s with the leg meshes apart and no command refused ({env['points_ok']} of {env['points']} points passed). "
           "The turn range is offered only if full left and full right go the right way at every tested friction; otherwise turning is listed as unavailable "
           "and the forward range is the one that passes with the turn input at zero.", ""]
    if f"{p}_turn" in rec:
        md += [f"![turn]({rec[f'{p}_turn']})", ""]

    stop = r["stop"]
    md += ["### Stop and power off in mid gait", "",
           f"Commands stopped at four points of a step: the watchdog goes to hold after 500 ms and the robot "
           f"{'stays up every time' if stop['watchdog_hold_stays_up'] else 'does not always stay up'}"
           + ("" if stop["watchdog_hold_stays_up"] else " (" + ", ".join(f"at {x['commands_stopped_at_s']} s: " + ("fell " + str(x["fell_how"]) if x["fell"] else "up") for x in stop["watchdog_hold"]) + ")")
           + ".",
           f"Pulses stopped (power off) at the same four points: the model {'stays up every time' if stop['power_off_stays_up'] else 'falls in some'}, "
           f"sinking {min(x['torso_drop_mm'] for x in stop['power_off'])} to {max(x['torso_drop_mm'] for x in stop['power_off'])} mm on to the servo travel stops. "
           + (f"In {stop['power_off_legs_meet']} of the 4 the pose it sinks to has the two shins or soles overlapping in the meshes "
              f"(up to {max((max(x['mesh_interference_mm3'].values()) if x['mesh_interference_mm3'] else 0.0) for x in stop['power_off'])} mm3): "
              "the model lets parts pass through each other, so on the robot the legs meet first and one sole comes down on or against the other. "
              "Where it then rests is not predicted."
              if stop["power_off_legs_meet"] else "The meshes of the legs do not overlap in the poses it sinks to."), ""]

    j = r["jump"]
    res = j["result"]
    md += ["### Jump", "",
           f"Crouch, then both hips and knees driven as fast as the servos go (firmware rate limit raised to {j['max_speed_deg_s']:.0f} deg/s). "
           f"Result: a **{res['verdict']}**. Nothing touches the floor for {res['flight_s']} s. In that time the centre of mass rises {res['com_rise_in_flight_mm']} mm "
           f"(it leaves at {res['com_speed_up_at_takeoff_m_s']} m/s upward) and the soles reach {res['feet_rise_mm']} mm, most of which is the legs being "
           f"pulled up under the body. "
           + ("It lands upright" if res["landed_upright"] else f"It falls {res['fell_how']} on landing")
           + f", peak tilt {res['max_tilt_deg']} deg, {res['travel_forward_mm']} mm forward; leg meshes overlapped: {_yes(res['legs_touched'])}. "
           "By the definition used here a jump needs 0.1 s of flight and the centre of mass rising 10 mm in it; less, with real flight, is a hop.", "",
           _table(["joint", "peak torque (N m)", "limit", "time at limit", "peak speed (deg/s)", "limit", "peak / limit"],
                  [(k, d["peak_torque_nm"], d["torque_limit_nm"], d["time_at_torque_limit_fraction"], d["peak_speed_deg_s"], d["speed_limit_deg_s"],
                    d["peak_speed_fraction"]) for k, d in res["demand"].items()]), "",
           f"The servos ask for {res['peak_supply_current_a']} A at the peak against a 4 A supply; the supply limit was active "
           f"{round(100 * res['supply_limited_fraction_of_push'])} percent of the push. "
           f"With the firmware's default {j['at_default_speed_limit']['max_speed_deg_s']:.0f} deg/s limit the same motion gives: {j['at_default_speed_limit']['verdict']}. "
           f"Upper bound: the hips can lift the body at {j['no_load_bound']['hip_lift_speed_m_s']} m/s with no load at all, a ballistic rise of "
           f"{j['no_load_bound']['ballistic_rise_mm']} mm of the centre of mass; under load it is less. With the supply limit removed (not a result, only to show "
           f"what limits it) the rise in flight is {j['not_the_result']['com_rise_in_flight_mm']} mm.", "",
           _table(["case", "verdict", "rise in flight (mm)", "soles off (mm)", "flight (s)", "lands upright"],
                  [(f"friction {f['floor_friction']}", f["verdict"], f["com_rise_in_flight_mm"], f["feet_rise_mm"], f["flight_s"], _yes(f["landed_upright"])) for f in j["friction"]]
                  + [(f["case"], f["verdict"], f["com_rise_in_flight_mm"], f["feet_rise_mm"], f["flight_s"], _yes(f["landed_upright"])) for f in j["head"]]
                  + [("half the time step", j["half_timestep"]["verdict"], j["half_timestep"]["com_rise_in_flight_mm"], j["half_timestep"]["feet_rise_mm"],
                      j["half_timestep"]["flight_s"], _yes(j["half_timestep"]["landed_upright"]))]), ""]
    if f"{p}_jump" in rec:
        md += [f"![jump, one fifth speed]({rec[f'{p}_jump']})", ""]

    s = r["sit"]
    pose = s["sit_pose_deg"]
    md += ["### Sit, power off and stand up", "",
           f"Sitting is a squat to the hip pitch limit: hip pitch {pose['left_hip_pitch']}, knee {pose['left_knee']} degrees, soles level, at 40 deg/s. "
           f"The torso comes down {s['torso_lowered_mm']} mm to {s['torso_height_sitting_mm']} mm. The limit is there because between about 65 and 75 degrees "
           "the top of each shin grazes the torso when the soles are level (up to 13 mm3 of overlap in the meshes).", "",
           f"- Lowering: {'reached the sit pose' if s['sat_down'] else 'fell'}; peak torque {s['lowering_demand']['peak_torque_fraction']} of the limit, "
           f"peak speed {s['lowering_demand']['peak_speed_fraction']} of the limit. Straight back up under power: {'reached the stand pose' if s['stood_up_without_power_off'] else 'failed'}.",
           f"- Pulses stopped in the sit pose: it {_rest(s['relaxed_rest'])}. {'It holds there' if s['relaxed_rest_holds'] else 'It does not hold'}. "
           f"With no joint friction at all: it {_rest(s['relaxed_with_no_joint_friction']['relaxed_rest'])}. "
           f"Shoved at 0.1 m/s forward and back while relaxed: {', '.join('holds' if x['relaxed_rest_holds'] else 'does not hold' for x in s['relaxed_and_shoved'])}.",
           f"- Standing up from there (enable, which drives the servos back to the sit pose from wherever the legs sank to, then up): "
           f"{'reached the stand pose upright' if s['stood_up'] else 'failed'}; "
           f"peak torque {s['rising_demand']['peak_torque_fraction']} of the limit, peak speed {s['rising_demand']['peak_speed_fraction']} of the limit.",
           f"- Pulses stopped at the stand pose instead: it {_rest(s['power_off_at_the_stand_pose'])}, sinking at up to "
           f"{s['power_off_at_the_stand_pose']['peak_sink_speed_m_s']} m/s. With the heaviest head: it {_rest(s['power_off_at_the_stand_pose_heaviest_head'])}.",
           "- Power off and on again at the stand pose: it " + _rest(s["power_cycle_at_the_stand_pose"]["rest"]) + ", and after enable it "
           + ("stands up" if s["power_cycle_at_the_stand_pose"]["stood_up_after_enable"] else
              (f"falls {s['power_cycle_at_the_stand_pose']['fell_how']}" if s["power_cycle_at_the_stand_pose"]["fell"] else
               f"does not reach the stand pose (hip pitch {s['power_cycle_at_the_stand_pose']['ends_at_deg']['hip_pitch']} degrees)"))
           + f", peak torque {s['power_cycle_at_the_stand_pose']['peak_torque_fraction']} of the limit. Parts overlapping in the meshes on the way up: "
           + _path(s["power_cycle_at_the_stand_pose"]["mesh_interference_on_the_way_up"]) + ".",
           "- Parts overlapping in the meshes on the way down and up under power: " + _path(s["mesh_interference_on_the_way"] or {}) + ". "
           "The model does not collide part with part, so an overlap listed here is a place where the real parts rub or stop.",
           f"- Parts that touched the floor at any time while sitting, resting and standing up: {', '.join(s['parts_that_touched_the_floor'])}. "
           f"Board, shield, battery, display, camera or head on the floor: {_yes(s['board_or_head_touched'])}.", "",
           _table(["joint", "rising peak torque / limit", "rising peak speed / limit"],
                  [(k, v["peak_torque_fraction"], v["peak_speed_fraction"]) for k, v in s["rising_demand_by_joint"].items()]), "",
           "Sit, rest and stand up by floor friction: " + ", ".join(f"{f['floor_friction']}: " + ("ok" if f["sat_down"] and f["relaxed_rest_holds"] and f["stood_up"] else "fails") for f in s["friction"]) + ". "
           "By head: " + ", ".join(f"{f['case']}: " + ("ok" if f["sat_down"] and f["relaxed_rest_holds"] and f["stood_up"] else "fails") for f in s["head"]) + ".", ""]
    if f"{p}_sit" in rec:
        md += [f"![sit, power off, stand up]({rec[f'{p}_sit']})", ""]
    return md


def clearance_section(out: dict) -> list:
    md = ["## The leg clearance rule", "",
          "With comb soles a single joint, inside its own limits, can swing one sole into the other. The control core (`microduck/protocol.py` and its twin",
          "`DuckControl.hpp`) therefore carries a box model of the two legs, `robot/clearance.json`: for each leg the thigh plate, the knee servo, the shin plate",
          "and the pieces of the sole (bridge, rail, each finger and the fillet at its root), each grown by half the margin.",
          "From the six commanded joint angles it places the boxes (hip roll, hip pitch and knee in turn, with its own sine so that every copy agrees to the bit)",
          "and tests shin against shin and each shin against the other thigh with the separating axis test.", "",
          "- A `J` line whose target would bring the legs together is answered `ERR CLEAR` and changes nothing.",
          "- A calibration nudge (`N`) that would do so is answered `ERR CLEAR`.",
          "- A tick whose rate-limited step would do so is not taken; the commanded angles stay where they are.", ""]
    v = out.get("leg_clearance_rule")
    if v:
        t = v["total"]
        md += [f"Checked against the exact meshes of the two legs (`scripts/validate_clearance.py`, seed {v['seed']}, margin {v['margin_mm']} mm): "
               f"{t['poses']} poses, {t['mesh_colliding']} of them colliding in the meshes. False accepts (rule says clear, meshes overlap): {t['false_accepts']}. "
               f"False rejects (meshes clear, rule refuses): {t['false_rejects']} of {t['mesh_free']} free poses, {round(100 * t['false_reject_rate_of_free_poses'], 1)} percent.", "",
               _table(["sample", "poses", "colliding in the meshes", "refused by the rule", "false accepts", "false rejects", "false reject rate of free poses"],
                      [(name, c["poses"], c["mesh_colliding"], c["rule_refuses"], c["false_accepts"], c["false_rejects"], c["false_reject_rate_of_free_poses"])
                       for name, c in v["sets"].items()]), ""]
    md += ["The rule works on commanded angles. Play in the gears, flex and a horn mounted a degree off move the real sole by a few millimetres at the end of",
           "a 160 mm leg, which is the size of the margin; the walking results above say how often the angles the joints reached were inside the margin.",
           "The rule covers leg against leg only: a shin against the torso is left to the per-joint limits.", "",
           "What a copy of the rule in another language has to reproduce, in this order: `sine` and `cosine` (the polynomial, not the library function),",
           "`_frame`, `_apply`, `_leg`, `_apart` and `legs_clear` of `microduck/protocol.py`, operation for operation in double precision; the table",
           "`robot/clearance.json`; `ERR CLEAR` for a refused `J` or `N`; and the tick that is not taken.", ""]
    return md


def files_section(out: dict, manifest: dict) -> list:
    rows = []
    for f in manifest["study"]["files"]:
        c = f["checks"]
        rows.append((f"`{f['file']}`", f["duration_s"], f["max_speed_deg_s"], c["limit_problems"], c["clamped_commands"],
                     c["refused_by_the_leg_clearance_rule"], c["least_gap_between_leg_boxes_mm"], c.get("worst_leg_mesh_overlap_mm3", "not run"),
                     _yes(f["passes_checks"])))
    return ["## Trajectories and their checks", "",
            "For the robot as built. Every row of every file is put through `protocol.Controller` (soft limits, speed limit, leg clearance rule), through the",
            "collision boxes of the two legs, and through the exact meshes of the two legs.", "",
            _table(["file", "s", "speed limit (deg/s)", "limit problems", "clamped", "refused", "least gap between leg boxes (mm)", "worst mesh overlap (mm3)", "passes"], rows), "",
            f"`trajectories/manifest.json` is in the shape the control page reads: gait parameters `{manifest['gait']['params']}`, forward {manifest['gait']['forward']}, "
            f"turn {manifest['gait']['turn']}, motions {', '.join(manifest['motions'])}; unavailable: {', '.join(manifest['unavailable']) or 'none'}. "
            "The jump is listed as unavailable with its reason and its file is kept in `trajectories/restricted/`.", ""]


def markdown(out: dict, manifest: dict | None = None) -> str:
    import json
    from .protocol import ROOT
    if manifest is None:
        with open(ROOT / "trajectories" / "manifest.json", encoding="utf-8") as handle:
            manifest = json.load(handle)
    presets = out["presets"]
    names = list(presets)
    phys = out["physics"]
    md = ["# Motion study: walk, turn, jump, sit", "",
          "Generated by `scripts/run_motion.py` from `reports/motion.json`. Do not edit by hand.", "",
          "What the MuJoCo model of the robot does when asked to walk, turn, jump, sit down, stand up, stop and lose power, with the servos, the command path",
          "and the floor modelled as described below. All numbers on this page are simulation results; none has been measured on the robot.",
          "The robot is the one in `robot/microduck.xml`: comb soles and the default head. The same robot with flat soles is run for comparison.", "",
          "## Result", ""]
    rows = []

    def row(label, f):
        rows.append([label] + [f(presets[p]) for p in names])

    row("mass (kg)", lambda r: r["stand"]["mass_kg"])
    row("stands on one foot (slow lift test)", lambda r: _yes(r["one_foot_test"]["stands_on_one_foot"]))
    row("truly steps", lambda r: _yes(r["walk"]["truly_steps"]))
    row("forward speed (mm/s)", lambda r: r["walk"]["nominal"].get("speed_mm_s"))
    row("one foot loaded, fraction of time", lambda r: r["walk"]["nominal"].get("single_support_fraction"))
    row("median swing clearance (mm)", lambda r: r["walk"]["nominal"].get("median_clearance_mm"))
    row("median swing time (s)", lambda r: r["walk"]["nominal"].get("median_swing_s"))
    row("standing-foot slip per step (mm)", lambda r: r["walk"]["nominal"].get("stance_slip_mm_per_step"))
    row("walk peak torque / limit", lambda r: r["walk"]["nominal"].get("peak_torque_fraction"))
    row("heading drift walking straight (deg/s)", lambda r: r["walk"]["nominal"].get("yaw_rate_deg_s"))
    row("stays up 120 s", lambda r: _yes(not r["walk"]["long_horizon"]["fell"]))
    row("falls in the 30 perturbed runs", lambda r: r["walk"]["robustness"]["fell"])
    row("perturbed runs that step", lambda r: r["walk"]["robustness"]["stepping_runs"])
    row("worst peak torque / limit in those runs", lambda r: r["walk"]["robustness"]["worst_peak_torque_fraction"])
    row("turning proportional at full forward", lambda r: _yes(r["walk"]["envelope"]["turn_is_proportional_at_full_forward"]))
    row("yaw rate at turn -1 / 0 / +1, full forward (deg/s)", lambda r: " / ".join(str(v) for v in r["walk"]["envelope"]["turning"]["1.0"]["0.6"]["yaw_rate_deg_s"][::2]))
    row("envelope: forward, turn", lambda r: f"{r['walk']['envelope']['forward_range']}, {r['walk']['envelope']['turn_range']}")
    row("commands stop in mid gait: stays up", lambda r: _yes(r["stop"]["watchdog_hold_stays_up"]))
    row("power off in mid gait: stays up", lambda r: _yes(r["stop"]["power_off_stays_up"]))
    row("jump", lambda r: r["jump"]["result"]["verdict"])
    row("flight (s), centre of mass rise in flight (mm)", lambda r: f"{r['jump']['result']['flight_s']}, {r['jump']['result']['com_rise_in_flight_mm']}")
    row("lands upright", lambda r: _yes(r["jump"]["result"]["landed_upright"]))
    row("sits down and stands up again", lambda r: _yes(r["sit"]["sat_down"] and r["sit"]["stood_up"]))
    row("power off in the squat: holds", lambda r: _yes(r["sit"]["relaxed_rest_holds"]))
    row("power off at the stand pose: stays up", lambda r: _yes(r["sit"]["power_off_at_the_stand_pose"]["holds"]))
    row("board, battery, display or camera on the floor", lambda r: _yes(r["sit"]["board_or_head_touched"]))
    md += [_table(["", *[TITLE.get(p, p) for p in names]], rows), "",
           "\"Truly steps\" means: it stayed up, at least 80 percent of the commanded steps happened with the whole sole 1 mm or more",
           "off the floor for 60 ms or more while the other foot carried the load, left and right in turn, and it went forward.", ""]

    md += ["## What the model includes", "",
           "Published: servo stall torque and no-load speed at 4.8 V (SR431 1.196 N m, 300 deg/s; SR311 0.304 N m, 429 deg/s),",
           "the 5 V 4 A supply, the masses of the servos. Position servos behind `protocol.Controller` with the soft limits of `robot/joints.json`",
           "and the leg clearance rule. A result obtained by loosening any of this is not shown as a result.", "",
           _table(["parameter", "value", "why"], [(k, v["value"], v["why"]) for k, v in phys.items()]), "",
           "The servo is a torque source: zero inside the dead zone (dead band plus half the gear play), then proportional,",
           "saturating at stall torque, with joint damping of stall torque over no-load speed so that speed falls with load.",
           "The firmware's own rate limit is " + str(out["firmware"]["max_speed_deg_s"]["value"]) + " deg/s; walking, turning, sitting and standing up stay inside it.",
           "A command sent by the host moves the servo 40 ms later (transport, then one PWM frame). For a motion played open loop that only shifts",
           "the whole motion in time; it matters to anything that closes a loop through the host, such as a gamepad.",
           "The joints are free over the whole servo travel in the model; the soft limits act on the commands, and a relaxed joint runs to its travel stop.",
           "As in the generated model, parts collide with the floor only. The generated collision boxes are bounding boxes of slices of the parts and stand closer",
           "together than the comb soles really do, so leg against leg is not simulated on them: after each run the joint angles the simulation reached are tested",
           "with the clearance rule's boxes and, where those are within the margin, with the exact meshes. A mesh overlap is reported as the legs touching.",
           "Not modelled: flex of the printed parts beyond the one series spring per joint (the soles are rigid), supply voltage sag below the",
           "current limit, servo heating, cable drag, and any mounting error of the horns.", "",
           f"Head: a point mass of {out['head']['extra_mass_g']} g at {out['head']['position_mm']} mm in the torso frame is added to the generated torso",
           "(`config/motion.json`). Zero means the torso as generated, which carries the default head. Set it and rerun to see the effect of another head.", ""]

    for p in names:
        md += preset_section(p, presets[p], out)
    md += clearance_section(out)
    md += files_section(out, manifest)
    search = out["search"]
    md += ["## Search budget", "",
           f"`scripts/optimise_motion.py`: {search['total_candidates']} candidates, {search['total_simulated_runs']} simulated runs, "
           f"{search['total_wall_clock_s']} s of wall clock on seven worker processes, no GPU. Each search is bounded by a fixed number of generations and a wall-clock limit. "
           f"Every gait candidate is run straight for {search['straight_run_s']:.0f} s on these copies of the robot and scored on the mean and the worst, "
           f"and for {search['turn_run_s']:.0f} s with the turn input at {search['turn_input']} each way:", "",
           _table(["floor friction", "mass scale", "start tilt roll, pitch (deg)", "start push x, y (m/s)"],
                  [(s["floor_friction"], s["mass_scale"], s["start_tilt_deg"], s["start_push_m_s"]) for s in search["scenarios"]]), "",
           "The gait score rewards staying up, forward distance, steps made with a sole off the floor and turning the right way; it charges for heading drift,",
           "sideways drift, tilt over 20 degrees, peak torque above 0.8 of the limit, time at the supply limit, the legs coming inside the clearance margin of each other",
           "and commands the clearance rule refuses.", ""]
    md += REAL
    md += ["## Files", "",
           "- `config/motion.json`: every parameter of the model. `config/presets.json`: the comparison preset. `config/gaits.json`: the searched motions.",
           "- `config/gait_motion.json`: the gait parameters for the robot as built, in the format of `config/gait.json`.",
           "- `robot/clearance.json`: the boxes of the leg clearance rule. `reports/clearance.json`: its validation.",
           "- `trajectories/manifest.json`, `trajectories/gait_params.json`: the motions and the tested envelope for the control page.",
           "- `reports/motion.json`: all numbers on this page and the rows behind them.", ""]
    return "\n".join(md) + "\n"


REAL = [
    "## On the robot: what to expect", "",
    "- These are predictions of a model whose dead band, backlash, compliance, friction and delays are estimates. Start with the slowest motions: stand, sit,",
    "  stand up, then single slow steps with the robot held, then the walk at a low forward input.",
    "- The jump can strip gears or break parts. It drives four servos at stall torque from a supply that cannot feed them, lands on hard plates, and needs the",
    "  firmware speed limit raised. It is listed as unavailable in the manifest and kept in `trajectories/restricted/`; in simulation it is only a hop.",
    "- Supply current: the walk's estimated peak is in the table above. The servos share one 5 V 4 A supply; a motion that asks for more is slowed in the model",
    "  and browns out the real supply.",
    "- Power off: see what the robot rests on above. It sinks quickly when the pulses stop at the stand pose. Lower it to the squat under power before",
    "  switching off, and check on the real parts what the legs come to rest against.",
    "- The comb soles pass each other with a few millimetres to spare. The leg clearance rule keeps the commands apart; play and a horn mounted off its zero",
    "  can still bring the real soles together. Set the zeros (`scripts/calibrate.py`) before the first step.",
    "- Heading drifts when walking straight and the drift changes with the floor. Expect to steer.", "",
]
