# SPDX-License-Identifier: MIT
"""The motion study: walk, turn, jump, sit and stand up, on the drawn
geometry and on the design variant, with the servo and command-path model of
microduck/motionsim.py.

Reads the searched motions from config/gaits.json (scripts/optimise_motion.py
writes it) and writes reports/motion.json, docs/motion.md, the trajectories
with trajectories/manifest.json and trajectories/gait_params.json, and the
recordings in docs/images/motion-*.gif.
"""
from __future__ import annotations

import json
from dataclasses import replace

import numpy as np

from . import gait as gaitfile
from . import gaitsearch, motions, motionsim, protocol, variant
from .protocol import JOINTS, ROOT

PRESETS = ("drawn", "comb_feet")
WALK_SECONDS = 30.0
LONG_SECONDS = 120.0
ROBUST_FRICTION = (0.3, 0.45, 0.6, 0.8, 1.0)
ROBUST_MASS = (0.9, 1.0, 1.1)
ROBUST_START = (((1.5, 1.5), (0.02, 0.02)), ((-1.5, -1.0), (-0.02, 0.03)))
ENVELOPE_SPEED = (0.25, 0.5, 0.75, 1.0)
ENVELOPE_TURN = (-1.0, -0.5, 0.0, 0.5, 1.0)
ENVELOPE_FRICTION = (0.4, 0.6, 0.9)
ENVELOPE_SECONDS = 20.0
SIT_POSE = motions.symmetric(0.0, 90.0, -90.0)
SIT_SPEED_DEG_S = 40.0
HEAD_CASES = (("as drawn", {}), ("20 g more in the head", {"extra_mass_g": 20.0}), ("40 g more in the head", {"extra_mass_g": 40.0}),
              ("20 g, 40 mm further forward", {"extra_mass_g": 20.0, "position_mm": [15.0, 0.0, 78.0]}),
              ("20 g, 40 mm further back", {"extra_mass_g": 20.0, "position_mm": [-65.0, 0.0, 78.0]}))


def load_gaits() -> dict:
    with open(ROOT / "config" / "gaits.json", encoding="utf-8") as handle:
        return json.load(handle)


def walk_trajectory(cal, entry: dict, seconds: float, speed: float = 1.0, turn: float = 0.0) -> tuple:
    """Trajectory of a preset's gait and the time steady walking starts."""
    p = entry["params"]
    if entry["kind"] == "crawl":
        lead = gaitsearch.CRAWL_LEAD_IN_S
        trajectory = motions.crawl(p, seconds, speed, turn, lead, cal.max_speed_deg_s, cal, cal.stand_deg)
    else:
        lead = gaitsearch.LEAD_IN_S
        trajectory = motions.walk(cal.stand_deg, p, seconds, speed, turn, lead, cal.max_speed_deg_s, cal)
    return trajectory, lead + p["period_s"]


def _demand_summary(demand: dict) -> dict:
    return {"peak_torque_fraction": max(v["peak_torque_fraction"] for v in demand.values()),
            "peak_speed_fraction": max(v["peak_speed_fraction"] for v in demand.values()),
            "time_at_torque_limit_fraction": max(v["time_at_torque_limit_fraction"] for v in demand.values())}


def walk_run(sim: motionsim.MotionSim, entry: dict, seconds: float, speed: float = 1.0, turn: float = 0.0,
             tilt=(0.0, 0.0), push=(0.0, 0.0), detail: bool = False) -> dict:
    sim.reset(tilt_deg=tilt, push_m_s=push)
    trajectory, t0 = walk_trajectory(sim.cal, entry, seconds, speed, turn)
    log = motionsim.run(sim, trajectory)
    t = log["t"]
    end = log["fell_at"] if log["fell_at"] is not None else t[-1]
    window = (t >= t0) & (t <= end)
    out = {"fell": log["fell_at"] is not None, "fell_at_s": log["fell_at"], "fell_how": log["fell_how"], "seconds": seconds}
    if window.sum() < 10:
        out.update({"speed_mm_s": 0.0, "yaw_rate_deg_s": 0.0, "steps": 0, "single_support_fraction": 0.0})
        return out
    pos = log["pos"][window]
    walked = float(t[window][-1] - t[window][0])
    yaw = np.degrees(np.unwrap(np.radians(log["yaw"][window])))
    path = float(np.sum(np.linalg.norm(np.diff(pos[::10, :2], axis=0), axis=1)))
    st = motionsim.stepping(log, t0)
    swings = st.pop("swings")
    demand = motionsim.demand(sim, log, t0)
    expected = 2.0 * walked / entry["params"]["period_s"]
    out.update({"forward_mm": round(float(pos[-1][0] - pos[0][0]) * 1000.0, 1),
                "sideways_mm": round(float(pos[-1][1] - pos[0][1]) * 1000.0, 1),
                "speed_mm_s": round(float(pos[-1][0] - pos[0][0]) * 1000.0 / walked, 1),
                "path_speed_mm_s": round(path * 1000.0 / walked, 1),
                "yaw_deg": round(float(yaw[-1] - yaw[0]), 1), "yaw_rate_deg_s": round(float(yaw[-1] - yaw[0]) / walked, 2),
                "max_tilt_deg": round(float(log["tilt"][window].max()), 1),
                "expected_steps": round(expected, 1), "step_fraction": round(min(1.0, st["steps"] / max(expected, 1.0)), 3),
                **st, **_demand_summary(demand),
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


def walking(preset: str, entry: dict, progress) -> dict:
    out = {"gait": entry}
    sim = motionsim.MotionSim(preset)
    progress(f"{preset}: walk {WALK_SECONDS:.0f} s")
    out["nominal"] = walk_run(sim, entry, WALK_SECONDS, detail=True)
    out["truly_steps"] = truly_steps(out["nominal"])
    progress(f"{preset}: walk {LONG_SECONDS:.0f} s")
    long = walk_run(sim, entry, LONG_SECONDS)
    out["long_horizon"] = {k: long.get(k) for k in ("fell", "fell_at_s", "fell_how", "seconds", "speed_mm_s", "yaw_deg", "steps", "step_fraction")}
    progress(f"{preset}: half time step")
    fine = walk_run(motionsim.MotionSim(preset, physics={"timestep_s": 0.001}), entry, WALK_SECONDS)
    out["half_timestep"] = {k: fine.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "steps", "step_fraction", "median_clearance_mm")}

    progress(f"{preset}: robustness")
    rows = []
    for mass in ROBUST_MASS:
        s = motionsim.MotionSim(preset, mass_scale=mass)
        for mu in ROBUST_FRICTION:
            s.set_floor_friction(mu)
            for tilt, push in ROBUST_START:
                r = walk_run(s, entry, WALK_SECONDS, tilt=tilt, push=push)
                rows.append({"floor_friction": mu, "mass_scale": mass, "start_tilt_deg": list(tilt), "start_push_m_s": list(push),
                             **{k: r.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "step_fraction", "alternating",
                                                      "median_clearance_mm", "single_support_fraction")}})
    up = [r for r in rows if not r["fell"]]
    by_mu = []
    for mu in ROBUST_FRICTION:
        sub = [r for r in rows if r["floor_friction"] == mu]
        ok = [r for r in sub if not r["fell"]]
        by_mu.append({"floor_friction": mu, "runs": len(sub), "fell": len(sub) - len(ok),
                      "speed_mm_s": [min(r["speed_mm_s"] for r in ok), max(r["speed_mm_s"] for r in ok)] if ok else None,
                      "yaw_deg": [min(r["yaw_deg"] for r in ok), max(r["yaw_deg"] for r in ok)] if ok else None,
                      "stepping_runs": sum(1 for r in ok if r["step_fraction"] >= 0.8 and r["alternating"])})
    out["robustness"] = {"runs": len(rows), "seconds_each": WALK_SECONDS, "fell": len(rows) - len(up),
                         "stepping_runs": sum(1 for r in up if r["step_fraction"] >= 0.8 and r["alternating"]),
                         "speed_mm_s": [min(r["speed_mm_s"] for r in up), max(r["speed_mm_s"] for r in up)] if up else None,
                         "yaw_deg": [min(r["yaw_deg"] for r in up), max(r["yaw_deg"] for r in up)] if up else None,
                         "by_friction": by_mu, "rows": rows}

    progress(f"{preset}: head mass")
    out["head_sensitivity"] = []
    for label, head in HEAD_CASES:
        r = walk_run(motionsim.MotionSim(preset, head=head), entry, WALK_SECONDS)
        out["head_sensitivity"].append({"case": label, "head": head, **{k: r.get(k) for k in ("fell", "fell_at_s", "speed_mm_s", "yaw_deg", "step_fraction",
                                                                                               "median_clearance_mm")}})

    progress(f"{preset}: speed and turn envelope")
    grid = []
    sims = {mu: motionsim.MotionSim(preset) for mu in ENVELOPE_FRICTION}
    for mu, s in sims.items():
        s.set_floor_friction(mu)
    for speed in ENVELOPE_SPEED:
        for turn in ENVELOPE_TURN:
            runs = {mu: walk_run(s, entry, ENVELOPE_SECONDS, speed, turn) for mu, s in sims.items()}
            nominal = runs[0.6]
            grid.append({"speed": speed, "turn": turn, "stayed_up_all_frictions": all(not r["fell"] for r in runs.values()),
                         "fell_at_friction": [mu for mu, r in runs.items() if r["fell"]],
                         "forward_mm_s": nominal.get("speed_mm_s"), "path_mm_s": nominal.get("path_speed_mm_s"),
                         "yaw_rate_deg_s": nominal.get("yaw_rate_deg_s"),
                         "yaw_rate_by_friction": {str(mu): r.get("yaw_rate_deg_s") for mu, r in runs.items()},
                         "step_fraction": nominal.get("step_fraction")})
    out["envelope"] = envelope(grid)
    return out


def envelope(grid: list) -> dict:
    """The largest speed and turn ranges, taken from full speed and zero turn
    outward, inside which every tested point stayed up at every friction."""
    ok = {(g["speed"], g["turn"]) for g in grid if g["stayed_up_all_frictions"]}
    speeds = [s for s in ENVELOPE_SPEED if all((s, t) in ok for t in ENVELOPE_TURN)]
    turns = [t for t in ENVELOPE_TURN if all((s, t) in ok for s in ENVELOPE_SPEED)]
    straight = {g["speed"]: g for g in grid if g["turn"] == 0.0}
    full = {g["turn"]: g for g in grid if g["speed"] == 1.0}
    base = full[0.0]["yaw_rate_deg_s"] or 0.0
    left, right = full[1.0]["yaw_rate_deg_s"], full[-1.0]["yaw_rate_deg_s"]
    monotonic = None not in (left, right) and all(
        (full[a]["yaw_rate_deg_s"] or 0.0) < (full[b]["yaw_rate_deg_s"] or 0.0) for a, b in zip(ENVELOPE_TURN, ENVELOPE_TURN[1:]))
    by_mu = {mu: [full[t]["yaw_rate_by_friction"][mu] for t in ENVELOPE_TURN] for mu in full[0.0]["yaw_rate_by_friction"]}
    same_sign = all(v[0] is not None and v[-1] is not None and v[-1] - v[len(v) // 2] > 0.5 and v[len(v) // 2] - v[0] > 0.5 for v in by_mu.values())
    return {"tested_speed": list(ENVELOPE_SPEED), "tested_turn": list(ENVELOPE_TURN), "tested_floor_friction": list(ENVELOPE_FRICTION),
            "seconds_each": ENVELOPE_SECONDS,
            "speed_range_all_turns": [min(speeds), max(speeds)] if speeds else None,
            "turn_range_all_speeds": [min(turns), max(turns)] if turns else None,
            "points_stayed_up": len(ok), "points": len(grid),
            "forward_mm_s_at_speed": {str(s): straight[s]["forward_mm_s"] for s in ENVELOPE_SPEED},
            "yaw_rate_deg_s_at_turn": {str(t): full[t]["yaw_rate_deg_s"] for t in ENVELOPE_TURN},
            "yaw_rate_deg_s_at_turn_by_friction": {mu: dict(zip(map(str, ENVELOPE_TURN), v)) for mu, v in by_mu.items()},
            "straight_line_yaw_rate_deg_s": base,
            "turn_input_steers": bool(monotonic),
            "turn_input_steers_at_every_friction": bool(same_sign),
            "grid": grid}


# --- jump --------------------------------------------------------------------

def jump_run(preset: str, params: dict, max_speed: float, physics: dict | None = None, mu: float | None = None,
             head: dict | None = None) -> dict:
    cal = replace(variant.calibration(preset), max_speed_deg_s=float(max_speed))
    sim = motionsim.MotionSim(preset, physics=physics, cal=cal, head=head)
    if mu is not None:
        sim.set_floor_friction(mu)
    trajectory, t_push = motions.jump(cal.stand_deg, params, max_speed, cal=cal)
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
            "peak_supply_current_a")
    out = {"params": p, "max_speed_deg_s": fast, "result": jump_run(preset, p, fast),
           "at_default_speed_limit": {"max_speed_deg_s": slow, **{k: v for k, v in jump_run(preset, p, slow).items() if k in keep}},
           "friction": [{"floor_friction": mu, **{k: v for k, v in jump_run(preset, p, fast, mu=mu).items() if k in keep}}
                        for mu in ROBUST_FRICTION],
           "head": [{"case": label, **{k: v for k, v in jump_run(preset, p, fast, head=head).items() if k in keep}} for label, head in HEAD_CASES],
           "half_timestep": {k: v for k, v in jump_run(preset, p, fast, physics={"timestep_s": 0.001}).items() if k in keep},
           "not_the_result": {"what": "the same motion with the supply current limit removed; shown only to say what limits the hop",
                              **{k: v for k, v in jump_run(preset, p, fast, physics={"supply_current_a": 1000.0}).items() if k in keep}}}
    # the most a ballistic body could rise if the whole robot left the floor
    # at the speed the hips can lift it with no load at all
    hip = np.radians(out["result"]["demand"]["left_hip_pitch"]["speed_limit_deg_s"])
    v = hip * motions.THIGH_MM / 1000.0
    out["no_load_bound"] = {"hip_lift_speed_m_s": round(float(v), 3), "ballistic_rise_mm": round(float(v * v / (2 * 9.80665)) * 1000.0, 1),
                            "note": "thigh length times the no-load speed of the hip servo; a servo delivers no torque at that speed, so the real figure is lower"}
    return out


# --- sit and stand up --------------------------------------------------------

def sit_trajectories(cal) -> tuple:
    down = motions.keyframes([(0.0, list(cal.stand_deg)), (0.4, list(cal.stand_deg)),
                              (0.4 + 45.0 / SIT_SPEED_DEG_S, SIT_POSE), (2.6, SIT_POSE)], SIT_SPEED_DEG_S, cal)
    up = motions.keyframes([(0.0, SIT_POSE), (0.4, SIT_POSE), (0.4 + 45.0 / SIT_SPEED_DEG_S, list(cal.stand_deg)),
                            (3.0, list(cal.stand_deg))], SIT_SPEED_DEG_S, cal)
    return down, up


def sit_run(preset: str, mu: float | None = None, head: dict | None = None, relaxed_friction: float | None = None,
            shove_m_s: float = 0.0) -> dict:
    sim = motionsim.MotionSim(preset, head=head)
    if mu is not None:
        sim.set_floor_friction(mu)
    cal = sim.cal
    down, up = sit_trajectories(cal)
    sim.reset()
    lowering = motionsim.run(sim, down)
    sat = {"tilt": float(lowering["tilt"][-1]), "height": float(lowering["pos"][-1][2]), "joint": lowering["joint"][-1].copy()}
    # servos off: this is the candidate power-off pose
    if relaxed_friction is not None:
        sim.model.dof_frictionloss[:] = relaxed_friction
    sim.send("R", delayed=False)
    if shove_m_s:
        sim.data.qvel[0] += shove_m_s
    rest_kinds, rest_low = set(), {}
    for _ in range(250):
        sim.tick()
        rest_kinds |= set(sim.contacts()["by_kind"])
    for kind, d in sim.lowest_by_kind().items():
        rest_low[kind] = round(d * 1000.0, 1)
    drift = float(np.abs(sim.joint_deg() - sat["joint"]).max())
    rest = {"fell": sim.fell_at is not None, "tilt_deg": round(sim.tilt_deg(), 2), "max_joint_drift_deg": round(drift, 2),
            "torso_drop_mm": abs(round((sat["height"] - float(sim.data.xpos[sim.torso][2])) * 1000.0, 1)),
            "touching_floor": sorted(rest_kinds)}
    stable = (not rest["fell"]) and rest["tilt_deg"] < 3.0 and drift < 3.0 and rest_kinds <= {"sole"}
    sim.model.dof_frictionloss[:] = sim.frictionloss
    sim.send("E", delayed=False)
    start_ms = sim.now_ms
    rising = motionsim.run(sim, [(t + start_ms, q) for t, q in up])
    stood = sim.fell_at is None and float(np.abs(rising["joint"][-1] - np.array(cal.stand_deg)).max()) < 3.0 and float(rising["tilt"][-1]) < 3.0
    kinds = set(lowering["contact_kinds"]) | rest_kinds | set(rising["contact_kinds"])
    return {"sat_down": lowering["fell_at"] is None and sat["tilt"] < 3.0,
            "sit_pose_deg": dict(zip(JOINTS, SIT_POSE)),
            "torso_lowered_mm": round((float(lowering["pos"][0][2]) - sat["height"]) * 1000.0, 1),
            "torso_height_sitting_mm": round(sat["height"] * 1000.0, 1),
            "lowering_demand": _demand_summary(motionsim.demand(sim, lowering)),
            "lowering_demand_by_joint": {j: v for j, v in motionsim.demand(sim, lowering).items() if not j.endswith("roll")},
            "relaxed_rest": rest, "relaxed_rest_stable": bool(stable),
            "lowest_part_above_floor_mm": {k: v for k, v in sorted(rest_low.items()) if k != "sole"},
            "stood_up": bool(stood),
            "rising_demand": _demand_summary(motionsim.demand(sim, rising)),
            "rising_demand_by_joint": {j: v for j, v in motionsim.demand(sim, rising).items() if not j.endswith("roll")},
            "parts_that_touched_the_floor": sorted(kinds),
            "board_or_head_touched": bool(kinds & {"controller board", "shield", "head and neck"})}


def relax_from_stand(preset: str, relaxed_friction: float | None = None) -> dict:
    """Stop the pulses at the stand pose and watch for 6 s."""
    sim = motionsim.MotionSim(preset)
    sim.reset()
    for _ in range(25):
        sim.tick()
    if relaxed_friction is not None:
        sim.model.dof_frictionloss[:] = relaxed_friction
    sim.send("R", delayed=False)
    kinds, speed = set(), 0.0
    for _ in range(300):
        sim.tick()
        kinds |= set(sim.contacts()["by_kind"])
        speed = max(speed, float(-sim.data.qvel[2]))
    joints = sim.joint_deg()
    return {"fell": sim.fell_at is not None, "fell_how": sim.fell_how, "final_tilt_deg": round(sim.tilt_deg(), 2),
            "ends_at_deg": {"hip_pitch": round(float(joints[1]), 1), "knee": round(float(joints[2]), 1)},
            "torso_drop_mm": round((sim.start_height - float(sim.data.xpos[sim.torso][2])) * 1000.0, 1),
            "peak_sink_speed_m_s": round(speed, 3), "touching_floor": sorted(kinds)}


def sitting(preset: str, progress) -> dict:
    progress(f"{preset}: sit and stand up")
    keep = ("sat_down", "relaxed_rest_stable", "stood_up", "parts_that_touched_the_floor")
    out = sit_run(preset)
    out["relaxed_with_no_joint_friction"] = {k: v for k, v in sit_run(preset, relaxed_friction=0.0).items() if k in keep + ("relaxed_rest",)}
    out["relaxed_and_shoved"] = [{"shove_m_s": v, **{k: w for k, w in sit_run(preset, shove_m_s=v).items() if k in keep}} for v in (0.1, -0.1)]
    out["friction"] = [{"floor_friction": mu, **{k: v for k, v in sit_run(preset, mu=mu).items() if k in keep}} for mu in ROBUST_FRICTION]
    out["pulses_stopped_at_the_stand_pose"] = relax_from_stand(preset)
    out["pulses_stopped_at_the_stand_pose_no_joint_friction"] = relax_from_stand(preset, 0.0)
    out["head"] = [{"case": label, **{k: v for k, v in sit_run(preset, head=head).items() if k in keep}} for label, head in HEAD_CASES]
    return out


# --- the evidence for the design change --------------------------------------

def one_foot_test(preset) -> dict:
    """From the stand pose lift one foot slowly (hip +15, knee -40 degrees,
    0.7 s), hold 2.5 s, set it down. Each side in turn."""
    sim = motionsim.MotionSim(preset)
    stand = list(sim.cal.stand_deg)
    out = {}
    for side, i in (("left", 1), ("right", 4)):
        lifted = list(stand)
        lifted[i] += 15.0
        lifted[i + 1] -= 40.0
        sim.reset()
        log = motionsim.run(sim, motions.keyframes([(0.0, stand), (0.3, stand), (1.0, lifted), (3.5, lifted), (4.2, stand), (5.0, stand)],
                                                   sim.cal.max_speed_deg_s, sim.cal))
        hold = (log["t"] > 1.6) & (log["t"] < 3.4)
        clear = log[f"clear_{side}"][hold] * 1000.0
        other = log["force_right" if side == "left" else "force_left"][hold]
        out[side] = {"fell": log["fell_at"] is not None, "fell_how": log["fell_how"],
                     "lifted_foot_clear_of_floor_fraction": round(float((clear > 0.5).mean()), 2),
                     "lifted_foot_clearance_mm": round(float(np.median(clear)), 1),
                     "load_on_other_foot_fraction": round(float(np.median(other)) / (sim.mass * 9.80665), 2),
                     "max_tilt_deg": round(float(log["tilt"].max()), 1)}
    out["stands_on_one_foot"] = all((not v["fell"]) and v["lifted_foot_clear_of_floor_fraction"] > 0.9 for v in (out["left"], out["right"]))
    return out


def stand_run(preset: str) -> dict:
    sim = motionsim.MotionSim(preset)
    log = motionsim.run(sim, gaitfile.stand(sim.cal.stand_deg, 10.0))
    return {"fell": log["fell_at"] is not None, "max_tilt_deg": round(float(log["tilt"].max()), 2),
            "mass_kg": round(sim.mass, 4), "torso_height_mm": round(sim.start_height * 1000.0, 1),
            **_demand_summary(motionsim.demand(sim, log)), "sole_mass_g": sim.info.get("sole_mass_g")}


# --- files for the robot and the gamepad page --------------------------------

def check_trajectory(trajectory: list, cal, max_speed: float) -> dict:
    """Play a trajectory through protocol.Controller and count what the
    firmware would change: clamped targets and rate-limited steps."""
    limited = replace(cal, max_speed_deg_s=float(max_speed))
    problems = gaitfile.check_limits(trajectory, limited)
    controller = protocol.Controller(limited)
    controller.current = list(trajectory[0][1])
    controller.target = list(trajectory[0][1])
    controller.handle("E", 0)
    clamps, lag = 0, 0.0
    for t, q in trajectory:
        reply = controller.handle(protocol.format_joints(q), t)
        clamps += reply.startswith("OK CLAMP")
        controller.tick(t + protocol.TICK_MS)
        lag = max(lag, max(abs(a - b) for a, b in zip(controller.current, q)))
    return {"limit_problems": len(problems), "clamped_commands": clamps, "max_lag_behind_command_deg": round(lag, 2)}


_ROBOT = []


def mesh_check(trajectory: list, poses: int = 8) -> dict | None:
    """Exact mesh interference (microduck/assembly.py) at evenly spaced poses
    of a trajectory plus its extreme pose of each joint. Only pairs that do
    not already touch at the neutral pose count. None without the STLs."""
    from . import assembly, model
    if not model.have_stls():
        return None
    if not _ROBOT:
        robot = model.build_robot()
        threshold = robot.assumptions["interference_threshold_mm3"]
        ignore = {frozenset((f["a"], f["b"])) for f in assembly.interferences(robot.placed(), threshold)}
        _ROBOT.extend([robot, threshold, ignore])
    robot, threshold, ignore = _ROBOT
    rows = np.array([q for _, q in trajectory])
    picks = set(np.linspace(0, len(rows) - 1, poses).astype(int).tolist())
    picks |= set(rows.argmax(axis=0).tolist()) | set(rows.argmin(axis=0).tolist())
    hits = []
    for i in sorted(picks):
        found = [f for f in assembly.interferences(robot.placed(dict(zip(JOINTS, rows[i]))), threshold)
                 if frozenset((f["a"], f["b"])) not in ignore]
        hits += [{"t_ms": trajectory[i][0], "a": f["a"], "b": f["b"], "volume_mm3": f["volume_mm3"]} for f in found]
    return {"poses_checked": len(picks), "collisions": len(hits), "first": hits[:3]}


def write_files(report: dict, gaits: dict, firmware: dict) -> dict:
    """Trajectories, the manifest and the gait parameter file."""
    folder = ROOT / "trajectories"
    default_speed = firmware["max_speed_deg_s"]["value"]
    jump_speed = firmware["jump_max_speed_deg_s"]["value"]
    entries, params = [], {}
    for preset in PRESETS:
        cal = variant.calibration(preset)
        g = gaits[preset]
        res = report["presets"][preset]
        env = res["walk"]["envelope"]
        steady = res["walk"]["nominal"]

        mesh = preset == "drawn"

        def add(name, trajectory, what, max_speed=default_speed, real=True, loop=None, note=None, tested=None):
            # a motion that needs the speed limit raised is kept apart from the ones a player may pick up
            file = f"{preset}_{name}.csv" if max_speed <= default_speed else f"restricted/{preset}_{name}.csv"
            gaitfile.write_csv(folder / file, trajectory)
            check = check_trajectory(trajectory, cal, max_speed)
            meshes = mesh_check(trajectory) if mesh else None
            check["mesh_collision_check"] = meshes if meshes else "not run: needs the STLs" if mesh else "not run: the variant's soles exist only as boxes"
            entry = {"name": f"{preset}_{name}", "file": file, "preset": preset, "duration_s": round(trajectory[-1][0] / 1000.0, 2),
                     "what": what, "limits": {"max_speed_deg_s": max_speed, "needs_speed_limit_raised": max_speed > default_speed,
                                              "soft_limits": "robot/joints.json" + (" with the preset's overrides" if preset != "drawn" else ""),
                                              **check},
                     "allowed_on_real_hardware_by_default": bool(real), "tested_in_simulation": tested}
            if loop:
                entry["loop"] = loop
            if note:
                entry["note"] = note
            entries.append(entry)

        period_ms = int(round(g["walk"]["params"]["period_s"] * 1000))
        lead_ms = int(round((gaitsearch.CRAWL_LEAD_IN_S if g["walk"]["kind"] == "crawl" else gaitsearch.LEAD_IN_S) * 1000))
        loop = {"from_ms": lead_ms + period_ms, "period_ms": period_ms,
                "how": "after from_ms the file repeats every period_ms; a player may loop that stretch"}
        up_ok = not res["walk"]["nominal"]["fell"]
        gentle = steady.get("peak_torque_fraction", 1.0) < 0.999
        hard = None if gentle else "Not allowed by default: it runs a servo at its stall torque on every beat."
        steps = "steps" if res["walk"]["truly_steps"] else "does not truly step"
        add("walk", walk_trajectory(cal, g["walk"], 12.0)[0],
            f"walk forward, {steady.get('speed_mm_s')} mm/s in simulation ({steps})", real=up_ok and gentle, loop=loop, note=hard,
            tested={"stayed_up": up_ok, "speed_mm_s": steady.get("speed_mm_s"), "peak_torque_fraction": steady.get("peak_torque_fraction")})
        for label, turn in (("turn_left", 1.0), ("turn_right", -1.0)):
            point = next(p for p in env["grid"] if p["speed"] == 1.0 and p["turn"] == turn)
            add(label, walk_trajectory(cal, g["walk"], 12.0, 1.0, turn)[0],
                f"walk with the turn input at {turn:+.0f}: {point['yaw_rate_deg_s']} deg/s in simulation "
                f"({'turns the right way at every tested friction' if env['turn_input_steers_at_every_friction'] else 'heading not reliably controlled'})",
                real=point["stayed_up_all_frictions"] and gentle, loop=loop, note=hard,
                tested={"stayed_up": point["stayed_up_all_frictions"], "yaw_rate_deg_s": point["yaw_rate_deg_s"]})
        jump = res["jump"]["result"]
        add("jump", motions.jump(cal.stand_deg, g["jump"]["params"], jump_speed, cal=replace(cal, max_speed_deg_s=jump_speed))[0],
            f"crouch and push off: a {jump['verdict']} in simulation, soles {jump['feet_rise_mm']} mm off the floor for {jump['flight_s']} s, "
            f"centre of mass rising {jump['com_rise_in_flight_mm']} mm in flight",
            max_speed=jump_speed, real=False,
            note="Untested on real servos and printed plates; it runs the servos at stall torque and can strip gears or break parts. "
                 "Needs the firmware speed limit raised; at the default limit it does not leave the floor.",
            tested={"landed_upright": jump["landed_upright"], "verdict": jump["verdict"]})
        down, up = sit_trajectories(cal)
        sit = res["sit"]
        add("sit", down, "lower from the stand pose to the squat at the travel stops; the rest pose with the servos relaxed"
            if sit["relaxed_rest_stable"] else "lower from the stand pose to the squat", real=sit["sat_down"],
            tested={"sat_down": sit["sat_down"], "relaxed_rest_stable": sit["relaxed_rest_stable"]})
        add("stand_up", up, "rise from the squat to the stand pose", real=sit["stood_up"], tested={"stood_up": sit["stood_up"]})
        params[preset] = {
            "generator": {"sway": "microduck.motions.walk", "crawl": "microduck.motions.crawl"}[g["walk"]["kind"]],
            "kind": g["walk"]["kind"], "params": g["walk"]["params"], "stand_pose_deg": dict(zip(JOINTS, cal.stand_deg)),
            "inputs": {"speed": "0 to 1, scales the stride", "turn": "-1 to 1, positive turns left: shortens the left stride and lengthens the right"},
            "max_speed_deg_s": default_speed,
            "truly_steps": res["walk"]["truly_steps"],
            "tested_envelope": {k: env[k] for k in ("tested_speed", "tested_turn", "tested_floor_friction", "seconds_each",
                                                    "speed_range_all_turns", "turn_range_all_speeds", "forward_mm_s_at_speed",
                                                    "yaw_rate_deg_s_at_turn", "yaw_rate_deg_s_at_turn_by_friction",
                                                    "straight_line_yaw_rate_deg_s", "turn_input_steers",
                                                    "turn_input_steers_at_every_friction")},
            "points": [{k: p[k] for k in ("speed", "turn", "stayed_up_all_frictions", "forward_mm_s", "yaw_rate_deg_s")} for p in env["grid"]],
        }
    manifest = {"generated_by": "scripts/run_motion.py",
                "status": "simulation only; the robot has never been assembled or powered",
                "format": "CSV, header t_ms and the six joint names, joint angles in degrees at 50 Hz (microduck/gait.py)",
                "joint_order": JOINTS, "gait_parameters": "gait_params.json", "trajectories": entries}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    doc = {"generated_by": "scripts/run_motion.py", "status": manifest["status"],
           "note": "A gait stayed up at every tested point inside speed_range_all_turns and turn_range_all_speeds, at floor friction "
                   "0.4, 0.6 and 0.9. Outside those ranges it is untested or it fell; null means no range passed.",
           "presets": params}
    (folder / "gait_params.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return manifest


def run(progress=print, record: bool = True) -> dict:
    gaits = load_gaits()
    config = variant.load_json("motion.json")
    out = {"generated_by": "scripts/run_motion.py",
           "status": "simulation only; the robot has never been assembled or powered",
           "physics": config["physics"], "head": config["head"], "firmware": config["firmware"],
           "robot_presets": {name: p["description"] for name, p in variant.load_presets().items()},
           "search": gaits["search"], "presets": {}}
    for preset in PRESETS:
        g = gaits[preset]
        progress(f"{preset}: stand")
        out["presets"][preset] = {"stand": stand_run(preset), "one_foot_test": one_foot_test(preset),
                                  "walk": walking(preset, g["walk"], progress),
                                  "jump": jumping(preset, g["jump"], config["firmware"], progress),
                                  "sit": sitting(preset, progress)}
    progress("design alternatives")
    out["design_evidence"] = {name: {"description": p["description"], "one_foot_test": one_foot_test(name)}
                              for name, p in variant.load_presets().items()}
    out["manifest"] = "trajectories/manifest.json"
    write_files(out, gaits, config["firmware"])
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
