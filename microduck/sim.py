# SPDX-License-Identifier: MIT
"""MuJoCo emulation of the robot behind the same command lines the firmware
takes.

DuckSim owns a MuJoCo model (robot/microduck.xml) and a protocol.Controller.
Command lines go to the controller exactly as they would go to the UNO Q; each
20 ms tick the controller's commanded joint angles become the position targets
of the simulated servos. Torque and speed limits are in the model.
"""
from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np

from . import protocol
from .protocol import JOINTS, ROOT, TICK_MS

FALL_TILT_DEG = 45.0
FALL_HEIGHT_FRACTION = 0.6


class DuckSim:
    def __init__(self, xml: Path | None = None, cal: protocol.Calibration | None = None, mount_error_deg=None):
        self.model = mujoco.MjModel.from_xml_path(str(xml or ROOT / "robot" / "microduck.xml"))
        self.data = mujoco.MjData(self.model)
        self.cal = cal or protocol.load_calibration()
        self.controller = protocol.Controller(self.cal)
        # Where each horn really sits: the table's zero plus a mounting error
        # the controller does not know about (zero unless a test injects one).
        self.true_zero = [j.zero_deg + e for j, e in zip(self.cal.joints, mount_error_deg or [0.0] * 6)]
        self.torso = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "torso")
        self.qadr = [self.model.jnt_qposadr[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, j)] for j in JOINTS]
        self.steps_per_tick = int(round(TICK_MS / 1000.0 / self.model.opt.timestep))
        self.limits = self.model.actuator_forcerange[:, 1].copy()
        self.kp = self.model.actuator_gainprm[:, 0].copy()
        self.damping = self.model.dof_damping.copy()
        self.floor = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.feet = {}
        for side in ("left", "right"):
            body = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"{side}_shin")
            geoms = [g for g in range(self.model.ngeom) if self.model.geom_bodyid[g] == body
                     and self.model.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX]
            self.feet[side] = (body, min(geoms, key=lambda g: self.model.geom_pos[g][2]))
        self.reset("stand")

    # -- state --
    def reset(self, pose: str = "stand") -> None:
        key = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, pose)
        mujoco.mj_resetDataKeyframe(self.model, self.data, key)
        mujoco.mj_forward(self.model, self.data)
        self.controller = protocol.Controller(self.cal)
        self.controller.current = [float(np.degrees(self.data.qpos[a])) for a in self.qadr]
        self.controller.target = list(self.controller.current)
        self.start_height = float(self.data.xpos[self.torso][2])
        self.now_ms = 0
        self.fell_at = None
        self.fell_how = None

    def joint_deg(self) -> list:
        return [float(np.degrees(self.data.qpos[a])) for a in self.qadr]

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.torso].reshape(3, 3)[:, 2]
        return float(np.degrees(np.arccos(np.clip(up[2], -1.0, 1.0))))

    def torso_pos(self) -> np.ndarray:
        return self.data.xpos[self.torso].copy()

    # -- the command interface --
    def send(self, line: str) -> str:
        return self.controller.handle(line, self.now_ms)

    def tick(self) -> None:
        """Advance 20 ms: one controller tick, then physics."""
        self.now_ms += TICK_MS
        self.controller.tick(self.now_ms)
        if self.controller.mode == protocol.RELAX:
            # No pulses: no drive and no back-EMF braking, gear friction only.
            self.model.actuator_gainprm[:, 0] = 0.0
            self.model.actuator_biasprm[:, 1] = 0.0
            self.model.dof_damping[:] = 0.0
        else:
            self.model.actuator_gainprm[:, 0] = self.kp
            self.model.actuator_biasprm[:, 1] = -self.kp
            self.model.dof_damping[:] = self.damping
            # The controller's output is a servo angle; the mechanism turns
            # that into a joint angle through the real horn position.
            servo = self.controller.servo_deg()
            self.data.ctrl[:] = np.radians([(a - z) / j.direction for a, z, j in zip(servo, self.true_zero, self.cal.joints)])
        for _ in range(self.steps_per_tick):
            mujoco.mj_step(self.model, self.data)
        if self.fell_at is None:
            height = float(self.data.xpos[self.torso][2])
            if self.tilt_deg() > FALL_TILT_DEG or height < FALL_HEIGHT_FRACTION * self.start_height:
                self.fell_at = self.now_ms / 1000.0
                up = self.data.xmat[self.torso].reshape(3, 3)[:, 2]
                if abs(up[0]) >= abs(up[1]):
                    self.fell_how = "forward" if up[0] > 0 else "backward"
                else:
                    self.fell_how = "to the left" if up[1] > 0 else "to the right"

    def torques(self) -> np.ndarray:
        return self.data.actuator_force.copy()

    def foot_state(self) -> dict:
        """Normal force on each foot (N) and the height of its lowest sole
        corner above the floor (m)."""
        force = {"left": 0.0, "right": 0.0}
        wrench = np.zeros(6)
        for i in range(self.data.ncon):
            contact = self.data.contact[i]
            if self.floor not in (contact.geom1, contact.geom2):
                continue
            other = contact.geom2 if contact.geom1 == self.floor else contact.geom1
            for side, (body, _) in self.feet.items():
                if self.model.geom_bodyid[other] == body:
                    mujoco.mj_contactForce(self.model, self.data, i, wrench)
                    force[side] += float(wrench[0])
        height = {}
        for side, (_, geom) in self.feet.items():
            size = self.model.geom_size[geom]
            corners = np.array([[sx * size[0], sy * size[1], -size[2]] for sx in (-1, 1) for sy in (-1, 1)])
            world = self.data.geom_xpos[geom] + corners @ self.data.geom_xmat[geom].reshape(3, 3).T
            height[side] = float(world[:, 2].min())
        return {"force_n": force, "lowest_corner_m": height}

    def set_floor_friction(self, mu: float) -> None:
        self.model.geom_friction[:, 0] = mu


def play(sim: DuckSim, trajectory: list, on_tick=None) -> dict:
    """Send a trajectory through the command interface and log what happens."""
    assert sim.send("E") == "OK"
    start = sim.torso_pos()
    index, log, clamps = 0, [], 0
    end_ms = trajectory[-1][0]
    while sim.now_ms < end_ms:
        while index < len(trajectory) and trajectory[index][0] <= sim.now_ms:
            reply = sim.send(protocol.format_joints(trajectory[index][1]))
            clamps += reply.startswith("OK CLAMP")
            index += 1
        sim.tick()
        log.append((sim.now_ms / 1000.0, sim.torso_pos(), sim.tilt_deg(), sim.torques(), sim.joint_deg(), sim.foot_state()))
        if on_tick:
            on_tick(sim)
    return summarise(sim, log, start, clamps)


def summarise(sim: DuckSim, log: list, start, clamps: int = 0, settle_s: float = 1.0) -> dict:
    t = np.array([row[0] for row in log])
    pos = np.array([row[1] for row in log])
    tilt = np.array([row[2] for row in log])
    torque = np.abs(np.array([row[3] for row in log]))
    upright = t <= (sim.fell_at if sim.fell_at is not None else t[-1])
    window = upright & (t >= min(settle_s, t[-1] / 2))
    if not window.any():
        window = upright
    last = np.nonzero(upright)[0][-1]
    left = np.array([row[5]["force_n"]["left"] for row in log])[upright]
    right = np.array([row[5]["force_n"]["right"] for row in log])[upright]
    high = {side: np.array([max(0.0, row[5]["lowest_corner_m"][side]) for row in log])[upright] for side in ("left", "right")}
    return {
        "duration_s": round(float(t[-1]), 2),
        "fell": sim.fell_at is not None,
        "fell_at_s": sim.fell_at,
        "fell_how": sim.fell_how,
        "upright_s": round(float(sim.fell_at if sim.fell_at is not None else t[-1]), 2),
        "distance_forward_m": round(float(pos[last][0] - start[0]), 4),
        "drift_left_m": round(float(pos[last][1] - start[1]), 4),
        "max_tilt_deg_while_upright": round(float(tilt[upright].max()), 2),
        "final_tilt_deg": round(float(tilt[-1]), 2),
        "clamped_commands": int(clamps),
        "feet": {"both_loaded_fraction": round(float(((left > 0.05) & (right > 0.05)).mean()), 3),
                 "single_support_fraction": round(float(((left > 0.05) ^ (right > 0.05)).mean()), 3),
                 "airborne_fraction": round(float(((left <= 0.05) & (right <= 0.05)).mean()), 3),
                 "max_whole_sole_lift_mm": {side: round(float(high[side].max() * 1000.0), 2) for side in ("left", "right")}},
        "torque": {joint: {"mean_nm": round(float(torque[window, i].mean()), 4),
                           "peak_nm": round(float(torque[window, i].max()), 4),
                           "limit_nm": round(float(sim.limits[i]), 4),
                           "peak_fraction_of_limit": round(float(torque[window, i].max() / sim.limits[i]), 3),
                           "saturated_fraction_of_time": round(float((torque[window, i] >= 0.999 * sim.limits[i]).mean()), 3)}
                   for i, joint in enumerate(JOINTS)},
    }
