# SPDX-License-Identifier: MIT
"""Seeded search for the walking gait's parameters and for a jump.

The gait score rewards what the owner asked for: staying up, forward
progress, and real steps (one sole wholly off the floor while the other
carries the load, left and right in turn). It charges for heading drift, for
running a servo near its torque limit, for one leg touching the other, and
for commands the controller's leg clearance rule would refuse. Each candidate
is run on four perturbed copies of the robot (friction, mass, initial tilt
and push) and scored on the mean and the worst of them, and twice more with
the turn input left and right, so a gait that only works on the nominal model
or cannot steer does not win.
"""
from __future__ import annotations

import multiprocessing
from dataclasses import replace

import numpy as np

from . import cmaes, motiongen, motionsim, protocol, variant

# floor friction, mass scale, initial (roll, pitch) deg, initial push (x, y) m/s
SCENARIOS = [
    (0.6, 1.00, (0.0, 0.0), (0.0, 0.0)),
    (0.4, 1.06, (0.0, 1.5), (0.0, 0.0)),
    (0.9, 0.94, (1.5, 0.0), (0.0, 0.03)),
    (0.6, 1.00, (-1.0, -1.0), (0.02, -0.02)),
]
SEARCH_SECONDS = 10.0
TURN_SECONDS = 8.0
TURN_INPUT = 0.6
LEAD_IN_S = 1.0
TORQUE_MARGIN = 0.8         # peak torque over the limit above which the score is charged
_SIMS: dict = {}


def sims(preset, head=None, physics=None, max_speed=None) -> list:
    """One simulator per scenario, kept for the life of the process.
    max_speed raises the firmware rate limit (the jump needs it)."""
    key = repr((preset, head, physics, max_speed))
    if key not in _SIMS:
        made = []
        cal = variant.calibration(preset)
        if max_speed:
            cal = replace(cal, max_speed_deg_s=float(max_speed))
        for mu, mass, _, _ in SCENARIOS:
            s = motionsim.MotionSim(preset, physics=physics, head=head, mass_scale=mass, cal=cal)
            s.set_floor_friction(mu)
            made.append(s)
        _SIMS[key] = made
    return _SIMS[key]


def refused_fraction(cal: protocol.Calibration, trajectory: list) -> float:
    """Part of a trajectory's rows the leg clearance rule refuses."""
    if not cal.clearance:
        return 0.0
    return sum(1 for _, q in trajectory if not protocol.legs_clear(cal.clearance, q)) / len(trajectory)


def touching_fraction(log: dict, t0: float = 0.0) -> float:
    """Part of the ticks in which one part of the robot pressed on another."""
    ticks = {t for rows in log["part_on_part"].values() for t, _ in rows if t >= t0}
    return len(ticks) / max(int((log["t"] >= t0).sum()), 1)


def gait_score(log: dict, params: dict, seconds: float, limits, refused: float = 0.0, lead_in_s: float = LEAD_IN_S) -> tuple:
    """Score of one straight run and the facts it was made from."""
    if log["fell_at"] is not None:
        return -5.0 + 5.0 * log["fell_at"] / seconds, {"fell": True}
    t0 = lead_in_s + params["period_s"]
    st = motionsim.stepping(log, t0)
    i0 = int(np.searchsorted(log["t"], t0))
    distance = float(log["pos"][-1][0] - log["pos"][i0][0])
    drift = float(log["pos"][-1][1] - log["pos"][i0][1])
    expected = 2.0 * (seconds - t0) / params["period_s"]
    step_fraction = min(1.0, st["steps"] / max(expected, 1.0)) * (1.0 if st["alternating"] else 0.5)
    clearance = min(st["median_clearance_mm"], 4.0) / 4.0
    window = log["t"] >= t0
    peak = float((np.abs(log["torque"][window]) / limits).max())
    yaw = float(np.abs(log["yaw"][window]).max())
    touching = touching_fraction(log, t0)
    score = (1.0 + 15.0 * min(distance, 0.6) * (0.25 + 0.75 * step_fraction) + 2.0 * step_fraction + clearance * step_fraction
             - yaw / 10.0 - 5.0 * abs(drift) - max(0.0, float(log["tilt"].max()) - 20.0) / 10.0
             - 3.0 * max(0.0, peak - TORQUE_MARGIN) / (1.0 - TORQUE_MARGIN) - 4.0 * log["current_limited_fraction"]
             - 25.0 * touching - 25.0 * refused)
    return score, {"fell": False, "distance_m": distance, "step_fraction": step_fraction, "steps": st["steps"],
                   "clearance_mm": st["median_clearance_mm"], "single_support": st["single_support_fraction"],
                   "peak_torque_fraction": peak, "max_yaw_deg": yaw, "touching": touching}


def turn_score(yaw_left: float | None, yaw_right: float | None) -> float:
    """Reward for turning the right way both ways; None is a fall."""
    if yaw_left is None or yaw_right is None:
        return -2.0
    return 3.0 * float(np.clip(min(yaw_left, -yaw_right) / 5.0, -1.0, 1.0))


def evaluate_gait(args) -> float:
    preset, x, head, physics = args
    params = motiongen.from_unit(motiongen.GAIT_SPACE, x)
    made = sims(preset, head, physics)
    cal = made[0].cal
    straight = motiongen.walk(cal.stand_deg, params, SEARCH_SECONDS, 1.0, 0.0, LEAD_IN_S, cal.max_speed_deg_s, cal)
    refused = refused_fraction(cal, straight)
    scores = []
    for s, (_, _, tilt, push) in zip(made, SCENARIOS):
        s.reset(tilt_deg=tilt, push_m_s=push)
        scores.append(gait_score(motionsim.run(s, straight), params, SEARCH_SECONDS, s.limits, refused)[0])
    rates = []
    for turn in (TURN_INPUT, -TURN_INPUT):
        s = made[0]
        s.reset()
        trajectory = motiongen.walk(cal.stand_deg, params, TURN_SECONDS, 1.0, turn, LEAD_IN_S, cal.max_speed_deg_s, cal)
        log = motionsim.run(s, trajectory)
        if log["fell_at"] is not None:
            rates.append(None)
            continue
        i0 = int(np.searchsorted(log["t"], LEAD_IN_S + params["period_s"]))
        yaw = np.degrees(np.unwrap(np.radians(log["yaw"][i0:])))
        rates.append(float(yaw[-1] - yaw[0]) / float(log["t"][-1] - log["t"][i0])
                     - 25.0 * (touching_fraction(log) + refused_fraction(cal, trajectory)) * np.sign(turn))
    return 0.6 * float(np.mean(scores)) + 0.4 * float(np.min(scores)) + turn_score(*rates)


def jump_metrics(sim: motionsim.MotionSim, log: dict, t_push: float) -> dict:
    """Rise of the centre of mass and of the soles, flight time, landing."""
    t = log["t"]
    before = (t > t_push - 0.3) & (t <= t_push)
    after = t > t_push
    clear = np.minimum(log["clear_left"], log["clear_right"])
    upright = t < (log["fell_at"] if log["fell_at"] is not None else t[-1] + 1.0)
    airborne = after & upright & (log["force_total"] <= motionsim.LOADED_N) & (clear > 0.0)
    edges = np.flatnonzero(np.diff(np.r_[0, airborne.astype(int), 0]))
    flights = [(a, b) for a, b in zip(edges[::2], edges[1::2])]
    if flights:
        a, b = max(flights, key=lambda ab: ab[1] - ab[0])
        flight_s = float((b - a) * (t[1] - t[0]))
        feet_rise = float(clear[a:b].max())
        takeoff_s = float(t[a] - t_push)
        z = log["com"][:, 2]
        com_flight = float(z[max(a - 1, 0):b].max() - z[max(a - 1, 0)])
        takeoff_speed = float((z[a] - z[a - 2]) / (t[a] - t[a - 2])) if a >= 2 else 0.0
    else:
        flight_s, feet_rise, takeoff_s, com_flight, takeoff_speed = 0.0, 0.0, None, 0.0, 0.0
    com0 = float(log["com"][before, 2].mean())
    stand_com = float(log["com"][t < 0.3, 2].mean())
    return {"flight_s": round(flight_s, 3), "feet_rise_mm": round(feet_rise * 1000.0, 2),
            "takeoff_after_push_s": None if takeoff_s is None else round(takeoff_s, 3),
            "com_rise_in_flight_mm": round(com_flight * 1000.0, 2), "com_speed_up_at_takeoff_m_s": round(takeoff_speed, 3),
            "com_rise_above_crouch_mm": round((float(log["com"][after, 2].max()) - com0) * 1000.0, 2),
            "com_rise_above_stand_mm": round((float(log["com"][after, 2].max()) - stand_com) * 1000.0, 2),
            "landed_upright": log["fell_at"] is None,
            "fell_how": log["fell_how"], "fell_at_s": log["fell_at"],
            "final_tilt_deg": round(float(log["tilt"][-1]), 2),
            "max_tilt_deg": round(float(log["tilt"].max()), 2),
            "travel_forward_mm": round(float(log["pos"][-1][0] - log["pos"][0][0]) * 1000.0, 1),
            "peak_supply_current_a": round(float(log["current"].max()), 2),
            "supply_limited_fraction_of_push": round(float((log["current"][after & (t < t_push + 0.3)] > sim.supply_a).mean()), 3),
            "legs_touched": bool(log["part_on_part"])}


def evaluate_jump(args) -> float:
    preset, x, head, physics, max_speed = args
    params = motiongen.from_unit(motiongen.JUMP_SPACE, x)
    scores = []
    for s, (_, _, tilt, _) in zip(sims(preset, head, physics, max_speed), SCENARIOS):
        s.reset(tilt_deg=tilt)
        trajectory, t_push = motiongen.jump(s.cal.stand_deg, params, max_speed, cal=s.cal)
        log = motionsim.run(s, trajectory)
        m = jump_metrics(s, log, t_push)
        score = m["feet_rise_mm"] + 20.0 * m["flight_s"] + 0.1 * max(0.0, m["com_rise_above_crouch_mm"])
        if not m["landed_upright"]:
            score = 0.2 * score - 3.0
        score -= 5.0 * touching_fraction(log) + 5.0 * refused_fraction(s.cal, trajectory)
        scores.append(score)
    return 0.6 * float(np.mean(scores)) + 0.4 * float(np.min(scores))


def search(kind: str, preset, seed: int, generations: int, popsize: int, budget_s: float, workers: int,
           head=None, physics=None, x0=None, sigma0: float = 0.25, max_speed: float | None = None, progress=None) -> dict:
    """Run CMA-ES for the gait ('gait') or a jump ('jump') on a preset."""
    if kind == "gait":
        function, dim = evaluate_gait, len(motiongen.GAIT_SPACE)
        pack = lambda x: (preset, x, head, physics)                 # noqa: E731
        runs = len(SCENARIOS) + 2
    else:
        function, dim = evaluate_jump, len(motiongen.JUMP_SPACE)
        pack = lambda x: (preset, x, head, physics, max_speed)      # noqa: E731
        runs = len(SCENARIOS)
    if workers > 1:
        with multiprocessing.Pool(workers) as pool:
            result = cmaes.maximise(lambda xs: pool.map(function, [pack(x) for x in xs]), dim, seed, x0, sigma0,
                                    popsize, generations, budget_s, progress)
    else:
        result = cmaes.maximise(lambda xs: [function(pack(x)) for x in xs], dim, seed, x0, sigma0,
                                popsize, generations, budget_s, progress)
    result.update({"kind": kind, "popsize": popsize, "workers": workers, "budget_s": budget_s, "runs_per_candidate": runs})
    return result
