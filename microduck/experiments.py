# SPDX-License-Identifier: MIT
"""The simulation experiments: stand, fall from neutral, watchdog, open-loop
gait and its parameter sweep. Writes reports/sim.json, docs/simulation.md,
trajectories/*.csv and, if offscreen rendering works, docs/images/sim-*.gif.
"""
from __future__ import annotations

import itertools
import json

import numpy as np

from . import gait, model, protocol, sim
from .protocol import JOINTS, ROOT

SWEEP = {"period_s": (0.6, 1.0, 1.6), "roll_amplitude_deg": (4.0, 8.0, 14.0),
         "step_amplitude_deg": (0.0, 6.0, 12.0), "lift_deg": (0.0, 8.0)}
GAIT_SECONDS = 12.0


def _run_gait(s: sim.DuckSim, params: dict, seconds: float = GAIT_SECONDS, mu: float | None = None) -> dict:
    s.reset("stand")
    if mu is not None:
        s.set_floor_friction(mu)
    result = sim.play(s, gait.gait(s.cal.stand_deg, params, seconds))
    walking = max(seconds - params["lead_in_s"], 1e-6)
    result["speed_mm_s"] = round(result["distance_forward_m"] * 1000.0 / walking, 1) if not result["fell"] else None
    return result


def supply_estimate(result: dict, hardware: dict) -> dict:
    """Rough supply current: stall current scaled by torque over stall torque."""
    peak = mean = 0.0
    for joint, t in result["torque"].items():
        stall = hardware["servos"][model.servo_for_joint(joint)]["assumed"]["stall_current_a"]["value"]
        peak += stall * min(1.0, t["peak_nm"] / t["limit_nm"])
        mean += stall * min(1.0, t["mean_nm"] / t["limit_nm"])
    return {"mean_a": round(mean, 2), "sum_of_peaks_a": round(peak, 2)}


def run(progress=print, record: bool = True) -> dict:
    hardware = model.load_json("hardware.json")
    s = sim.DuckSim()
    stand_deg = s.cal.stand_deg
    mu0 = float(s.model.geom_friction[s.floor][0])
    out = {"generated_by": "scripts/run_sim.py",
           "status": "simulation only; the robot has never been assembled or powered",
           "model": "robot/microduck.xml", "floor_friction": mu0,
           "timestep_s": float(s.model.opt.timestep), "controller_tick_ms": protocol.TICK_MS,
           "max_speed_deg_s": s.cal.max_speed_deg_s}

    progress("stand")
    trajectory = gait.stand(stand_deg, 10.0)
    gait.write_csv(ROOT / "trajectories" / "stand.csv", trajectory)
    s.reset("stand")
    out["stand"] = sim.play(s, trajectory)
    out["stand"]["supply_estimate"] = supply_estimate(out["stand"], hardware)

    progress("neutral pose")
    s.reset("neutral")
    out["neutral"] = sim.play(s, gait.stand([0.0] * 6, 5.0))

    progress("relax from the stand pose")
    s.reset("stand")
    s.send("E")
    for _ in range(25):
        s.send(protocol.format_joints(stand_deg))
        s.tick()
    s.send("R")
    for _ in range(250):
        s.tick()
    out["relax_from_stand"] = {"fell": s.fell_at is not None, "fell_at_s": s.fell_at, "fell_how": s.fell_how,
                               "relaxed_at_s": 0.5}

    progress("default gait")
    params = gait.load_params()
    trajectory = gait.gait(stand_deg, params, GAIT_SECONDS)
    gait.write_csv(ROOT / "trajectories" / "gait.csv", trajectory)
    out["gait_default"] = {"params": params, **_run_gait(s, params)}
    out["gait_default"]["supply_estimate"] = supply_estimate(out["gait_default"], hardware)
    out["gait_default"]["limit_problems"] = len(gait.check_limits(trajectory, s.cal))

    progress("watchdog: commands stop in mid gait")
    s.reset("stand")
    s.send("E")
    for t, q in trajectory:
        if t > 4000:
            break
        while s.now_ms < t:
            s.tick()
        s.send(protocol.format_joints(q))
    for _ in range(300):
        s.tick()
    out["watchdog_hold"] = {"commands_stopped_at_s": 4.0, "mode_after": s.controller.mode,
                            "fell": s.fell_at is not None, "fell_at_s": s.fell_at,
                            "status_line": s.send("S")}

    progress("gait parameter sweep")
    rows = []
    keys = list(SWEEP)
    for values in itertools.product(*SWEEP.values()):
        p = dict(params, **dict(zip(keys, values)))
        r = _run_gait(s, p)
        playable = not gait.check_limits(gait.gait(stand_deg, p, 3.0 * p["period_s"] + p["lead_in_s"]), s.cal)
        rows.append({**{k: p[k] for k in keys}, "within_speed_limit": playable, "fell": r["fell"], "fell_at_s": r["fell_at_s"], "fell_how": r["fell_how"],
                     "distance_forward_m": r["distance_forward_m"], "drift_left_m": r["drift_left_m"],
                     "speed_mm_s": r["speed_mm_s"], "max_tilt_deg": r["max_tilt_deg_while_upright"],
                     "single_support_fraction": r["feet"]["single_support_fraction"],
                     "max_sole_lift_mm": max(r["feet"]["max_whole_sole_lift_mm"].values()),
                     "peak_torque_fraction": max(t["peak_fraction_of_limit"] for t in r["torque"].values())})
    upright = [r for r in rows if not r["fell"]]
    candidates = [r for r in upright if r["within_speed_limit"]]
    best = max(candidates, key=lambda r: r["distance_forward_m"]) if candidates else None
    out["gait_sweep"] = {"runs": len(rows), "fell": len(rows) - len(upright), "seconds_each": GAIT_SECONDS,
                         "over_speed_limit": sum(1 for r in rows if not r["within_speed_limit"]),
                         "best": best, "rows": rows}

    if best:
        progress("best gait: friction sensitivity")
        best_params = dict(params, **{k: best[k] for k in keys})
        gait.write_csv(ROOT / "trajectories" / "gait_best.csv", gait.gait(stand_deg, best_params, GAIT_SECONDS))
        out["gait_best"] = {"params": best_params, **_run_gait(s, best_params)}
        out["gait_best"]["supply_estimate"] = supply_estimate(out["gait_best"], hardware)
        out["friction_sensitivity"] = []
        for mu in (0.3, 0.6, 1.0):
            r = _run_gait(s, best_params, mu=mu)
            out["friction_sensitivity"].append({"floor_friction": mu, "fell": r["fell"], "fell_at_s": r["fell_at_s"],
                                                "distance_forward_m": r["distance_forward_m"], "speed_mm_s": r["speed_mm_s"]})
        s.set_floor_friction(mu0)

    out["recordings"] = {}
    if record:
        progress("recording")
        try:
            from . import record as recorder
            out["recordings"] = recorder.record_all(out)
            out["offscreen_rendering"] = "worked"
        except Exception as error:  # no GL context on this machine
            out["offscreen_rendering"] = f"failed: {type(error).__name__}: {error}"

    (ROOT / "reports").mkdir(exist_ok=True)
    out["suggestions"] = suggestions()
    out["verdict"] = verdict(out)
    (ROOT / "reports" / "sim.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "docs" / "simulation.md").write_text(markdown(out), encoding="utf-8", newline="\n")
    return out


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _torque_table(result: dict) -> str:
    return _table(["joint", "mean (N m)", "peak (N m)", "limit (N m)", "peak / limit", "time at the limit"],
                  [(j, t["mean_nm"], t["peak_nm"], t["limit_nm"], t["peak_fraction_of_limit"], t["saturated_fraction_of_time"])
                   for j, t in result["torque"].items()])


def verdict(out: dict) -> dict:
    """Plain statements of what the simulation showed."""
    st, ne, gd = out["stand"], out["neutral"], out["gait_default"]
    best = out.get("gait_best")
    text = {
        "stand": (f"Stands for the whole {st['duration_s']} s run at the stand pose; peak tilt {st['max_tilt_deg_while_upright']} deg."
                  if not st["fell"] else f"Falls {st['fell_how']} at {st['fell_at_s']} s from the stand pose."),
        "neutral": (f"With the legs straight down it falls {ne['fell_how']} at {ne['fell_at_s']} s, as the assembly test predicted."
                    if ne["fell"] else "With the legs straight down it stays up, which the assembly test did not predict."),
    }
    if gd["fell"]:
        text["gait"] = f"The default gait falls {gd['fell_how']} at {gd['fell_at_s']} s."
    else:
        lift = max(gd["feet"]["max_whole_sole_lift_mm"].values())
        text["gait"] = (f"The default gait stays up for {gd['duration_s']} s and moves {round(gd['distance_forward_m'] * 1000)} mm forward "
                        f"({gd['speed_mm_s']} mm/s). It is a shuffle, not a walk: the highest a whole sole comes off the floor is "
                        f"{lift} mm, and both feet stay loaded {round(gd['feet']['both_loaded_fraction'] * 100)} percent of the time.")
    if best:
        sweep = out["gait_sweep"]
        text["best"] = (f"Best of {sweep['runs']} parameter sets that stay inside the speed limit as written: "
                        f"{round(best['distance_forward_m'] * 1000)} mm in {sweep['seconds_each']} s ({best['speed_mm_s']} mm/s). "
                        f"{sweep['fell']} sets fell; {sweep['over_speed_limit']} ask for more than the speed limit and are slowed by the controller.")
    return text


def markdown(out: dict) -> str:
    v = verdict(out)
    st, gd = out["stand"], out["gait_default"]
    md = ["# Simulation results", "",
          "Generated by `scripts/run_sim.py` with MuJoCo from `robot/microduck.xml`. Do not edit by hand.",
          "The numbers are also in `reports/sim.json`.", "",
          "Status: simulation only. The robot has never been assembled or powered.", "",
          "## What happened", ""]
    md += [f"- {line}" for line in v.values()]
    md += ["", "## How the servos are modelled", "",
           "Each joint is a position actuator with the stall torque the maker gives at 4.8 V as its force limit and a joint",
           "damping of stall torque over no-load speed, which gives the published speed with no load and less under load.",
           f"Commands pass through the same controller the firmware runs: soft limits, {out['max_speed_deg_s']} deg/s speed limit, watchdog,",
           f"{out['controller_tick_ms']} ms tick. Floor friction {out['floor_friction']} (assumed). Only the floor is a contact surface; parts of the robot",
           "do not collide with each other in the simulation, the joint limits from the assembly test stand in for that.",
           "No backlash, no cable-tie compliance, no flex in the printed parts.", "",
           "## Standing", "", v["stand"], "", _torque_table(st), "",
           f"Estimated supply current while standing: {st['supply_estimate']['mean_a']} A "
           "(stall current scaled by torque; stall currents are assumed, see docs/power.md).", "",
           "## Legs straight down", "", v["neutral"], "",
           "## Servos relaxed", "",
           (f"With the pulses stopped at the stand pose the robot falls {out['relax_from_stand']['fell_how']} "
            f"{round(out['relax_from_stand']['fell_at_s'] - out['relax_from_stand']['relaxed_at_s'], 2)} s later. "
            "So the watchdog's default action is hold, not relax."
            if out["relax_from_stand"]["fell"] else
            "With the pulses stopped at the stand pose the robot stays up in the simulation, held by the assumed gear friction."), "",
           "## Watchdog", "",
           f"Commands stopped at {out['watchdog_hold']['commands_stopped_at_s']} s in mid gait. Controller afterwards: "
           f"`{out['watchdog_hold']['status_line']}`. Fell: {out['watchdog_hold']['fell']}.", "",
           "## Open-loop gait", "", v["gait"], "",
           f"Parameters: `{json.dumps(gd['params'] and {k: gd['params'][k] for k in gd['params'] if not k.startswith('_')})}`", "",
           _torque_table(gd), "",
           f"Feet: both loaded {gd['feet']['both_loaded_fraction']}, one loaded {gd['feet']['single_support_fraction']}, "
           f"neither {gd['feet']['airborne_fraction']} of the time; highest lift of a whole sole "
           f"{gd['feet']['max_whole_sole_lift_mm']} mm.", ""]
    if "gait" in out.get("recordings", {}):
        md += [f"![gait]({out['recordings']['gait']})", ""]
    sweep = out["gait_sweep"]
    md += ["## Parameter sweep", "", v.get("best", "Every parameter set fell."), "",
           _table(["period (s)", "roll (deg)", "step (deg)", "lift (deg)", "inside speed limit", "fell", "forward (mm)", "left (mm)", "max tilt (deg)",
                   "one-foot time", "sole lift (mm)", "peak torque / limit"],
                  [(r["period_s"], r["roll_amplitude_deg"], r["step_amplitude_deg"], r["lift_deg"], "yes" if r["within_speed_limit"] else "no",
                    f"{r['fell_how']} at {r['fell_at_s']} s" if r["fell"] else "no",
                    round(r["distance_forward_m"] * 1000), round(r["drift_left_m"] * 1000), r["max_tilt_deg"],
                    r["single_support_fraction"], r["max_sole_lift_mm"], r["peak_torque_fraction"]) for r in sweep["rows"]]), ""]
    if "gait_best" in out:
        md += ["## Best set and floor friction", "",
               _table(["floor friction", "fell", "forward (mm)", "speed (mm/s)"],
                      [(r["floor_friction"], r["fell"], round(r["distance_forward_m"] * 1000), r["speed_mm_s"])
                       for r in out["friction_sensitivity"]]), ""]
        if "gait_best" in out.get("recordings", {}):
            md += [f"![best gait]({out['recordings']['gait_best']})", ""]
    if "neutral" in out.get("recordings", {}):
        md += ["## Recordings", "", f"![fall from neutral]({out['recordings']['neutral']})", ""]
    md += ["## What the simulation suggests changing", "",
           "Suggestions only; none of this has been done.", ""]
    md += [f"- {line}" for line in suggestions()]
    return "\n".join(md) + "\n"


def suggestions() -> list:
    with open(ROOT / "reports" / "assembly.json", encoding="utf-8") as handle:
        report = json.load(handle)
    rep = report["variants"][report["selected"]]
    hip_x = rep["dimensions"]["joint_origins_mm"]["left_hip_pitch"][0]
    stance = rep["dimensions"]["stance_width_between_foot_centres_mm"]
    one = abs(rep["balance"]["one_foot_left"]["at_stand_pose"]["margin_mm"])
    swing = rep["balance"]["stand_pose"]["thigh_swing_deg"]
    return [
        f"Move the hips back under the body. The hip pitch axis is {hip_x:.0f} mm ahead of the torso origin, so with straight legs "
        f"the centre of mass is behind the heels and the robot only stands with the thighs swung {swing:.0f} degrees back.",
        f"Bring the feet together. The foot centres are {stance:.0f} mm apart and the centre of mass is {one:.0f} mm outside either "
        "foot, so the weight cannot be put on one foot and the gait can only shuffle.",
        "Add an ankle roll joint, or shape the soles as a rocker, so a weight shift tilts the body over a foot instead of tipping "
        "the feet onto their edges. With six servos this means giving up a knee or a hip joint on each leg.",
        "Add hip yaw or accept that the robot cannot turn: with roll and pitch only it has no way to change heading except by slipping.",
        "Check the soles on the real floor. The shuffle is a sliding gait, and the contact model is the least certain part of the simulation.",
    ]
