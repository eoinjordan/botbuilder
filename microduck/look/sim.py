# SPDX-License-Identifier: MIT
"""MuJoCo emulation of the Microduck-look build: stand, and a walking attempt
with the repository's open-loop gait.

Fifteen position servos behind a 50 Hz command path with the firmware's rate
limit (120 deg/s), the soft limits of robot/microduck-look/joints.json and one
tick of delay. No firmware exists for fifteen joints: this command path is a
stand-in for it, with the same tick and rate limit as microduck/protocol.py.

The gait is the one of microduck/gait.py carried to this joint set: both hips
rolled the same way to unload one foot, the hips swung fore and aft with the
ankles turned against them so the soles stay level, and the unloaded leg bent
a little more to lift its foot. Its parameters are searched with
microduck/cmaes.py and scored with microduck/gaitsearch.gait_score.

Two sets of feet are studied: the feet as generated ("web") and the comb feet
of microduck/look/combfeet.py ("comb"). Parts collide with the floor only, so
on the comb feet the search also puts the two feet through their exact meshes
for one gait cycle and refuses a gait in which they overlap.
"""
from __future__ import annotations

import json
import math
import time

import mujoco
import numpy as np

from .. import cmaes, gaitsearch, motionsim
from . import analyse
from .model import FEET, JOINTS, ROOT, Robot, apply, parameters

FOLDER = ROOT / "robot" / "microduck-look"
REPORT = ROOT / "reports" / "microduck-look" / "sim.json"
GAIT_FILE = ROOT / "config" / "microduck-look" / "gait.json"
GAIT_FILES = {"web": GAIT_FILE, "comb": ROOT / "config" / "microduck-look" / "gait_comb.json"}
MODEL_FILES = {"web": "microduck_look.xml", "comb": "microduck_look_comb.xml"}
FEET_OVERLAP_MM3 = 1.0     # above this the two feet are taken to be in each other
TICK_MS = 20
MAX_SPEED_DEG_S = 120.0
FALL_TILT_DEG = 45.0
FALL_HEIGHT_FRACTION = 0.6
GAIT_SPACE = [
    ("period_s", 0.6, 3.0),
    ("roll_amplitude_deg", 0.0, 20.0),
    ("step_amplitude_deg", 1.0, 14.0),
    ("lift_deg", 0.0, 25.0),
    ("step_phase_deg", 30.0, 150.0),
]
SCENARIOS = [(0.6, (0.0, 0.0)), (0.4, (0.0, 1.5)), (0.9, (1.5, 0.0))]      # floor friction, start tilt (roll, pitch) deg
SEARCH_SECONDS = 10.0
LEAD_IN_S = 1.0


def table() -> dict:
    with open(FOLDER / "joints.json", encoding="utf-8") as handle:
        return json.load(handle)


class LookSim:
    def __init__(self, joints: dict | None = None, feet: str = "web"):
        self.table = joints or table()
        self.feet_kind = feet
        self.model = mujoco.MjModel.from_xml_path(str(FOLDER / MODEL_FILES[feet]))
        self.data = mujoco.MjData(self.model)
        name2id = lambda kind, name: mujoco.mj_name2id(self.model, kind, name)      # noqa: E731
        self.trunk = name2id(mujoco.mjtObj.mjOBJ_BODY, "trunk")
        self.qadr = [self.model.jnt_qposadr[name2id(mujoco.mjtObj.mjOBJ_JOINT, j)] for j in JOINTS]
        self.limits = self.model.actuator_forcerange[:, 1].copy()
        self.lo = np.array([self.table["joints"][j]["min_deg"] for j in JOINTS])
        self.hi = np.array([self.table["joints"][j]["max_deg"] for j in JOINTS])
        self.stand = np.array([self.table["stand_pose_deg"][j] for j in JOINTS])
        types = parameters()["servo_types"]
        self.stall_a = np.array([types[self.table["joints"][j]["servo"]]["stall_a"] for j in JOINTS])
        self.board = [self.table["joints"][j]["driven_by"] for j in JOINTS]
        self.steps_per_tick = int(round(TICK_MS / 1000.0 / self.model.opt.timestep))
        self.floor = name2id(mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.feet = {}
        for side in ("left", "right"):
            body = name2id(mujoco.mjtObj.mjOBJ_BODY, f"{side}_foot")
            sole = name2id(mujoco.mjtObj.mjOBJ_GEOM, f"{side}_foot_sole")
            mesh = self.model.geom_dataid[sole]
            start, count = self.model.mesh_vertadr[mesh], self.model.mesh_vertnum[mesh]
            verts = self.model.mesh_vert[start:start + count].copy()
            self.feet[side] = (body, sole, verts[verts[:, 2] < verts[:, 2].min() + 1e-4])
        self.reset()

    def reset(self, tilt_deg=(0.0, 0.0), friction: float | None = None) -> None:
        key = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.model, self.data, key)
        if friction is not None:
            self.model.geom_friction[:, 0] = friction
        roll, pitch = np.radians(tilt_deg)
        quat = np.zeros(4)
        mujoco.mju_euler2Quat(quat, np.array([roll, pitch, 0.0]), "xyz")
        self.data.qpos[3:7] = quat
        mujoco.mj_forward(self.model, self.data)
        # put the lowest sole point on the floor
        self.data.qpos[2] -= min(self._clear(side) for side in self.feet) - 0.0005
        mujoco.mj_forward(self.model, self.data)
        self.commanded = self.stand.copy()
        self.pending = self.stand.copy()
        self.start_height = float(self.data.xpos[self.trunk][2])
        self.now_ms = 0
        self.fell_at = None

    def _clear(self, side: str) -> float:
        _, sole, verts = self.feet[side]
        world = self.data.geom_xpos[sole] + verts @ self.data.geom_xmat[sole].reshape(3, 3).T
        return float(world[:, 2].min())

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.trunk].reshape(3, 3)[:, 2]
        return float(np.degrees(np.arccos(np.clip(up[2], -1.0, 1.0))))

    def yaw_deg(self) -> float:
        x = self.data.xmat[self.trunk].reshape(3, 3)[:, 0]
        return float(np.degrees(np.arctan2(x[1], x[0])))

    def forces(self) -> dict:
        out = {"left": 0.0, "right": 0.0}
        wrench = np.zeros(6)
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            if self.floor not in (c.geom1, c.geom2):
                continue
            other = c.geom2 if c.geom1 == self.floor else c.geom1
            for side, (body, _, _) in self.feet.items():
                if self.model.geom_bodyid[other] == body:
                    mujoco.mj_contactForce(self.model, self.data, i, wrench)
                    out[side] += float(wrench[0])
        return out

    def tick(self, target_deg) -> None:
        """One 20 ms tick: the target sent last tick is taken, clamped to the soft limits and rate limited."""
        self.now_ms += TICK_MS
        step = MAX_SPEED_DEG_S * TICK_MS / 1000.0
        goal = np.clip(self.pending, self.lo, self.hi)
        self.commanded = self.commanded + np.clip(goal - self.commanded, -step, step)
        self.pending = np.asarray(target_deg, float)
        self.data.ctrl[:] = np.radians(self.commanded)
        for _ in range(self.steps_per_tick):
            mujoco.mj_step(self.model, self.data)
        if self.fell_at is None and (self.tilt_deg() > FALL_TILT_DEG or self.data.xpos[self.trunk][2] < FALL_HEIGHT_FRACTION * self.start_height):
            self.fell_at = self.now_ms / 1000.0


def run(sim: LookSim, trajectory) -> dict:
    """Play (t_ms, fifteen angles) rows and log in the shape microduck/motionsim.stepping and gaitsearch.gait_score read."""
    rows = {key: [] for key in ("t", "pos", "tilt", "yaw", "torque", "force_left", "force_right", "clear_left", "clear_right",
                                "foot_left", "foot_right", "com")}
    index = 0
    end_ms = trajectory[-1][0]
    target = sim.stand.copy()
    while sim.now_ms < end_ms:
        while index < len(trajectory) and trajectory[index][0] <= sim.now_ms:
            target = np.asarray(trajectory[index][1], float)
            index += 1
        sim.tick(target)
        force = sim.forces()
        rows["t"].append(sim.now_ms / 1000.0)
        rows["pos"].append(sim.data.xpos[sim.trunk].copy())
        rows["tilt"].append(sim.tilt_deg())
        rows["yaw"].append(sim.yaw_deg())
        rows["torque"].append(sim.data.actuator_force.copy())
        rows["com"].append(sim.data.subtree_com[sim.trunk].copy())
        for side in ("left", "right"):
            rows[f"force_{side}"].append(force[side])
            rows[f"clear_{side}"].append(max(0.0, sim._clear(side)))
            rows[f"foot_{side}"].append(sim.data.xpos[sim.feet[side][0]][:2].copy())
    log = {key: np.array(value) for key, value in rows.items()}
    log.update({"fell_at": sim.fell_at, "current_limited_fraction": 0.0, "part_on_part": {}})
    return log


# ---------------------------------------------------------------- gait
def _axis_y(joints: dict, name: str) -> float:
    return float(joints["joints"][name]["axis"][1])


def gait(joints: dict, params: dict, seconds: float, forward: float = 1.0) -> list:
    """Stand for lead_in_s, ramp in over one period, then walk. Angles in the order of model.JOINTS."""
    stand = [joints["stand_pose_deg"][j] for j in JOINTS]
    at = {j: i for i, j in enumerate(JOINTS)}
    period, roll, step, lift = params["period_s"], params["roll_amplitude_deg"], params["step_amplitude_deg"] * forward, params["lift_deg"]
    phase = math.radians(params["step_phase_deg"])
    lead = params.get("lead_in_s", LEAD_IN_S)
    out = []
    for t in range(0, int(seconds * 1000) + 1, TICK_MS):
        ts = t / 1000.0 - lead
        q = list(stand)
        if ts > 0:
            ramp = min(1.0, ts / period)
            w = 2.0 * math.pi * ts / period
            sway = math.sin(w)                       # +1: trunk over the left foot, the right unloaded
            swing = math.sin(w + phase)
            for side, sign, unloaded in (("left", 1.0, max(0.0, -sway)), ("right", -1.0, max(0.0, sway))):
                q[at[f"{side}_hip_roll"]] += ramp * roll * sway
                hip = ramp * (sign * step * swing - lift * unloaded)      # about +y: negative carries the foot forward
                knee = ramp * 2.0 * lift * unloaded
                q[at[f"{side}_hip_pitch"]] += hip * _axis_y(joints, f"{side}_hip_pitch")
                q[at[f"{side}_knee"]] += knee * _axis_y(joints, f"{side}_knee")
                q[at[f"{side}_ankle"]] += -(hip + knee) * _axis_y(joints, f"{side}_ankle")
        out.append((t, q))
    return out


def mesh_overlaps(robot: Robot, rows, every: int = 5) -> dict:
    """The exact meshes at every few rows of a trajectory: the simulation lets parts pass through each other."""
    hits, pairs = 0, set()
    picked = rows[::every]
    for _, q in picked:
        found = analyse.interferences(robot, dict(zip(JOINTS, [float(v) for v in q])))
        hits += bool(found)
        pairs.update(f"{h['a']} with {h['b']}" for h in found)
    return {"poses_checked": len(picked), "poses_with_overlap": hits, "pairs": sorted(pairs)}


def feet_overlap(robot: Robot, rows, every: int = 4) -> dict:
    """The two feet alone through their exact meshes at every few rows: cheap enough to run for every
    candidate of a search. With comb feet the fingers of one foot lie between those of the other."""
    solids = {side: next(s.solid for s in robot.links[f"{side}_foot"].solids if s.kind == "shell") for side in ("left", "right")}
    picked = rows[::every]
    hits = 0
    for _, q in picked:
        poses = robot.poses(dict(zip(JOINTS, [float(v) for v in q])))
        left, right = (apply(solids[side], poses[f"{side}_foot"]) for side in ("left", "right"))
        hits += bool((left ^ right).volume() > FEET_OVERLAP_MM3)
    return {"poses_checked": len(picked), "poses_with_overlap": hits}


def one_cycle(joints: dict, params: dict) -> list:
    """The commanded rows of the second gait cycle, the first at full amplitude."""
    lead = params.get("lead_in_s", LEAD_IN_S)
    rows = gait(joints, params, lead + 2.0 * params["period_s"])
    return [row for row in rows if lead + params["period_s"] <= row[0] / 1000.0 < lead + 2.0 * params["period_s"]]


def from_unit(x) -> dict:
    return {name: lo + min(max(float(v), 0.0), 1.0) * (hi - lo) for (name, lo, hi), v in zip(GAIT_SPACE, x)}


def score(sim: LookSim, params: dict, guard: Robot | None = None) -> tuple:
    if guard is not None:
        met = feet_overlap(guard, one_cycle(sim.table, params))
        if met["poses_with_overlap"]:
            return -10.0 - met["poses_with_overlap"] / met["poses_checked"], []
    trajectory = gait(sim.table, params, SEARCH_SECONDS)
    scores, facts = [], []
    for friction, tilt in SCENARIOS:
        sim.reset(tilt, friction)
        value, fact = gaitsearch.gait_score(run(sim, trajectory), params, SEARCH_SECONDS, sim.limits, 0.0, LEAD_IN_S)
        scores.append(value)
        facts.append(fact)
    return 0.6 * float(np.mean(scores)) + 0.4 * float(np.min(scores)), facts


def search(sim: LookSim, seed: int, generations: int, popsize: int, budget_s: float, progress=None, guard: Robot | None = None) -> dict:
    result = cmaes.maximise(lambda xs: [score(sim, from_unit(x), guard)[0] for x in xs], len(GAIT_SPACE), seed, None, 0.25,
                            popsize, generations, budget_s, progress)
    result["params"] = {k: round(v, 2) for k, v in from_unit(result["x"]).items()}
    result["runs_per_candidate"] = len(SCENARIOS)
    return result


def describe_run(sim: LookSim, log: dict, params: dict | None, seconds: float) -> dict:
    t = log["t"]
    upright = t <= (log["fell_at"] if log["fell_at"] is not None else t[-1])
    window = upright & (t >= min(1.0, t[-1] / 2))
    torque = np.abs(log["torque"])
    out = {"duration_s": round(float(t[-1]), 2), "fell": log["fell_at"] is not None, "fell_at_s": log["fell_at"],
           "distance_forward_mm": round(float(log["pos"][upright][-1][0] - log["pos"][0][0]) * 1000.0, 1),
           "drift_left_mm": round(float(log["pos"][upright][-1][1] - log["pos"][0][1]) * 1000.0, 1),
           "heading_change_deg": round(float(log["yaw"][upright][-1] - log["yaw"][0]), 1),
           "max_tilt_deg": round(float(log["tilt"][upright].max()), 2),
           "torque": {j: {"peak_nm": round(float(torque[window, i].max()), 3), "mean_nm": round(float(torque[window, i].mean()), 3),
                          "limit_nm": round(float(sim.limits[i]), 3), "peak_over_limit": round(float(torque[window, i].max() / sim.limits[i]), 2)}
                      for i, j in enumerate(JOINTS)}}
    # supply current: each servo taken to draw its stall current in proportion to its torque
    amps = torque[window] / sim.limits * sim.stall_a
    out["estimated_supply_current_a"] = {
        name: {"peak": round(float(amps[:, [i for i, b in enumerate(sim.board) if b in boards]].sum(axis=1).max()), 2),
               "mean": round(float(amps[:, [i for i, b in enumerate(sim.board) if b in boards]].sum(axis=1).mean()), 2)}
        for name, boards in (("board 1 with the driver", ("board 1", "driver")), ("board 2", ("board 2",)))}
    if params is not None:
        st = motionsim.stepping(log, LEAD_IN_S + params["period_s"])
        expected = 2.0 * (seconds - LEAD_IN_S - params["period_s"]) / params["period_s"]
        out["stepping"] = {k: st[k] for k in ("single_support_fraction", "double_support_fraction", "steps", "alternating",
                                              "median_clearance_mm", "median_swing_s", "step_length_mm", "stance_slip_mm_per_step")}
        out["stepping"]["steps_commanded"] = round(expected, 1)
        out["speed_mm_s"] = round(out["distance_forward_mm"] / (seconds - LEAD_IN_S), 1)
        out["truly_steps"] = bool(not out["fell"] and st["alternating"] and st["steps"] >= 0.8 * expected and out["distance_forward_mm"] > 0)
    return out


def study(seed: int = 1, generations: int = 12, popsize: int = 12, budget_s: float = 420.0, progress=print, feet=FEET) -> dict:
    """Stand, one foot and the walking attempt for each set of feet named. The feet as generated fill the
    report; the comb feet are its "comb_feet" entry. A set that is not named keeps what the report holds."""
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.is_file() else {}
    with open(ROOT / "reports" / "microduck-look" / "assembly.json", encoding="utf-8") as handle:
        assembly = json.load(handle)
    if "web" in feet:
        kept = report.get("comb_feet")
        report = _study("web", assembly, seed, generations, popsize, budget_s)
        if kept is not None:
            report["comb_feet"] = kept
    if "comb" in feet:
        comb = _study("comb", assembly["comb_feet"], seed, generations, popsize, budget_s)
        if "walk" in report:
            # the gait found on the other feet, on these: the feet changed and nothing else
            sim = LookSim(feet="comb")
            params = report["walk"]["params"]
            seconds = 30.0
            other = describe_run(sim, run(sim, gait(sim.table, params, seconds)), params, seconds)
            other["params"] = params
            other["feet_overlap"] = feet_overlap(Robot(feet="comb"), one_cycle(sim.table, params))
            comb["walk_with_the_gait_of_the_plain_feet"] = other
        report["comb_feet"] = comb
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    return report


def _study(feet: str, assembly: dict, seed: int, generations: int, popsize: int, budget_s: float) -> dict:
    sim = LookSim(feet=feet)
    robot = Robot(feet=feet)
    report = {"generated_by": "scripts/run_look.py", "model": "robot/microduck-look/" + MODEL_FILES[feet],
              "mass_kg": round(float(sim.model.body_mass.sum()), 4),
              "command_path": {"tick_ms": TICK_MS, "max_speed_deg_s": MAX_SPEED_DEG_S, "delay_ticks": 1,
                               "floor_friction": float(sim.model.geom_friction[sim.floor, 0])}}
    # stand
    sim.reset()
    seconds = 10.0
    log = run(sim, [(t, sim.stand) for t in range(0, int(seconds * 1000) + 1, TICK_MS)])
    report["stand"] = describe_run(sim, log, None, seconds)
    force = (log["force_left"][-50:].mean(), log["force_right"][-50:].mean())
    report["stand"]["foot_load_n"] = {"left": round(float(force[0]), 2), "right": round(float(force[1]), 2)}
    # stand with the neck and head moved through their soft ranges
    at = {j: i for i, j in enumerate(JOINTS)}
    rows = []
    for t in range(0, 12001, TICK_MS):
        q = sim.stand.copy()
        s = math.sin(2.0 * math.pi * t / 4000.0)
        q[at["neck_pitch"]] += -25.0 * max(0.0, s)
        q[at["head_pitch"]] += 25.0 * s
        q[at["head_yaw"]] += 60.0 * math.sin(2.0 * math.pi * t / 6000.0)
        q[at["head_roll"]] += 20.0 * math.sin(2.0 * math.pi * t / 3000.0)
        q[at["beak"]] += 15.0 * (1.0 - math.cos(2.0 * math.pi * t / 2000.0))
        rows.append((t, q))
    sim.reset()
    report["head_motion_while_standing"] = describe_run(sim, run(sim, rows), None, 12.0)
    # one foot, slowly: the pose of the assembly test
    report["one_foot"] = one_foot_runs(sim, robot, assembly)
    # walking attempt
    started = time.time()
    return _walk(sim, robot, report, seed, generations, popsize, budget_s, started)


def one_foot_runs(sim: LookSim, robot: Robot, assembly: dict) -> dict:
    """Slowly into the one-foot pose of the assembly test: both hips rolled over three seconds, then the other
    leg bent. There is no ankle roll, so the question is whether the weight comes on to one sole at all."""
    at = {j: i for i, j in enumerate(JOINTS)}
    report = {"one_foot": {}}
    for side in ("left", "right"):
        pose = assembly["one_foot"][side]
        if not pose.get("found"):
            report["one_foot"][side] = {"held": False, "why": "the assembly test found no pose"}
            continue
        goal = np.array([pose["q_deg"][j] for j in JOINTS])
        shift = sim.stand.copy()
        for j in ("left_hip_roll", "right_hip_roll"):
            shift[at[j]] = goal[at[j]]
        rows = []
        for t in range(0, 9001, TICK_MS):
            if t < 3000:
                q = sim.stand + (shift - sim.stand) * t / 3000.0
            elif t < 5000:
                q = shift + (goal - shift) * (t - 3000) / 2000.0
            else:
                q = goal
            rows.append((t, q))
        sim.reset()
        log = run(sim, rows)
        overlaps = mesh_overlaps(robot, rows, 25)
        swing = "right" if side == "left" else "left"
        hold = log["t"] > 6.0
        report["one_foot"][side] = {
            "held": bool(log["fell_at"] is None and log[f"force_{swing}"][hold].max() < motionsim.LOADED_N),
            "fell": log["fell_at"] is not None,
            "foot_load_n": {side: round(float(log[f"force_{side}"][hold].mean()), 2), swing: round(float(log[f"force_{swing}"][hold].mean()), 2)},
            "trunk_tilt_deg": round(float(log["tilt"][hold].mean()), 1), "trunk_tilt_of_the_pose_deg": abs(pose["roll_deg"]),
            "max_tilt_deg": round(float(log["tilt"].max()), 1), "mesh_overlaps": overlaps,
            "peak_torque_over_limit": {j: round(float(np.abs(log["torque"][hold, i]).max() / sim.limits[i]), 2) for i, j in enumerate(JOINTS)
                                       if j.startswith(side)}}
    return report["one_foot"]


def _walk(sim: LookSim, robot: Robot, report: dict, seed: int, generations: int, popsize: int, budget_s: float, started: float) -> dict:
    guard = robot if sim.feet_kind == "comb" else None
    found = search(sim, seed, generations, popsize, budget_s, None, guard)
    params = dict(found["params"], lead_in_s=LEAD_IN_S)
    seconds = 30.0
    sim.reset()
    log = run(sim, gait(sim.table, params, seconds))
    walk = describe_run(sim, log, params, seconds)
    walk["params"] = params
    one_period = one_cycle(sim.table, params)
    walk["mesh_overlaps"] = mesh_overlaps(robot, one_period, 4)
    if guard is not None:
        walk["search_refuses_feet_that_overlap"] = True
        walk["feet_overlap"] = feet_overlap(robot, one_period)
    walk["search"] = {"seed": seed, "generations": found["generations"], "popsize": popsize, "candidates": found["evaluations"],
                      "simulated_runs": found["evaluations"] * len(SCENARIOS), "seconds_each": SEARCH_SECONDS,
                      "wall_clock_s": round(time.time() - started, 1), "best_score": round(found["score"], 3), "history": found["history"]}
    by_friction = []
    for friction in (0.4, 0.6, 0.9):
        sim.reset((0.0, 0.0), friction)
        r = describe_run(sim, run(sim, gait(sim.table, params, 20.0)), params, 20.0)
        by_friction.append({"floor_friction": friction, "fell": r["fell"], "speed_mm_s": r["speed_mm_s"], "truly_steps": r["truly_steps"],
                            "steps": r["stepping"]["steps"], "clearance_mm": r["stepping"]["median_clearance_mm"],
                            "heading_change_deg": r["heading_change_deg"]})
    sim.reset((0.0, 0.0), 0.6)
    walk["by_floor_friction"] = by_friction
    report["walk"] = walk
    target = GAIT_FILES[sim.feet_kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    comment = "Open-loop gait parameters of the Microduck-look build, found by scripts/run_look.py --sim. Simulation only."
    if sim.feet_kind == "comb":
        comment = "Open-loop gait parameters of the Microduck-look build on its comb feet, found by scripts/run_look.py --sim. Simulation only."
    target.write_text(json.dumps({"_comment": comment, **params}, indent=1) + "\n", encoding="utf-8", newline="\n")
    return report
