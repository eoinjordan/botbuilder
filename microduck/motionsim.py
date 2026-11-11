# SPDX-License-Identifier: MIT
"""MuJoCo emulation for the motion study, with the parts of the command path
and the servo that the first model (microduck/sim.py) left out.

Command lines still go through protocol.Controller, as on the UNO Q. Around it:

  host line -> transport delay -> Controller (20 ms tick, soft limits, rate
  limit) -> pulse rounded to 1 us -> one 50 Hz frame of latency -> servo

The servo is a torque source: nothing inside the dead zone (dead band plus
half the gear play), then proportional up to the published stall torque,
with the published no-load speed through joint damping. A series spring sits
between horn and link. The sum of the estimated servo currents is held to the
supply's rating by scaling all torques. Every value is in config/motion.json.
"""
from __future__ import annotations

import mujoco
import numpy as np

import json

from . import protocol, variant
from .protocol import JOINTS, TICK_MS

FALL_TILT_DEG = 50.0
LOADED_N = 0.05
OFF_FLOOR_M = 0.0005        # a foot counts as off the floor when all of it is this high


class MotionSim:
    def __init__(self, preset="comb", physics: dict | None = None, head: dict | None = None,
                 cal: protocol.Calibration | None = None, mass_scale: float = 1.0):
        xml, self.info = variant.build(preset, physics, head)
        self.preset = preset
        self.xml = xml
        self.phys = self.info["physics"]
        self.model = mujoco.MjModel.from_xml_string(xml)
        if mass_scale != 1.0:
            self.model.body_mass[:] *= mass_scale
            self.model.body_inertia[:] *= mass_scale
        self.data = mujoco.MjData(self.model)
        self.cal = cal or variant.calibration(preset)
        m = self.model
        name2id = lambda kind, name: mujoco.mj_name2id(m, kind, name)   # noqa: E731
        self.torso = name2id(mujoco.mjtObj.mjOBJ_BODY, "torso")
        jid = [name2id(mujoco.mjtObj.mjOBJ_JOINT, j) for j in JOINTS]
        fid = [name2id(mujoco.mjtObj.mjOBJ_JOINT, j + "_flex") for j in JOINTS]
        self.qadr, self.vadr = m.jnt_qposadr[jid], m.jnt_dofadr[jid]
        self.fqadr, self.fvadr = m.jnt_qposadr[fid], m.jnt_dofadr[fid]
        self.steps_per_tick = int(round(TICK_MS / 1000.0 / m.opt.timestep))
        self.limits = m.actuator_ctrlrange[:, 1].copy()
        self.speed_limits = self.limits / m.dof_damping[self.vadr]          # rad/s, no load
        self.kp = self.limits / np.radians(self.phys["full_torque_error_deg"])
        self.dead = np.radians(self.phys["deadband_deg"] + 0.5 * self.phys["backlash_deg"])
        self.damping = m.dof_damping.copy()
        self.frictionloss = m.dof_frictionloss.copy()
        hardware = variant.load_json("hardware.json")
        self.stall_a = np.array([hardware["servos"]["SR311" if j.endswith("knee") else "SR431"]["assumed"]["stall_current_a"]["value"]
                                 for j in JOINTS])
        self.supply_a = float(self.phys["supply_current_a"])
        self.floor = name2id(mujoco.mjtObj.mjOBJ_GEOM, "floor")
        # feet: the boxes of the underside (for clearance); soles: every box of the sole (for load)
        self.feet = {side: [name2id(mujoco.mjtObj.mjOBJ_GEOM, g) for g in names]
                     for side, names in self.info["foot_geoms"].items()}
        self.soles = {side: [name2id(mujoco.mjtObj.mjOBJ_GEOM, g) for g in names]
                      for side, names in self.info["sole_geoms"].items()}
        self.geom_kind = self._classify()
        self.mesh = None            # an object with overlap_mm3(q_deg) for the exact leg meshes, if attached
        self.mass = float(m.body_subtreemass[self.torso])
        self.set_floor_friction(self.phys["floor_friction"])
        self.reset()

    # -- model facts --
    def _classify(self) -> dict:
        """What each collision geom is, for contact reports."""
        m, out = self.model, {}
        with open(variant.ROOT / "robot" / "model.json", encoding="utf-8") as handle:
            links = {link["name"]: [s["kind"] for s in link["shapes"]] for link in json.load(handle)["links"]}
        named = {"board": "controller board", "shield": "shield", "battery": "battery", "display": "display", "camera": "camera"}
        for g in range(m.ngeom):
            if g == self.floor or m.geom_contype[g] == 0:
                continue
            body = m.body(m.geom_bodyid[g]).name
            name = m.geom(g).name
            if any(g in ids for ids in self.soles.values()):
                kind = "sole"
            else:
                generated = links[body][int(name.rsplit("_", 1)[1])]
                if generated in named:
                    kind = named[generated]
                elif generated == "servo":
                    kind = {"torso": "hip roll servo", "left_hip": "hip pitch servo", "right_hip": "hip pitch servo"}.get(body, "knee servo")
                elif body == "torso":
                    top = m.geom_pos[g][2] + m.geom_size[g][2]
                    kind = "head and camera mount" if top > 0.012 else ("deck" if m.geom_pos[g][2] > 0 else "hip cradle")
                else:
                    kind = {"hip": "yoke", "thigh": "thigh plate", "shin": "shin plate"}[body.split("_")[1]]
            out[g] = kind
        return out

    def set_floor_friction(self, mu: float) -> None:
        self.model.geom_friction[:, 0] = mu

    # -- state --
    def reset(self, pose_deg=None, tilt_deg=(0.0, 0.0), push_m_s=(0.0, 0.0), enable: bool = True) -> None:
        """Put the robot on the floor at a pose (default: stand), the servos
        commanded there. tilt_deg (roll, pitch) and push_m_s (x, y) perturb
        the initial state."""
        m, d = self.model, self.data
        pose = list(self.cal.stand_deg if pose_deg is None else pose_deg)
        mujoco.mj_resetData(m, d)
        d.qpos[self.qadr] = np.radians(pose)
        roll, pitch = np.radians(tilt_deg)
        quat = np.zeros(4)
        mujoco.mju_euler2Quat(quat, np.array([roll, pitch, 0.0]), "xyz")
        d.qpos[3:7] = quat
        d.qpos[2] = 1.0
        mujoco.mj_forward(m, d)
        low = min(self._distance(g) for g in self.geom_kind)
        d.qpos[2] -= low
        d.qvel[0:2] = push_m_s
        mujoco.mj_forward(m, d)
        self.controller = protocol.Controller(self.cal)
        self.controller.current = list(pose)
        self.controller.target = list(pose)
        self.now_ms = 0
        self.queue = []
        self.target = np.radians(pose)
        self.frame = np.radians(pose)
        self.fell_at = self.fell_how = None
        self.start_height = float(d.xpos[self.torso][2])
        self.peak_current_a = 0.0
        self.current_limited_steps = 0
        self.steps = 0
        self.model.dof_frictionloss[:] = self.frictionloss
        if enable:
            self.controller.handle("E", 0)

    def _distance(self, geom: int) -> float:
        return float(mujoco.mj_geomDistance(self.model, self.data, geom, self.floor, 10.0, None))

    def joint_deg(self) -> np.ndarray:
        """Link angles: servo angle plus the deflection of the series spring."""
        return np.degrees(self.data.qpos[self.qadr] + self.data.qpos[self.fqadr])

    def servo_deg(self) -> np.ndarray:
        return np.degrees(self.data.qpos[self.qadr])

    def joint_speed_deg_s(self) -> np.ndarray:
        return np.degrees(self.data.qvel[self.vadr])

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.torso].reshape(3, 3)[:, 2]
        return float(np.degrees(np.arccos(np.clip(up[2], -1.0, 1.0))))

    def yaw_deg(self) -> float:
        r = self.data.xmat[self.torso].reshape(3, 3)
        return float(np.degrees(np.arctan2(r[1, 0], r[0, 0])))

    def pitch_deg(self) -> float:
        r = self.data.xmat[self.torso].reshape(3, 3)
        return float(np.degrees(np.arcsin(np.clip(-r[2, 0], -1.0, 1.0))))

    def com(self) -> np.ndarray:
        return self.data.subtree_com[self.torso].copy()

    # -- the command path --
    def send(self, line: str, delayed: bool = True) -> None:
        """A host line; it reaches the controller after the transport delay."""
        self.queue.append((self.now_ms + (self.phys["transport_delay_ms"] if delayed else 0), line))

    def tick(self) -> None:
        """Advance 20 ms."""
        m, d = self.model, self.data
        self.now_ms += TICK_MS
        # this call covers the 20 ms that end at now_ms; a line is acted on by
        # the first controller tick after it has arrived
        while self.queue and self.queue[0][0] <= self.now_ms - TICK_MS:
            self.controller.handle(self.queue.pop(0)[1], self.now_ms)
        self.controller.tick(self.now_ms)
        relaxed = self.controller.mode == protocol.RELAX
        if relaxed:
            m.dof_damping[self.vadr] = 0.0
        else:
            m.dof_damping[self.vadr] = self.damping[self.vadr]
            # the frame the servo acts on now is the one set a frame ago
            self.target = self.frame
            cal = self.cal
            pulses = [cal.pulse_us(s) for s in self.controller.servo_deg()]
            angle = [(p - cal.min_us) * 180.0 / (cal.max_us - cal.min_us) for p in pulses]
            self.frame = np.radians([(a - z) / j.direction for a, z, j in zip(angle, self.controller.zero, cal.joints)])
            if self.phys["pwm_latency_ms"] < TICK_MS:
                self.target = self.frame
        for _ in range(self.steps_per_tick):
            if relaxed:
                d.ctrl[:] = 0.0
            else:
                error = self.target - d.qpos[self.qadr]
                drive = np.sign(error) * np.maximum(np.abs(error) - self.dead, 0.0)
                torque = np.clip(self.kp * drive, -self.limits, self.limits)
                # motor current: proportional to the torque the motor makes,
                # which is the drive less the back-EMF term
                current = float(np.sum(self.stall_a * np.abs(torque - self.damping[self.vadr] * d.qvel[self.vadr]) / self.limits))
                self.peak_current_a = max(self.peak_current_a, current)
                if current > self.supply_a:
                    torque *= self.supply_a / current
                    self.current_limited_steps += 1
                d.ctrl[:] = torque
            mujoco.mj_step(m, d)
            self.steps += 1
        if self.fell_at is None:
            if self.tilt_deg() > FALL_TILT_DEG:
                self.fell_at = self.now_ms / 1000.0
                up = d.xmat[self.torso].reshape(3, 3)[:, 2]
                if abs(up[0]) >= abs(up[1]):
                    self.fell_how = "forward" if up[0] > 0 else "backward"
                else:
                    self.fell_how = "to the left" if up[1] > 0 else "to the right"

    # -- measurements --
    def contacts(self) -> dict:
        """Normal force on the floor by kind of part (N), and per foot."""
        d, m = self.data, self.model
        kinds, feet, parts = {}, {"left": 0.0, "right": 0.0}, {}
        wrench = np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            mujoco.mj_contactForce(m, d, i, wrench)
            if wrench[0] <= 0.0:
                continue
            if c.geom1 == self.floor:
                other = c.geom2
            elif c.geom2 == self.floor:
                other = c.geom1
            else:
                # one part of the robot pressing on another
                pair = " on ".join(sorted((self._where(c.geom1), self._where(c.geom2))))
                parts[pair] = parts.get(pair, 0.0) + float(wrench[0])
                continue
            kind = self.geom_kind.get(other, "other")
            kinds[kind] = kinds.get(kind, 0.0) + float(wrench[0])
            for side, ids in self.soles.items():
                if other in ids:
                    feet[side] += float(wrench[0])
        return {"by_kind": kinds, "feet": feet, "part_on_part": parts}

    def _where(self, geom: int) -> str:
        body = self.model.body(self.model.geom_bodyid[geom]).name
        kind = self.geom_kind.get(geom, "part")
        return kind if body == "torso" else f"{body.split('_')[0]} {kind}"

    def foot_clearance(self) -> dict:
        """Height of the lowest point of each sole above the floor (m)."""
        return {side: min(self._distance(g) for g in ids) for side, ids in self.feet.items()}

    def foot_xy(self) -> dict:
        out = {}
        for side, ids in self.feet.items():
            body = self.model.geom_bodyid[ids[0]]
            out[side] = self.data.xpos[body][:2].copy()
        return out

    def lowest_by_kind(self) -> dict:
        out = {}
        for g, kind in self.geom_kind.items():
            out[kind] = min(out.get(kind, 10.0), self._distance(g))
        return out


def run(sim: MotionSim, trajectory: list, on_tick=None, tail_s: float = 0.0, relax_at_ms: int | None = None) -> dict:
    """Play a trajectory through the command path and log every tick.
    Returns arrays keyed by name; t is in seconds."""
    index = 0
    end_ms = trajectory[-1][0] + int(tail_s * 1000)
    keys = ("t", "pos", "com", "tilt", "yaw", "pitch", "torque", "speed", "joint", "servo", "command",
            "force_left", "force_right", "clear_left", "clear_right", "foot_left", "foot_right", "current", "force_total")
    log = {k: [] for k in keys}
    kinds, parts = {}, {}
    relaxed = False
    while sim.now_ms < end_ms:
        while index < len(trajectory) and trajectory[index][0] <= sim.now_ms:
            sim.send(protocol.format_joints(trajectory[index][1]))
            index += 1
        if relax_at_ms is not None and not relaxed and sim.now_ms >= relax_at_ms:
            sim.send("R")
            relaxed = True
        before = sim.peak_current_a
        sim.peak_current_a = 0.0
        sim.tick()
        tick_current = sim.peak_current_a
        sim.peak_current_a = max(before, tick_current)
        c = sim.contacts()
        clear = sim.foot_clearance()
        xy = sim.foot_xy()
        for kind, force in c["by_kind"].items():
            kinds.setdefault(kind, []).append((sim.now_ms / 1000.0, force))
        for pair, force in c["part_on_part"].items():
            parts.setdefault(pair, []).append((sim.now_ms / 1000.0, force))
        row = (sim.now_ms / 1000.0, sim.data.xpos[sim.torso].copy(), sim.com(), sim.tilt_deg(), sim.yaw_deg(), sim.pitch_deg(),
               sim.data.actuator_force.copy(), sim.joint_speed_deg_s(), sim.joint_deg(), sim.servo_deg(),
               np.array(sim.controller.current), c["feet"]["left"], c["feet"]["right"], clear["left"], clear["right"],
               xy["left"], xy["right"], tick_current, sum(c["by_kind"].values()))
        for k, v in zip(keys, row):
            log[k].append(v)
        if on_tick:
            on_tick(sim)
    out = {k: np.array(v) for k, v in log.items()}
    out["contact_kinds"] = kinds
    # Leg against leg, from the joint angles the simulation reached. "near":
    # the boxes of the leg clearance rule (which carry its margin) touch.
    # With the exact meshes attached, a near tick is checked on them and
    # only a real overlap counts; without them every near tick counts.
    table = sim.cal.clearance
    near = np.zeros(len(out["t"]), bool)
    if table is not None:
        for i, q in enumerate(out["joint"]):
            near[i] = not protocol.legs_clear(table, [round(float(v), 1) for v in q])
    out["near"] = near
    for i in np.flatnonzero(near):
        if sim.mesh is None:
            parts.setdefault("legs within the clearance margin", []).append((float(out["t"][i]), 0.0))
        else:
            volume = sim.mesh.overlap_mm3([round(float(v), 1) for v in out["joint"][i]])
            if volume > 0.5:
                parts.setdefault("left leg on right leg", []).append((float(out["t"][i]), round(volume, 1)))
    out["part_on_part"] = parts
    out["fell_at"], out["fell_how"] = sim.fell_at, sim.fell_how
    out["current_limited_fraction"] = sim.current_limited_steps / max(sim.steps, 1)
    return out


def demand(sim: MotionSim, log: dict, t0: float = 0.0) -> dict:
    """Peak torque and speed of each joint against the servo's limits."""
    window = log["t"] >= t0
    out = {}
    for i, joint in enumerate(JOINTS):
        torque = np.abs(log["torque"][window, i])
        speed = np.abs(log["speed"][window, i])
        limit_speed = float(np.degrees(sim.speed_limits[i]))
        out[joint] = {"peak_torque_nm": round(float(torque.max()), 3), "torque_limit_nm": round(float(sim.limits[i]), 3),
                      "peak_torque_fraction": round(float(torque.max() / sim.limits[i]), 3),
                      "time_at_torque_limit_fraction": round(float((torque >= 0.98 * sim.limits[i]).mean()), 3),
                      "peak_speed_deg_s": round(float(speed.max()), 1), "speed_limit_deg_s": round(limit_speed, 1),
                      "peak_speed_fraction": round(float(speed.max() / limit_speed), 3)}
    return out


def stepping(log: dict, t0: float, t1: float | None = None) -> dict:
    """What the feet did between t0 and t1: support fractions, and each swing
    (a stretch with one foot wholly off the floor while the other carries
    load) with its clearance, duration and how far the foot moved."""
    t = log["t"]
    upright_until = log["fell_at"] if log["fell_at"] is not None else t[-1] + 1.0
    window = (t >= t0) & (t <= (t1 if t1 is not None else t[-1])) & (t < upright_until)
    if window.sum() < 2:
        return {"single_support_fraction": 0.0, "double_support_fraction": 0.0, "flight_fraction": 0.0, "swings": [],
                "steps": 0, "alternating": False, "median_clearance_mm": 0.0, "median_swing_s": 0.0,
                "stance_slip_mm_per_step": 0.0, "step_length_mm": 0.0}
    fl, fr = log["force_left"][window], log["force_right"][window]
    cl, cr = log["clear_left"][window], log["clear_right"][window]
    tw = t[window]
    yaw = np.radians(log["yaw"][window])
    heading = np.c_[np.cos(yaw), np.sin(yaw)]
    left_on, right_on = fl > LOADED_N, fr > LOADED_N
    swings = []
    for side, off, other_on, clear, foot, other_foot in (
            ("left", cl > OFF_FLOOR_M, right_on, cl, log["foot_left"][window], log["foot_right"][window]),
            ("right", cr > OFF_FLOOR_M, left_on, cr, log["foot_right"][window], log["foot_left"][window])):
        swing = off & other_on
        edges = np.flatnonzero(np.diff(np.r_[0, swing.astype(int), 0]))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a < 2:
                continue
            move = foot[b - 1] - foot[a]
            slip = other_foot[b - 1] - other_foot[a]
            swings.append({"side": side, "start_s": round(float(tw[a]), 2), "duration_s": round(float(tw[b - 1] - tw[a] + TICK_MS / 1000.0), 2),
                           "clearance_mm": round(float(clear[a:b].max() * 1000.0), 2),
                           "forward_mm": round(float(move @ heading[a] * 1000.0), 2),
                           "stance_slip_mm": round(float(np.linalg.norm(slip) * 1000.0), 2)})
    swings.sort(key=lambda s: s["start_s"])
    real = [s for s in swings if s["clearance_mm"] >= 1.0 and s["duration_s"] >= 0.06]
    order = [s["side"] for s in real]
    alternating = len(order) >= 4 and sum(a != b for a, b in zip(order, order[1:])) >= 0.8 * (len(order) - 1)
    med = lambda values: round(float(np.median(values)), 2) if len(values) else 0.0   # noqa: E731
    return {"single_support_fraction": round(float((left_on ^ right_on).mean()), 3),
            "double_support_fraction": round(float((left_on & right_on).mean()), 3),
            "flight_fraction": round(float((~left_on & ~right_on).mean()), 3),
            "steps": len(real), "alternating": bool(alternating),
            "median_clearance_mm": med([s["clearance_mm"] for s in real]),
            "median_swing_s": med([s["duration_s"] for s in real]),
            "step_length_mm": med([s["forward_mm"] for s in real]),
            "stance_slip_mm_per_step": med([s["stance_slip_mm"] for s in real]),
            "swings": swings}
