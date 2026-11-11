# SPDX-License-Identifier: MIT
"""MuJoCo simulation of a crank walker with a model of its two motors.

Each motor is a torque source behind a speed and phase controller, as the
controller sketches in walkers/controllers/ are: the reference crank angle of
each side advances at the commanded speed, and the torque is a proportional
and derivative correction of the angle error. The torque is then clipped to
what the motor can give at its present speed: the straight line from the
stall torque at rest to zero at the no-load speed. The motor is on the rear
gear axle, so the ratio to the crank is 1.
"""
from __future__ import annotations

import json
from pathlib import Path

import mujoco
import numpy as np

from . import mjcf, model

CONTROL_DT = 0.005
KP = 3.0            # N m per rad of crank angle error
KD = 0.04           # N m per rad/s
MAX_LEAD = 0.6      # rad the reference may run ahead of a crank that cannot follow
FALL_TILT_DEG = 35.0
MM = 0.001


class WalkerSim:
    def __init__(self, build: str, xml: str | Path | None = None, friction: float | None = None):
        self.build = build
        path = Path(xml) if xml else mjcf.OUT / f"{build}.xml"
        with open(mjcf.OUT / f"{build}.json", encoding="utf-8") as handle:
            self.meta = json.load(handle)
        self.model = mujoco.MjModel.from_xml_path(str(path))
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.stall = self.meta["motor"]["stall_torque_nm"]
        self.w0 = self.meta["motor"]["no_load_rpm"] * 2 * np.pi / 60.0
        self.chassis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "chassis")
        self.sides = ("left", "right")

        def jid(name):
            return mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
        self.q = {n: m.jnt_qposadr[jid(n)] for s in self.sides for n in (f"{s}_rear_crank", f"{s}_front_crank", f"{s}_leg_pivot")}
        self.v = {n: m.jnt_dofadr[jid(n)] for n in self.q}
        self.legs = {s: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"{s}_leg") for s in self.sides}
        self.floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.step_geom = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "step")
        self.hit = [g for g in range(m.ngeom) if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "").endswith("_hit")]
        self.gravity = 9.81
        self.step_pos = [0.0, 0.0, -1.0]
        if friction is not None:
            self.set_friction(friction)
        self.reset()

    # -- set-up --
    def set_friction(self, mu: float) -> None:
        self.model.geom_friction[:, 0] = mu

    def set_slope(self, uphill_deg: float = 0.0, left_high_deg: float = 0.0) -> None:
        """Tilt gravity instead of the floor: uphill_deg > 0 is a climb when
        walking forward, left_high_deg > 0 raises the left side."""
        a, b = np.radians(uphill_deg), np.radians(left_high_deg)
        self.model.opt.gravity[:] = [-self.gravity * np.sin(a), -self.gravity * np.sin(b) * np.cos(a),
                                     -self.gravity * np.cos(a) * np.cos(b)]

    def set_step(self, x_m: float, height_m: float) -> None:
        """A long step across the path: its near edge at x_m, top at height_m."""
        g = self.step_geom
        half = float(self.model.geom_size[g][2])
        self.step_pos = [x_m + 0.5, 0.0, height_m - half if height_m > 0 else -1.0]
        self.data.mocap_pos[0] = self.step_pos

    def reset(self, phase_deg: float = mjcf.START_PHASE, phase_error_deg: float = 0.0) -> None:
        mujoco.mj_resetData(self.model, self.data)
        d = self.data
        d.mocap_pos[0] = self.step_pos
        left = np.radians(phase_deg)
        right = np.radians(phase_deg + 180.0 + phase_error_deg)
        for side, angle in (("left", left), ("right", right)):
            d.qpos[self.q[f"{side}_rear_crank"]] = angle
            d.qpos[self.q[f"{side}_front_crank"]] = angle
            d.qpos[self.q[f"{side}_leg_pivot"]] = -angle
        low = min(-np.sin(left), -np.sin(right))
        d.qpos[2] = (model.LEG_DROP - model.CRANK_R * low) * MM + 0.0003
        mujoco.mj_forward(self.model, d)
        self.ref = {"left": left, "right": right}
        self.gap = right - left - np.pi     # commanded offset of the right side beyond half a turn
        self.time = 0.0
        self.fell_at = None
        self.fell_how = None
        self.start = d.xpos[self.chassis].copy()
        self.steps = int(round(CONTROL_DT / self.model.opt.timestep))

    # -- state --
    def crank(self, side: str) -> tuple:
        return float(self.data.qpos[self.q[f"{side}_rear_crank"]]), float(self.data.qvel[self.v[f"{side}_rear_crank"]])

    def attitude(self) -> tuple:
        """Roll, pitch, yaw of the chassis in degrees (roll > 0: left side up;
        pitch > 0: nose down)."""
        r = self.data.xmat[self.chassis].reshape(3, 3)
        return (float(np.degrees(np.arctan2(r[2, 1], r[2, 2]))), float(np.degrees(-np.arcsin(np.clip(r[2, 0], -1, 1)))),
                float(np.degrees(np.arctan2(r[1, 0], r[0, 0]))))

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.chassis].reshape(3, 3)[:, 2]
        g = -self.model.opt.gravity / np.linalg.norm(self.model.opt.gravity)
        return float(np.degrees(np.arccos(np.clip(up @ g, -1.0, 1.0))))

    def foot_forces(self) -> dict:
        force = {"left": 0.0, "right": 0.0}
        wrench = np.zeros(6)
        m, d = self.model, self.data
        for i in range(d.ncon):
            c = d.contact[i]
            for geom in (c.geom1, c.geom2):
                body = m.geom_bodyid[geom]
                for side, leg in self.legs.items():
                    if body == leg:
                        mujoco.mj_contactForce(m, d, i, wrench)
                        force[side] += float(wrench[0])
        return force

    def body_on_floor(self) -> bool:
        d = self.data
        return any(d.contact[i].geom1 in self.hit or d.contact[i].geom2 in self.hit for i in range(d.ncon))

    def torque_limits(self, speed: float) -> tuple:
        """Lowest and highest torque the motor can give at this speed."""
        return (max(-self.stall, -self.stall * (1.0 + speed / self.w0)),
                min(self.stall, self.stall * (1.0 - speed / self.w0)))

    # -- one control period --
    def tick(self, speed_cmd: dict, hold: bool = True) -> dict:
        """Advance 5 ms. speed_cmd: commanded crank speed per side in rad/s,
        or None for a side to coast."""
        d = self.data
        torque = {}
        for i, side in enumerate(self.sides):
            angle, speed = self.crank(side)
            cmd = speed_cmd.get(side)
            if cmd is None:
                torque[side] = 0.0
                self.ref[side] = angle
            else:
                cmd = float(np.clip(cmd, -self.w0, self.w0))
                self.ref[side] = float(np.clip(self.ref[side] + cmd * CONTROL_DT, angle - MAX_LEAD, angle + MAX_LEAD))
                wanted = KP * (self.ref[side] - angle) + KD * (cmd - speed)
                lo, hi = self.torque_limits(speed)
                torque[side] = float(np.clip(wanted, min(lo, 0.0) if speed > -self.w0 else 0.0, max(hi, 0.0) if speed < self.w0 else 0.0))
            d.ctrl[i] = torque[side]
        for _ in range(self.steps):
            mujoco.mj_step(self.model, d)
        self.time += CONTROL_DT
        if self.fell_at is None and (self.tilt_deg() > FALL_TILT_DEG or self.body_on_floor()):
            self.fell_at = round(self.time, 3)
            roll, pitch, _ = self.attitude()
            if abs(roll) > abs(pitch):
                self.fell_how = "to the right" if roll > 0 else "to the left"
            else:
                self.fell_how = "forward" if pitch > 0 else "backward"
        return torque


def run(sim: WalkerSim, command, duration_s: float, on_tick=None, settle_s: float = 1.0) -> dict:
    """Run a command profile: command(t) returns {"left": rad/s, "right": rad/s}."""
    rows = []
    slip = {"left": 0.0, "right": 0.0}
    d = sim.data
    start = d.xpos[sim.chassis].copy()
    turns0 = {s: sim.crank(s)[0] for s in sim.sides}
    while sim.time < duration_s - 1e-9:
        cmd = command(sim.time)
        torque = sim.tick(cmd)
        force = sim.foot_forces()
        for side in sim.sides:
            if force[side] > 0.2:
                v = d.cvel[sim.legs[side]][3:5]
                slip[side] += float(np.hypot(*v)) * CONTROL_DT
        roll, pitch, yaw = sim.attitude()
        rows.append((sim.time, *d.xpos[sim.chassis], roll, pitch, yaw, torque["left"], torque["right"],
                     sim.crank("left")[0], sim.crank("right")[0], sim.crank("left")[1], sim.crank("right")[1],
                     force["left"], force["right"], sim.tilt_deg()))
        if on_tick:
            on_tick(sim)
        if sim.fell_at is not None and sim.time > sim.fell_at + 0.5:
            break
    a = np.array(rows)
    t = a[:, 0]
    up = t <= (sim.fell_at if sim.fell_at is not None else t[-1])
    steady = up & (t >= min(settle_s, t[-1] / 2))
    if not steady.any():
        steady = up
    last = np.nonzero(up)[0][-1]
    turns = {s: (a[last, 9 + i] - turns0[s]) / (2 * np.pi) for i, s in enumerate(sim.sides)}
    ideal = model.STRIDE * MM * (abs(turns["left"]) + abs(turns["right"])) / 2.0
    forward = float(a[last, 1] - start[0])
    span = float(t[last] - 0.0)
    yaw = np.unwrap(np.radians(a[:, 6]))
    phase_gap = np.degrees((a[steady, 10] - a[steady, 9] - sim.gap) % (2 * np.pi) - np.pi) if steady.any() else np.zeros(1)
    limit = sim.stall
    tq = np.abs(a[steady][:, 7:9])
    speeds = a[steady][:, 11:13]
    available = np.maximum(sim.stall * (1.0 - np.abs(speeds) / sim.w0), 1e-6)
    fl, fr = a[up][:, 13], a[up][:, 14]
    return {
        "duration_s": round(float(t[-1]), 2),
        "fell": sim.fell_at is not None, "fell_at_s": sim.fell_at, "fell_how": sim.fell_how,
        "distance_forward_m": round(forward, 4),
        "drift_left_m": round(float(a[last, 2] - start[1]), 4),
        "speed_mm_s": round(forward / span * 1000.0, 1) if span > 0 else 0.0,
        "crank_turns": {s: round(float(v), 2) for s, v in turns.items()},
        "ideal_distance_m": round(float(ideal), 4),
        "slip_fraction": round(float(1.0 - forward / ideal), 3) if ideal > 1e-6 else None,
        "foot_sliding_m": {s: round(v, 4) for s, v in slip.items()},
        "yaw_change_deg": round(float(np.degrees(yaw[last] - yaw[0])), 1),
        "max_roll_deg": round(float(np.abs(a[up][:, 4]).max()), 2),
        "max_pitch_deg": round(float(np.abs(a[up][:, 5]).max()), 2),
        "max_tilt_deg": round(float(a[up][:, 15].max()), 2),
        "height_range_mm": [round(float(a[up][:, 3].min() * 1000), 1), round(float(a[up][:, 3].max() * 1000), 1)],
        "phase_gap_error_deg": {"mean": round(float(np.mean(phase_gap)), 1), "max_abs": round(float(np.abs(phase_gap).max()), 1)},
        "torque": {"peak_nm": round(float(tq.max()), 3), "mean_nm": round(float(tq.mean()), 3), "stall_nm": limit,
                   "peak_fraction_of_stall": round(float(tq.max() / limit), 2),
                   "running_torque_nm": sim.meta["motor"]["running_torque_nm"],
                   "mean_fraction_of_running": round(float(tq.mean() / sim.meta["motor"]["running_torque_nm"]), 2),
                   "at_speed_limit_fraction_of_time": round(float((tq >= 0.98 * available).mean()), 3)},
        "feet": {"both_fraction": round(float(((fl > 0.2) & (fr > 0.2)).mean()), 3),
                 "one_fraction": round(float(((fl > 0.2) ^ (fr > 0.2)).mean()), 3),
                 "none_fraction": round(float(((fl <= 0.2) & (fr <= 0.2)).mean()), 3)},
    }


def constant(left_rpm: float, right_rpm: float | None = None, ramp_s: float = 0.5, stop_at_s: float | None = None):
    """Both sides at a speed in rpm, ramped up from rest; optional stop."""
    right_rpm = left_rpm if right_rpm is None else right_rpm

    def command(t):
        k = min(1.0, t / ramp_s) if ramp_s > 0 else 1.0
        if stop_at_s is not None and t >= stop_at_s:
            k = 0.0
        return {"left": k * left_rpm * 2 * np.pi / 60.0, "right": k * right_rpm * 2 * np.pi / 60.0}
    return command
