# SPDX-License-Identifier: MIT
"""The motion study: walk, turn, jump, sit, stand up, stop and power off, on
the robot as generated (comb soles) and, for comparison, on the same robot
with flat soles, with the servo and command-path model of
microduck/motionsim.py.

Reads the searched motions from config/gaits.json (scripts/optimise_motion.py
writes it) and writes reports/motion.json, docs/motion.md, the trajectories
with trajectories/manifest.json and trajectories/gait_params.json, and the
recordings in docs/images/motion-*.gif.
"""
from __future__ import annotations

import json
from dataclasses import replace

import mujoco
import numpy as np

from . import gait as gaitfile
from . import gaitsearch, motiongen, motionsim, protocol, variant
from .protocol import JOINTS, ROOT

PRESETS = ("comb", "flat_feet")
DEFAULT = "comb"                # the robot the trajectories are for
WALK_SECONDS = 30.0
LONG_SECONDS = 120.0
ROBUST_FRICTION = (0.3, 0.45, 0.6, 0.8, 1.0)
ROBUST_MASS = (0.9, 1.0, 1.1)
ROBUST_START = (((1.5, 1.5), (0.02, 0.02)), ((-1.5, -1.0), (-0.02, 0.03)))
ENVELOPE_FORWARD = (-1.0, -0.5, 0.0, 0.5, 1.0)
ENVELOPE_TURN = (-1.0, -0.5, 0.0, 0.5, 1.0)
ENVELOPE_FRICTION = (0.4, 0.6, 0.9)
ENVELOPE_SECONDS = 20.0
SIT_SPEED_DEG_S = 40.0
HEAD_CASES = (("default head", {}),
              ("20 g more at the head", {"extra_mass_g": 20.0}),
              ("32 g more: the heaviest turning head, 57 g at the head", {"extra_mass_g": 32.0}),
              ("32 g more, 20 mm further forward", {"extra_mass_g": 32.0, "position_mm": [80.0, 0.0, 80.0]}),
              ("32 g more, 30 mm higher", {"extra_mass_g": 32.0, "position_mm": [60.0, 0.0, 110.0]}))


_MESH: dict = {}


def make_sim(preset, **kw) -> motionsim.MotionSim:
    """A simulator with the exact leg meshes attached when the preset keeps
    the generated soles, so that 'the legs touched' means the meshes did."""
    sim = motionsim.MotionSim(preset, **kw)
    if sim.cal.clearance is not None:
        from . import clearance, model
        if model.have_stls():
            if "legs" not in _MESH:
                _MESH["legs"] = clearance.MeshLegs()
            sim.mesh = _MESH["legs"]
    return sim


def interference(q_deg, preset=DEFAULT) -> dict:
    """Exact mesh interference of the whole robot at a pose: pairs of parts
    and the overlapping volume (mm3), without the pairs that already touch at
    the neutral pose. Only for the robot as generated."""
    if preset != DEFAULT:
        return {}
    from . import assembly, model
    if "robot" not in _MESH:
        robot = model.build_robot()
        threshold = robot.assumptions["interference_threshold_mm3"]
        ignore = {frozenset((f["a"], f["b"])) for f in assembly.interferences(robot.placed(), threshold)}
        _MESH["robot"] = (robot, threshold, ignore)
    robot, threshold, ignore = _MESH["robot"]
    found = assembly.interferences(robot.placed(dict(zip(JOINTS, [float(v) for v in q_deg]))), threshold)
    return {f"{f['a']} and {f['b']}": f["volume_mm3"] for f in found if frozenset((f["a"], f["b"])) not in ignore}


def path_interference(logs: list, preset=DEFAULT, poses: int = 12) -> dict:
    """The worst mesh interference over poses sampled along simulated runs."""
    worst = {}
    for log in logs:
        rows = log["joint"]
        for i in np.linspace(0, len(rows) - 1, poses).astype(int):
            for pair, volume in interference(np.round(rows[i], 1), preset).items():
                if volume > worst.get(pair, {"mm3": 0.0})["mm3"]:
                    worst[pair] = {"mm3": volume, "at_hip_pitch_deg": round(float(rows[i][1]), 1), "at_knee_deg": round(float(rows[i][2]), 1)}
    return worst


def load_gaits() -> dict:
    with open(ROOT / "config" / "gaits.json", encoding="utf-8") as handle:
        return json.load(handle)


def walk_trajectory(cal, entry: dict, seconds: float, forward: float = 1.0, turn: float = 0.0) -> tuple:
    """Trajectory of the gait and the time steady walking starts."""
    p = entry["params"]
    lead = p.get("lead_in_s", gaitsearch.LEAD_IN_S)
    return motiongen.walk(cal.stand_deg, p, seconds, forward, turn, lead, cal.max_speed_deg_s, cal), lead + p["period_s"]


def _demand_summary(demand: dict) -> dict:
    return {"peak_torque_fraction": max(v["peak_torque_fraction"] for v in demand.values()),
            "peak_speed_fraction": max(v["peak_speed_fraction"] for v in demand.values()),
            "time_at_torque_limit_fraction": max(v["time_at_torque_limit_fraction"] for v in demand.values())}


def walk_run(sim: motionsim.MotionSim, entry: dict, seconds: float, forward: float = 1.0, turn: float = 0.0,
             tilt=(0.0, 0.0), push=(0.0, 0.0), detail: bool = False) -> dict:
    sim.reset(tilt_deg=tilt, push_m_s=push)
    trajectory, t0 = walk_trajectory(sim.cal, entry, seconds, forward, turn)
    log = motionsim.run(sim, trajectory)
    t = log["t"]
    end = log["fell_at"] if log["fell_at"] is not None else t[-1]
    window = (t >= t0) & (t <= end)
    out = {"fell": log["fell_at"] is not None, "fell_at_s": log["fell_at"], "fell_how": log["fell_how"], "seconds": seconds,
           "legs_touching_fraction": round(gaitsearch.touching_fraction(log), 4),
           "legs_within_margin_fraction": round(float(log["near"].mean()), 4),
           "commands_refused_fraction": round(gaitsearch.refused_fraction(sim.cal, trajectory), 4)}
    if window.sum() < 10:
        out.update({"speed_mm_s": 0.0, "yaw_rate_deg_s": 0.0, "steps": 0, "single_support_fraction": 0.0})
        return out
    pos = log["pos"][window]
    walked = float(t[window][-1] - t[window][0])
    yaw = np.degrees(np.unwrap(np.radians(log["yaw"][window])))
    heading = np.radians(yaw[0])
    along = (pos[-1][0] - pos[0][0]) * np.cos(heading) + (pos[-1][1] - pos[0][1]) * np.sin(heading)
    st = motionsim.stepping(log, t0)
    swings = st.pop("swings")
    demand = motionsim.demand(sim, log, t0)
    expected = 2.0 * walked / entry["params"]["period_s"]
    # distance along the path, from positions one gait period apart (the sway within a period is not travel)
    per = max(1, int(round(entry["params"]["period_s"] * 1000 / protocol.TICK_MS)))
    path = float(np.sum(np.linalg.norm(np.diff(pos[::per, :2], axis=0), axis=1)))
    out.update({"forward_mm": round(float(along) * 1000.0, 1),
                "sideways_mm": round(float(pos[-1][1] - pos[0][1]) * 1000.0, 1),
                "speed_mm_s": round(float(along) * 1000.0 / walked, 1),
                "path_speed_mm_s": round(path * 1000.0 / walked, 1),
                "yaw_deg": round(float(yaw[-1] - yaw[0]), 1), "yaw_rate_deg_s": round(float(yaw[-1] - yaw[0]) / walked, 2),
                "max_tilt_deg": round(float(log["tilt"][window].max()), 1),
                "expected_steps": round(expected, 1), "step_fraction": round(min(1.0, st["steps"] / max(expected, 1.0)), 3),
                **st, **_demand_summary(demand),
                "torque_margin": round(1.0 - max(v["peak_torque_fraction"] for v in demand.values()), 3),
                "peak_supply_current_a": round(float(log["current"][window].max()), 2),
                "supply_limited_fraction": round(float((log["current"][window] > sim.supply_a).mean()), 3)})
    if detail:
        out["demand"] = demand
        out["first_swings"] = swings[:8]
    return out


def truly_steps(run: dict) -> bool:
    """The test for 'it steps': it stayed up, at least 8 of 10 expected
    steps happened with a sole wholly off the floor by 1 mm or more, left and
    right in turn, and it went forward."""
    return bool(not run["fell"] and run.get("step_fraction", 0.0) >= 0.8 and run.get("alternating") and run.get("speed_mm_s", 0.0) > 1.0)


def _ok(run: dict) -> bool:
    """Stayed up, no command was refused, and the meshes of the legs never touched."""
    return not run["fell"] and run["legs_touching_fraction"] == 0.0 and run["commands_refused_fraction"] == 0.0


def walking(preset: str, entry: dict, progress) -> dict:
    out = {"gait": entry}
    sim = make_sim(preset)
    progress(f"{preset}: walk {WALK_SECONDS:.0f} s")
    out["nominal"] = walk_run(sim, entry, WALK_SECONDS, detail=True)
    out["truly_steps"] = truly_steps(out["nominal"])
    progress(f"{preset}: walk {LONG_SECONDS:.0f} s")
    long = walk_run(sim, entry, LONG_SECONDS)
    out["long_horizon"] = {k: long.get(k) for k in ("fell", "fell_at_s", "fell_how", "seconds", "speed_mm_s", "path_speed_mm_s", "yaw_deg", "yaw_rate_deg_s",
                                                    "steps", "step_fraction", "legs_touching_fraction")}
    progress(f"{preset}: half time step")
    fine = walk_run(make_sim(preset, physics={"timestep_s": 0.001}), entry, WALK_SECONDS)
    out["half_timestep"] = {k: fine.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "steps", "step_fraction", "median_clearance_mm",
                                                     "peak_torque_fraction")}

    progress(f"{preset}: robustness")
    rows = []
    for mass in ROBUST_MASS:
        s = make_sim(preset, mass_scale=mass)
        for mu in ROBUST_FRICTION:
            s.set_floor_friction(mu)
            for tilt, push in ROBUST_START:
                r = walk_run(s, entry, WALK_SECONDS, tilt=tilt, push=push)
                rows.append({"floor_friction": mu, "mass_scale": mass, "start_tilt_deg": list(tilt), "start_push_m_s": list(push),
                             **{k: r.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "step_fraction", "alternating",
                                                      "median_clearance_mm", "single_support_fraction", "peak_torque_fraction",
                                                      "legs_touching_fraction")}})
    up = [r for r in rows if not r["fell"]]
    by_mu = []
    for mu in ROBUST_FRICTION:
        sub = [r for r in rows if r["floor_friction"] == mu]
        ok = [r for r in sub if not r["fell"]]
        by_mu.append({"floor_friction": mu, "runs": len(sub), "fell": len(sub) - len(ok),
                      "speed_mm_s": [min(r["speed_mm_s"] for r in ok), max(r["speed_mm_s"] for r in ok)] if ok else None,
                      "yaw_deg": [min(r["yaw_deg"] for r in ok), max(r["yaw_deg"] for r in ok)] if ok else None,
                      "peak_torque_fraction": max(r["peak_torque_fraction"] for r in ok) if ok else None,
                      "stepping_runs": sum(1 for r in ok if r["step_fraction"] >= 0.8 and r["alternating"])})
    out["robustness"] = {"runs": len(rows), "seconds_each": WALK_SECONDS, "fell": len(rows) - len(up),
                         "stepping_runs": sum(1 for r in up if r["step_fraction"] >= 0.8 and r["alternating"]),
                         "runs_with_legs_touching": sum(1 for r in rows if r["legs_touching_fraction"] > 0.0),
                         "speed_mm_s": [min(r["speed_mm_s"] for r in up), max(r["speed_mm_s"] for r in up)] if up else None,
                         "yaw_deg": [min(r["yaw_deg"] for r in up), max(r["yaw_deg"] for r in up)] if up else None,
                         "worst_peak_torque_fraction": max(r["peak_torque_fraction"] for r in up) if up else None,
                         "by_friction": by_mu, "rows": rows}

    progress(f"{preset}: head mass")
    out["head_sensitivity"] = []
    for label, head in HEAD_CASES:
        s = make_sim(preset, head=head)
        r = walk_run(s, entry, WALK_SECONDS)
        out["head_sensitivity"].append({"case": label, "head": head, "mass_kg": round(s.mass, 4),
                                        **{k: r.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "step_fraction",
                                                                 "median_clearance_mm", "peak_torque_fraction", "legs_touching_fraction")}})

    progress(f"{preset}: forward and turn envelope")
    grid = []
    sims = {mu: make_sim(preset) for mu in ENVELOPE_FRICTION}
    for mu, s in sims.items():
        s.set_floor_friction(mu)
    for forward in ENVELOPE_FORWARD:
        for turn in ENVELOPE_TURN:
            runs = {mu: walk_run(s, entry, ENVELOPE_SECONDS, forward, turn) for mu, s in sims.items()}
            nominal = runs[0.6]
            grid.append({"forward": forward, "turn": turn, "ok_at_every_friction": all(_ok(r) for r in runs.values()),
                         "fell_at_friction": [mu for mu, r in runs.items() if r["fell"]],
                         "legs_touched_at_friction": [mu for mu, r in runs.items() if r["legs_touching_fraction"] > 0.0],
                         "commands_refused": nominal["commands_refused_fraction"] > 0.0,
                         "speed_mm_s": nominal.get("speed_mm_s"), "yaw_rate_deg_s": nominal.get("yaw_rate_deg_s"),
                         "speed_by_friction": {str(mu): r.get("speed_mm_s") for mu, r in runs.items()},
                         "yaw_rate_by_friction": {str(mu): r.get("yaw_rate_deg_s") for mu, r in runs.items()},
                         "peak_torque_fraction": max(r.get("peak_torque_fraction", 1.0) for r in runs.values()),
                         "step_fraction": nominal.get("step_fraction")})
    out["envelope"] = envelope(grid)
    return out


def envelope(grid: list) -> dict:
    """The forward and turn ranges for the control page: the largest
    rectangle of tested points around zero in which every point stayed up at
    every friction with the legs apart and no command refused. Also how the
    yaw rate follows the turn input."""
    ok = {(g["forward"], g["turn"]) for g in grid if g["ok_at_every_friction"]}
    best, area = ([0.0, 0.0], [0.0, 0.0]), -1.0
    for f0 in (v for v in ENVELOPE_FORWARD if v <= 0):
        for f1 in (v for v in ENVELOPE_FORWARD if v >= 0):
            for t0 in (v for v in ENVELOPE_TURN if v <= 0):
                for t1 in (v for v in ENVELOPE_TURN if v >= 0):
                    inside = [(f, t) for f in ENVELOPE_FORWARD for t in ENVELOPE_TURN if f0 <= f <= f1 and t0 <= t <= t1]
                    if all(p in ok for p in inside):
                        size = (f1 - f0 + 0.01) * (t1 - t0 + 0.01) + 0.001 * f1
                        if size > area:
                            best, area = ([f0, f1], [t0, t1]), size
    at = {(g["forward"], g["turn"]): g for g in grid}
    turning = {}
    for forward in ENVELOPE_FORWARD:
        by_mu = {}
        for mu in map(str, ENVELOPE_FRICTION):
            rates = [at[(forward, t)]["yaw_rate_by_friction"][mu] for t in ENVELOPE_TURN]
            if None in rates:
                by_mu[mu] = {"yaw_rate_deg_s": rates, "monotonic": False, "deg_s_per_unit_turn": None, "r_squared": None}
                continue
            slope, offset = np.polyfit(ENVELOPE_TURN, rates, 1)
            residual = np.array(rates) - (slope * np.array(ENVELOPE_TURN) + offset)
            total = float(np.sum((np.array(rates) - np.mean(rates)) ** 2))
            by_mu[mu] = {"yaw_rate_deg_s": rates, "monotonic": bool(all(b > a for a, b in zip(rates, rates[1:]))),
                         "deg_s_per_unit_turn": round(float(slope), 2), "deg_s_at_zero_turn": round(float(offset), 2),
                         "r_squared": round(1.0 - float(np.sum(residual ** 2)) / total, 3) if total > 0 else None}
        turning[str(forward)] = by_mu
    full = turning["1.0"]
    proportional = all(v["monotonic"] and (v["r_squared"] or 0.0) >= 0.9 and (v["deg_s_per_unit_turn"] or 0.0) > 0 for v in full.values())
    right_way = all(v["yaw_rate_deg_s"][-1] is not None and v["yaw_rate_deg_s"][0] is not None
                    and v["yaw_rate_deg_s"][-1] > 0.5 and v["yaw_rate_deg_s"][0] < -0.5 for v in full.values())
    # walking straight only: the run of tested forward values around zero that pass with turn at zero
    straight = [0.0, 0.0]
    for f in sorted(v for v in ENVELOPE_FORWARD if v > 0):
        if (f, 0.0) not in ok:
            break
        straight[1] = f
    for f in sorted((v for v in ENVELOPE_FORWARD if v < 0), reverse=True):
        if (f, 0.0) not in ok:
            break
        straight[0] = f
    if not right_way:
        best = (straight, [0.0, 0.0])
    return {"tested_forward": list(ENVELOPE_FORWARD), "tested_turn": list(ENVELOPE_TURN), "tested_floor_friction": list(ENVELOPE_FRICTION),
            "seconds_each": ENVELOPE_SECONDS, "forward_range": best[0], "turn_range": best[1],
            "forward_range_with_turn_at_zero": straight,
            "points_ok": len(ok), "points": len(grid),
            "speed_mm_s_at_forward": {str(f): at[(f, 0.0)]["speed_mm_s"] for f in ENVELOPE_FORWARD},
            "turning": turning,
            "turn_is_proportional_at_full_forward": bool(proportional),
            "full_turn_goes_the_right_way_at_every_friction": bool(right_way),
            "straight_line_yaw_rate_deg_s": at[(1.0, 0.0)]["yaw_rate_deg_s"],
            "turn_on_the_spot_yaw_rate_deg_s": [at[(0.0, -1.0)]["yaw_rate_deg_s"], at[(0.0, 1.0)]["yaw_rate_deg_s"]],
            "grid": grid}


# --- jump --------------------------------------------------------------------

def jump_run(preset: str, params: dict, max_speed: float, physics: dict | None = None, mu: float | None = None,
             head: dict | None = None) -> dict:
    cal = replace(variant.calibration(preset), max_speed_deg_s=float(max_speed))
    sim = make_sim(preset, physics=physics, cal=cal, head=head)
    if mu is not None:
        sim.set_floor_friction(mu)
    trajectory, t_push = motiongen.jump(cal.stand_deg, params, max_speed, cal=cal)
    log = motionsim.run(sim, trajectory)
    out = gaitsearch.jump_metrics(sim, log, t_push)
    out["demand"] = {j: v for j, v in motionsim.demand(sim, log, t_push - 0.05).items() if not j.endswith("roll")}
    out["contacts"] = sorted(log["contact_kinds"])
    out["verdict"] = jump_verdict(out)
    return out


def jump_verdict(m: dict) -> str:
    """A jump: nothing on the floor for 0.1 s or more and the centre of mass
    rising 10 mm or more after the soles leave it. Less, with real flight, is
    a hop. Soles that clear the floor only because the legs are pulled up
    under a body that is not rising do not make it a jump."""
    if m["flight_s"] <= 0.0 or m["feet_rise_mm"] < 0.5:
        return "no flight"
    if m["flight_s"] >= 0.10 and m["com_rise_in_flight_mm"] >= 10.0:
        return "jump"
    return "hop"


def jumping(preset: str, entry: dict, firmware: dict, progress) -> dict:
    progress(f"{preset}: jump")
    fast = firmware["jump_max_speed_deg_s"]["value"]
    slow = firmware["max_speed_deg_s"]["value"]
    p = entry["params"]
    keep = ("flight_s", "feet_rise_mm", "com_rise_in_flight_mm", "com_rise_above_stand_mm", "landed_upright", "fell_how", "verdict",
            "peak_supply_current_a", "legs_touched")
    out = {"params": p, "max_speed_deg_s": fast, "result": jump_run(preset, p, fast),
           "at_default_speed_limit": {"max_speed_deg_s": slow, **{k: v for k, v in jump_run(preset, p, slow).items() if k in keep}},
           "friction": [{"floor_friction": mu, **{k: v for k, v in jump_run(preset, p, fast, mu=mu).items() if k in keep}}
                        for mu in ROBUST_FRICTION],
           "head": [{"case": label, **{k: v for k, v in jump_run(preset, p, fast, head=head).items() if k in keep}} for label, head in HEAD_CASES],
           "half_timestep": {k: v for k, v in jump_run(preset, p, fast, physics={"timestep_s": 0.001}).items() if k in keep},
           "not_the_result": {"what": "the same motion with the supply current limit removed; shown only to say what limits the hop",
                              **{k: v for k, v in jump_run(preset, p, fast, physics={"supply_current_a": 1000.0}).items() if k in keep}}}
    hip = np.radians(out["result"]["demand"]["left_hip_pitch"]["speed_limit_deg_s"])
    v = hip * 0.0824
    out["no_load_bound"] = {"hip_lift_speed_m_s": round(float(v), 3), "ballistic_rise_mm": round(float(v * v / (2 * 9.80665)) * 1000.0, 1),
                            "note": "thigh length times the no-load speed of the hip servo; a servo delivers no torque at that speed, so the real figure is lower"}
    return out


# --- sit, stand up, stop and power off ---------------------------------------

def squat_pose(cal) -> list:
    """Thighs swung back to the hip pitch limit, soles level."""
    hip = min(cal.joints[1].max_deg, cal.joints[4].max_deg, 90.0)
    return motiongen.symmetric(0.0, hip, -hip)


def sit_pose(cal) -> list:
    """The sit is the squat: as low as the hip pitch limit lets the robot go
    under power with its soles level."""
    return squat_pose(cal)


def sit_trajectories(cal) -> tuple:
    stand, sit = list(cal.stand_deg), sit_pose(cal)
    travel = max(abs(a - b) for a, b in zip(sit, stand)) / SIT_SPEED_DEG_S
    down = motiongen.keyframes([(0.0, stand), (0.4, stand), (0.4 + travel, sit), (1.4 + travel, sit)], SIT_SPEED_DEG_S, cal)
    up = motiongen.keyframes([(0.0, sit), (1.0, sit), (1.0 + travel, stand), (2.5 + travel, stand)], SIT_SPEED_DEG_S, cal)
    return down, up


def _rest(sim: motionsim.MotionSim, ticks: int, start: float | None = None) -> dict:
    """Let the robot settle and say what it rests on."""
    floor = set()
    start = float(sim.data.xpos[sim.torso][2]) if start is None else start
    for _ in range(ticks):
        sim.tick()
    for _ in range(25):
        sim.tick()
        floor |= set(sim.contacts()["by_kind"])
    joints = sim.joint_deg()
    speed = float(np.abs(sim.joint_speed_deg_s()).max())
    return {"fell": sim.fell_at is not None, "fell_how": sim.fell_how, "tilt_deg": round(sim.tilt_deg(), 2),
            "pitch_deg": round(sim.pitch_deg(), 1),
            "joints_deg": {"hip_roll": round(float(joints[0]), 1), "hip_pitch": round(float(joints[1]), 1), "knee": round(float(joints[2]), 1)},
            "torso_drop_mm": round((start - float(sim.data.xpos[sim.torso][2])) * 1000.0, 1),
            "still_moving_deg_s": round(speed, 1),
            "on_the_floor": sorted(floor), "mesh_interference_mm3": interference(np.round(joints, 1), sim.preset),
            "at_travel_stop": [JOINTS[i] for i in range(6) if abs(abs(joints[i]) - 90.0) < 1.0]}


def _rest_holds(rest: dict) -> bool:
    return bool(not rest["fell"] and rest["still_moving_deg_s"] < 2.0 and set(rest["on_the_floor"]) <= {"sole"})


def sit_run(preset: str, mu: float | None = None, head: dict | None = None, relaxed_friction: float | None = None,
            shove_m_s: float = 0.0, detail: bool = False) -> dict:
    sim = make_sim(preset, head=head)
    if mu is not None:
        sim.set_floor_friction(mu)
    cal = sim.cal
    down, up = sit_trajectories(cal)
    # under power all the way: down and straight back up
    sim.reset()
    motionsim.run(sim, down)
    powered = motionsim.run(sim, [(t + sim.now_ms, q) for t, q in up])
    powered_up = sim.fell_at is None and float(np.abs(powered["joint"][-1] - np.array(cal.stand_deg)).max()) < 3.0
    sim.reset()
    lowering = motionsim.run(sim, down)
    sat = {"tilt": float(lowering["tilt"][-1]), "height": float(lowering["pos"][-1][2]), "pitch": sim.pitch_deg()}
    # servos off: this is the candidate power-off pose
    if relaxed_friction is not None:
        sim.model.dof_frictionloss[:] = relaxed_friction
    sim.send("R", delayed=False)
    if shove_m_s:
        sim.data.qvel[0] += shove_m_s
    rest = _rest(sim, 475)
    sim.model.dof_frictionloss[:] = sim.frictionloss
    sim.send("E", delayed=False)
    start_ms = sim.now_ms
    rising = motionsim.run(sim, [(t + start_ms, q) for t, q in up])
    stood = sim.fell_at is None and float(np.abs(rising["joint"][-1] - np.array(cal.stand_deg)).max()) < 3.0 and float(rising["tilt"][-1]) < 3.0
    kinds = set(lowering["contact_kinds"]) | set(rest["on_the_floor"]) | set(rising["contact_kinds"])
    return {"sat_down": lowering["fell_at"] is None,
            "body_pitch_sitting_deg": round(sat["pitch"], 1),
            "stood_up_without_power_off": bool(powered_up),
            "sit_pose_deg": dict(zip(JOINTS, sit_pose(cal))),
            "torso_lowered_mm": round((float(lowering["pos"][0][2]) - sat["height"]) * 1000.0, 1),
            "torso_height_sitting_mm": round(sat["height"] * 1000.0, 1),
            "lowering_demand": _demand_summary(motionsim.demand(sim, lowering)),
            "relaxed_rest": rest, "relaxed_rest_holds": _rest_holds(rest),
            "torso_height_at_rest_mm": round(float(lowering["pos"][-1][2]) * 1000.0 - rest["torso_drop_mm"], 1),
            "stood_up": bool(stood),
            "rising_demand": _demand_summary(motionsim.demand(sim, rising)),
            "rising_demand_by_joint": {j: v for j, v in motionsim.demand(sim, rising).items() if not j.endswith("roll")},
            "legs_touched_while_moving": bool(lowering["part_on_part"]) or bool(rising["part_on_part"]),
            "mesh_interference_on_the_way": path_interference([lowering, rising], preset) if detail else None,
            "parts_that_touched_the_floor": sorted(kinds),
            "board_or_head_touched": bool(kinds & {"controller board", "shield", "head and camera mount", "display", "camera", "battery"})}


def power_off_from_stand(preset: str, relaxed_friction: float | None = None, head: dict | None = None) -> dict:
    """Stop the pulses at the stand pose and watch for 6 s."""
    sim = motionsim.MotionSim(preset, head=head)
    sim.reset()
    for _ in range(25):
        sim.tick()
    if relaxed_friction is not None:
        sim.model.dof_frictionloss[:] = relaxed_friction
    sim.send("R", delayed=False)
    speed, start = 0.0, float(sim.data.xpos[sim.torso][2])
    for _ in range(60):
        sim.tick()
        speed = max(speed, float(-sim.data.qvel[2]))
    rest = _rest(sim, 215, start)
    return {**rest, "holds": _rest_holds(rest), "peak_sink_speed_m_s": round(speed, 3)}


def power_cycle(preset: str, pose: list) -> dict:
    """Go to a pose, stop the pulses, wait, enable again and ask for the
    stand pose. The firmware has no position feedback: on enable it drives
    the servos to the last commanded pose, wherever the legs have sunk to."""
    sim = make_sim(preset)
    cal = sim.cal
    stand = list(cal.stand_deg)
    sim.reset()
    travel = max(abs(a - b) for a, b in zip(pose, stand)) / SIT_SPEED_DEG_S
    motionsim.run(sim, motiongen.keyframes([(0.0, stand), (0.3, stand), (0.3 + travel, pose), (0.8 + travel, pose)], SIT_SPEED_DEG_S, cal))
    start = float(sim.data.xpos[sim.torso][2])
    sim.send("R", delayed=False)
    rest = _rest(sim, 225, start)
    sim.send("E", delayed=False)
    back = motiongen.keyframes([(0.0, pose), (1.0, pose), (1.0 + travel, stand), (3.0 + travel, stand)], SIT_SPEED_DEG_S, cal)
    rising = motionsim.run(sim, [(t + sim.now_ms, q) for t, q in back])
    joints = rising["joint"][-1]
    stood = sim.fell_at is None and float(np.abs(joints - np.array(stand)).max()) < 3.0 and float(rising["tilt"][-1]) < 3.0
    return {"pose_deg": {"hip_pitch": pose[1], "knee": pose[2]}, "rest": rest, "rest_holds": _rest_holds(rest), "stood_up_after_enable": bool(stood),
            "ends_at_deg": {"hip_pitch": round(float(joints[1]), 1), "knee": round(float(joints[2]), 1)},
            "fell": sim.fell_at is not None, "fell_how": sim.fell_how,
            "mesh_interference_on_the_way_up": path_interference([rising], preset),
            "peak_torque_fraction": _demand_summary(motionsim.demand(sim, rising))["peak_torque_fraction"]}


def stopping(preset: str, entry: dict, progress) -> dict:
    """What happens when commands stop in mid gait (the watchdog holds) and
    when the pulses stop in mid gait (power off), at four points of a step."""
    progress(f"{preset}: stop and power off in mid gait")
    period = entry["params"]["period_s"]
    out = {"watchdog_hold": [], "power_off": []}
    for k in range(4):
        at_ms = int(round((4.0 + k * period / 4.0) * 50)) * 20
        sim = make_sim(preset)
        trajectory, _ = walk_trajectory(sim.cal, entry, 8.0)
        cut = [(t, q) for t, q in trajectory if t <= at_ms]
        sim.reset()
        motionsim.run(sim, cut)
        rest = _rest(sim, 175)
        out["watchdog_hold"].append({"commands_stopped_at_s": at_ms / 1000.0, "mode_after": sim.controller.mode,
                                     "fell": rest["fell"], "fell_how": rest["fell_how"], "tilt_deg": rest["tilt_deg"],
                                     "on_the_floor": rest["on_the_floor"]})
        sim.reset()
        motionsim.run(sim, cut)
        sim.send("R", delayed=False)
        rest = _rest(sim, 275)
        out["power_off"].append({"pulses_stopped_at_s": at_ms / 1000.0, **rest, "holds": _rest_holds(rest)})
    out["watchdog_hold_stays_up"] = all(not r["fell"] for r in out["watchdog_hold"])
    out["power_off_stays_up"] = all(not r["fell"] for r in out["power_off"])
    out["power_off_legs_meet"] = sum(1 for r in out["power_off"] if any("shin" in pair and pair.count("shin") == 2 for pair in r["mesh_interference_mm3"]))
    return out


def sitting(preset: str, progress) -> dict:
    progress(f"{preset}: sit and stand up")
    keep = ("sat_down", "relaxed_rest_holds", "stood_up", "parts_that_touched_the_floor")
    out = sit_run(preset, detail=True)
    free = sit_run(preset, relaxed_friction=0.0)
    out["relaxed_with_no_joint_friction"] = {"relaxed_rest_holds": free["relaxed_rest_holds"], "relaxed_rest": free["relaxed_rest"]}
    out["relaxed_and_shoved"] = [{"shove_m_s": v, **{k: w for k, w in sit_run(preset, shove_m_s=v).items() if k in keep}} for v in (0.1, -0.1)]
    out["friction"] = [{"floor_friction": mu, **{k: v for k, v in sit_run(preset, mu=mu).items() if k in keep}} for mu in ROBUST_FRICTION]
    out["head"] = [{"case": label, **{k: v for k, v in sit_run(preset, head=head).items() if k in keep}} for label, head in HEAD_CASES]
    cal = variant.calibration(preset)
    out["power_cycle_at_the_stand_pose"] = power_cycle(preset, list(cal.stand_deg))
    out["power_off_at_the_stand_pose"] = power_off_from_stand(preset)
    out["power_off_at_the_stand_pose_no_joint_friction"] = power_off_from_stand(preset, 0.0)
    out["power_off_at_the_stand_pose_heaviest_head"] = power_off_from_stand(preset, head=HEAD_CASES[2][1])
    return out


def one_foot_test(preset) -> dict:
    """From the stand pose lift one foot slowly with its sole level (hip
    +10, knee -10 degrees, 0.7 s), hold 2.5 s, set it down. Each side in turn."""
    sim = make_sim(preset)
    stand = list(sim.cal.stand_deg)
    out = {}
    for side, i in (("left", 1), ("right", 4)):
        lifted = list(stand)
        lifted[i] += 10.0
        lifted[i + 1] -= 10.0
        sim.reset()
        trajectory = motiongen.keyframes([(0.0, stand), (0.3, stand), (1.0, lifted), (3.5, lifted), (4.2, stand), (5.0, stand)],
                                         sim.cal.max_speed_deg_s, sim.cal)
        log = motionsim.run(sim, trajectory)
        hold = (log["t"] > 1.6) & (log["t"] < 3.4)
        clear = log[f"clear_{side}"][hold] * 1000.0
        other = log["force_right" if side == "left" else "force_left"][hold]
        out[side] = {"fell": log["fell_at"] is not None, "fell_how": log["fell_how"],
                     "lifted_foot_clear_of_floor_fraction": round(float((clear > 0.5).mean()), 2),
                     "lifted_foot_clearance_mm": round(float(np.median(clear)), 1),
                     "load_on_other_foot_fraction": round(float(np.median(other)) / (sim.mass * 9.80665), 2),
                     "max_tilt_deg": round(float(log["tilt"].max()), 1),
                     "legs_touched": bool(log["part_on_part"]),
                     "commands_refused": gaitsearch.refused_fraction(sim.cal, trajectory) > 0.0}
    out["stands_on_one_foot"] = all((not v["fell"]) and v["lifted_foot_clear_of_floor_fraction"] > 0.9 for v in (out["left"], out["right"]))
    return out


def stand_run(preset: str) -> dict:
    sim = make_sim(preset)
    log = motionsim.run(sim, gaitfile.stand(sim.cal.stand_deg, 10.0))
    return {"fell": log["fell_at"] is not None, "max_tilt_deg": round(float(log["tilt"].max()), 2),
            "mass_kg": round(sim.mass, 4), "torso_height_mm": round(sim.start_height * 1000.0, 1),
            **_demand_summary(motionsim.demand(sim, log)), "parts_touching_each_other": sorted(log["part_on_part"])}


# --- checks of a trajectory file ---------------------------------------------

class LegGap:
    """Distance between the collision boxes of one leg and those of the
    other, pose by pose, without dynamics."""

    def __init__(self, preset=DEFAULT, reach_m: float = 0.03):
        xml, _ = variant.build(preset)
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.reach = reach_m
        m = self.model
        self.qadr = [m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in JOINTS]
        legs = {}
        for g in range(m.ngeom):
            body = m.body(m.geom_bodyid[g]).name
            if m.geom_contype[g] and body.split("_")[-1] in ("thigh", "shin"):
                legs.setdefault(body.split("_")[0], []).append(g)
        self.left, self.right = legs["left"], legs["right"]
        self.radius = m.geom_rbound

    def min_mm(self, q_deg) -> float:
        m, d = self.model, self.data
        d.qpos[:] = 0.0
        d.qpos[2], d.qpos[3] = 1.0, 1.0
        for a, v in zip(self.qadr, q_deg):
            d.qpos[a] = np.radians(v)
        mujoco.mj_kinematics(m, d)
        best = self.reach
        for a in self.left:
            pa, ra = d.geom_xpos[a], self.radius[a]
            for b in self.right:
                if np.linalg.norm(pa - d.geom_xpos[b]) > ra + self.radius[b] + best:
                    continue
                best = min(best, mujoco.mj_geomDistance(m, d, a, b, best, None))
        return float(best) * 1000.0


_CHECKERS: dict = {}


def check_trajectory(trajectory: list, cal, max_speed: float, meshes: bool = True) -> dict:
    """Everything a trajectory has to pass before it is shipped, over its
    whole length: the soft limits and the speed limit (gait.check_limits),
    protocol.Controller taking every row as written (no clamp, no refusal by
    the leg clearance rule, no rate limiting), the gap between the collision
    boxes of the two legs, and the exact meshes of the two legs."""
    limited = replace(cal, max_speed_deg_s=float(max_speed))
    problems = gaitfile.check_limits(trajectory, limited)
    controller = protocol.Controller(limited)
    controller.current = list(trajectory[0][1])
    controller.target = list(trajectory[0][1])
    controller.handle("E", 0)
    clamps, refused, lag = 0, 0, 0.0
    for t, q in trajectory:
        reply = controller.handle(protocol.format_joints(q), t)
        clamps += reply.startswith("OK CLAMP")
        refused += reply == "ERR CLEAR"
        controller.tick(t + protocol.TICK_MS)
        lag = max(lag, max(abs(a - b) for a, b in zip(controller.current, q)))
    if "gap" not in _CHECKERS:
        _CHECKERS["gap"] = LegGap()
    gap = min(_CHECKERS["gap"].min_mm(q) for _, q in trajectory)
    out = {"limit_problems": len(problems), "clamped_commands": clamps, "refused_by_the_leg_clearance_rule": refused,
           "max_lag_behind_command_deg": round(lag, 2), "least_gap_between_leg_boxes_mm": round(gap, 1)}
    if meshes:
        from . import clearance
        if "mesh" not in _CHECKERS:
            _CHECKERS["mesh"] = clearance.MeshLegs()
        seen, worst = {}, 0.0
        for _, q in trajectory:
            key = tuple(q)
            if key not in seen:
                seen[key] = _CHECKERS["mesh"].overlap_mm3(q)
            worst = max(worst, seen[key])
        out["rows_checked_against_the_leg_meshes"] = len(trajectory)
        out["worst_leg_mesh_overlap_mm3"] = round(worst, 2)
    return out


def trajectory_passes(check: dict) -> bool:
    return (check["limit_problems"] == 0 and check["clamped_commands"] == 0 and check["refused_by_the_leg_clearance_rule"] == 0
            and check["max_lag_behind_command_deg"] <= 0.06 and check["least_gap_between_leg_boxes_mm"] > 0.0
            and check.get("worst_leg_mesh_overlap_mm3", 0.0) <= 0.5)


# --- files for the robot and the control page --------------------------------

def write_files(report: dict, gaits: dict, firmware: dict) -> dict:
    """Trajectories for the robot as built, the manifest in the shape the
    control page reads, and the gait parameters with the tested envelope."""
    folder = ROOT / "trajectories"
    default_speed = firmware["max_speed_deg_s"]["value"]
    jump_speed = firmware["jump_max_speed_deg_s"]["value"]
    cal = variant.calibration(DEFAULT)
    g = gaits[DEFAULT]
    res = report["presets"][DEFAULT]
    env = res["walk"]["envelope"]
    steady = res["walk"]["nominal"]
    files, motions, unavailable = [], {}, {}

    def add(name, trajectory, what, max_speed=default_speed, loop=None, tested=None):
        file = f"{name}.csv" if max_speed <= default_speed else f"restricted/{name}.csv"
        gaitfile.write_csv(folder / file, trajectory)
        check = check_trajectory(trajectory, cal, max_speed)
        entry = {"name": name, "file": f"trajectories/{file}", "duration_s": round(trajectory[-1][0] / 1000.0, 2), "what": what,
                 "max_speed_deg_s": max_speed, "needs_speed_limit_raised": max_speed > default_speed,
                 "checks": check, "passes_checks": trajectory_passes(check), "tested_in_simulation": tested}
        if loop:
            entry["loop"] = loop
        files.append(entry)
        return entry

    period_ms = int(round(g["walk"]["params"]["period_s"] * 1000))
    lead_ms = int(round(g["walk"]["params"].get("lead_in_s", gaitsearch.LEAD_IN_S) * 1000))
    loop = {"from_ms": lead_ms + period_ms, "period_ms": period_ms,
            "how": "after from_ms the file repeats every period_ms; a player may loop that stretch"}
    add("walk", walk_trajectory(cal, g["walk"], 12.0)[0], f"walk forward, {steady.get('speed_mm_s')} mm/s in simulation", loop=loop,
        tested={"stayed_up": not steady["fell"], "speed_mm_s": steady.get("speed_mm_s"), "peak_torque_fraction": steady.get("peak_torque_fraction")})
    for label, turn in (("turn_left", 1.0), ("turn_right", -1.0)):
        point = next(p for p in env["grid"] if p["forward"] == 1.0 and p["turn"] == turn)
        add(label, walk_trajectory(cal, g["walk"], 12.0, 1.0, turn)[0],
            f"walk with the turn input at {turn:+.0f}: {point['yaw_rate_deg_s']} deg/s in simulation", loop=loop,
            tested={"ok_at_every_friction": point["ok_at_every_friction"], "yaw_rate_deg_s": point["yaw_rate_deg_s"]})
    down, up = sit_trajectories(cal)
    sit = res["sit"]
    sit_entry = add("sit", down, "lower from the stand pose to the squat at the hip pitch limit", tested={"sat_down": sit["sat_down"]})
    add("stand_up", up, "rise from the squat to the stand pose", tested={"stood_up": sit["stood_up"]})
    jump = res["jump"]["result"]
    add("jump", motiongen.jump(cal.stand_deg, g["jump"]["params"], jump_speed, cal=replace(cal, max_speed_deg_s=jump_speed))[0],
        f"crouch and push off: a {jump['verdict']} in simulation, soles {jump['feet_rise_mm']} mm off the floor for {jump['flight_s']} s, "
        f"centre of mass rising {jump['com_rise_in_flight_mm']} mm in flight", max_speed=jump_speed,
        tested={"landed_upright": jump["landed_upright"], "verdict": jump["verdict"]})

    motions["stand"] = {"file": "trajectories/stand.csv", "label": "Stand"}
    if sit["sat_down"] and sit_entry["passes_checks"]:
        motions["sit"] = {"file": "trajectories/sit.csv", "label": "Sit"}
    else:
        unavailable["sit"] = "the sit trajectory did not pass its checks"
    unavailable["jump"] = ("locked: the jump runs four servos at stall torque from a supply that cannot feed them and can strip gears or break parts; "
                           "it needs the firmware speed limit raised, and in simulation it is a hop of a few millimetres. "
                           "The file is trajectories/restricted/jump.csv")
    if env["forward_range"][0] == 0.0:
        unavailable["back"] = "walking backward did not stay inside the tested envelope"
    if env["turn_range"] == [0.0, 0.0]:
        unavailable["turn"] = ("the step difference does not steer reliably in simulation: the yaw rate does not follow the turn input at every floor friction, "
                               "and there is no hip yaw joint")
    manifest = {"version": 1,
                "gait": {"params": "config/gait.json", "forward": env["forward_range"], "turn": env["turn_range"]},
                "motions": motions, "unavailable": unavailable,
                "study": {"generated_by": "scripts/run_motion.py", "robot": "comb soles, default head",
                          "format": "CSV, header t_ms and the six joint names, joint angles in degrees at 50 Hz (microduck/gait.py)",
                          "gait_parameters_and_envelope": "trajectories/gait_params.json",
                          "files": files}}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    doc = {"generated_by": "scripts/run_motion.py",
           "gait": "microduck/gait.py with the control page's inputs: left step scaled by forward minus turn, right by forward plus turn, each clipped to -1..1",
           "params_file": "config/gait.json", "params": g["walk"]["params"],
           "stand_pose_deg": dict(zip(JOINTS, cal.stand_deg)), "max_speed_deg_s": default_speed,
           "forward": env["forward_range"], "turn": env["turn_range"],
           "note": "Inside forward and turn every tested point stayed up at floor friction 0.4, 0.6 and 0.9 with the legs apart and no command refused. "
                   "Outside it a point fell, touched, was refused, or was not tested.",
           "tested": {k: env[k] for k in ("tested_forward", "tested_turn", "tested_floor_friction", "seconds_each", "points_ok", "points",
                                          "speed_mm_s_at_forward", "turn_is_proportional_at_full_forward",
                                          "full_turn_goes_the_right_way_at_every_friction", "straight_line_yaw_rate_deg_s",
                                          "turn_on_the_spot_yaw_rate_deg_s")},
           "turning": env["turning"],
           "points": [{k: p[k] for k in ("forward", "turn", "ok_at_every_friction", "speed_mm_s", "yaw_rate_deg_s", "peak_torque_fraction")}
                      for p in env["grid"]]}
    (folder / "gait_params.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return manifest


def run(progress=print, record: bool = True) -> dict:
    gaits = load_gaits()
    config = variant.load_json("motion.json")
    out = {"generated_by": "scripts/run_motion.py",
           "physics": config["physics"], "head": config["head"], "firmware": config["firmware"],
           "robot_presets": {name: p["description"] for name, p in variant.load_presets().items()},
           "search": gaits["search"], "presets": {}}
    clearance_report = ROOT / "reports" / "clearance.json"
    if clearance_report.is_file():
        with open(clearance_report, encoding="utf-8") as handle:
            out["leg_clearance_rule"] = json.load(handle)
    for preset in PRESETS:
        g = gaits[preset]
        progress(f"{preset}: stand")
        out["presets"][preset] = {"stand": stand_run(preset), "one_foot_test": one_foot_test(preset),
                                  "walk": walking(preset, g["walk"], progress),
                                  "stop": stopping(preset, g["walk"], progress),
                                  "jump": jumping(preset, g["jump"], config["firmware"], progress),
                                  "sit": sitting(preset, progress)}
    progress("trajectories")
    write_files(out, gaits, config["firmware"])
    out["manifest"] = "trajectories/manifest.json"
    out["recordings"] = {}
    if record:
        progress("recording")
        try:
            from . import motion_record
            out["recordings"] = motion_record.record_all(gaits, config["firmware"])
            out["offscreen_rendering"] = "worked"
        except Exception as error:  # no GL context on this machine
            out["offscreen_rendering"] = f"failed: {type(error).__name__}: {error}"
    (ROOT / "reports" / "motion.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    from . import motion_report
    (ROOT / "docs" / "motion.md").write_text(motion_report.markdown(out), encoding="utf-8", newline="\n")
    return out
