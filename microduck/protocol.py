# SPDX-License-Identifier: MIT
"""The joint command format shared by the simulator and the robot.

One ASCII line per command, newline terminated. Angles are joint angles in
degrees in the robot's convention (see docs/sim-to-real.md), in this order:

    left_hip_roll left_hip_pitch left_knee right_hip_roll right_hip_pitch right_knee

    J <q0> .. <q5>      joint targets          -> OK | OK CLAMP <n> | ERR ...
    E                   enable (soft start)    -> OK
    R                   relax (no pulses)      -> OK
    S                   status                 -> STAT mode=.. age_ms=.. q=..
    W <ms> <hold|relax> watchdog               -> OK
    C <index>           calibrate one joint    -> OK
    N <delta>           nudge it, servo deg    -> CAL <index> servo=.. pulse=..
    Z                   take this as its zero  -> ZERO <index> <servo_deg>
    X                   leave calibration      -> OK

Controller below is the reference implementation of what the firmware does
with those lines (firmware/microduck_agent/sketch/DuckControl.hpp is the same
logic in C++). The simulator drives MuJoCo through it, so soft limits, the
speed limit and the watchdog behave the same in simulation and on the robot.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOINTS = ["left_hip_roll", "left_hip_pitch", "left_knee",
          "right_hip_roll", "right_hip_pitch", "right_knee"]
TICK_MS = 20
RELAX, RUN, HOLD, CAL = "RELAX", "RUN", "HOLD", "CAL"
_NUMBER = re.compile(r"[-+]?[0-9]{1,6}(\.[0-9]{0,6})?")


@dataclass
class JointCal:
    name: str
    servo: str
    channel: str
    pin: int
    zero_deg: float
    direction: int
    min_deg: float
    max_deg: float

    def to_servo(self, joint_deg: float) -> float:
        return self.zero_deg + self.direction * joint_deg

    def to_joint(self, servo_deg: float) -> float:
        return (servo_deg - self.zero_deg) / self.direction

    def clamp(self, joint_deg: float) -> float:
        return min(max(joint_deg, self.min_deg), self.max_deg)


@dataclass
class Calibration:
    joints: list
    min_us: int = 500
    max_us: int = 2500
    frequency_hz: int = 50
    soft_start_pin: int = 12
    max_speed_deg_s: float = 120.0
    watchdog_ms: int = 500
    watchdog_action: str = "hold"
    step_max_deg: float = 2.0
    stand_deg: list = field(default_factory=lambda: [0.0] * 6)

    def pulse_us(self, servo_deg: float) -> int:
        bounded = min(max(servo_deg, 0.0), 180.0)
        return int(self.min_us + bounded * (self.max_us - self.min_us) / 180.0 + 0.5)

    def servo_deg(self, q_deg) -> list:
        return [j.to_servo(q) for j, q in zip(self.joints, q_deg)]

    def joint_deg(self, servo_deg) -> list:
        return [j.to_joint(s) for j, s in zip(self.joints, servo_deg)]

    def clamp(self, q_deg) -> list:
        return [j.clamp(q) for j, q in zip(self.joints, q_deg)]


def load_calibration(calibration_path: Path | None = None, joints_path: Path | None = None) -> Calibration:
    """Merge the hand-edited calibration with the generated joint limits."""
    with open(calibration_path or ROOT / "config" / "calibration.json", encoding="utf-8") as handle:
        raw = json.load(handle)
    with open(joints_path or ROOT / "robot" / "joints.json", encoding="utf-8") as handle:
        generated = json.load(handle)
    by_name = {j["name"]: j for j in raw["joints"]}
    joints = []
    for name in JOINTS:
        j, g = by_name[name], generated["joints"][name]
        if j["direction"] not in (1, -1):
            raise ValueError(f"{name}: direction must be 1 or -1")
        joints.append(JointCal(name, j["servo"], j["channel"], int(j["pin"]), float(j["zero_deg"]),
                               int(j["direction"]), float(g["min_deg"]), float(g["max_deg"])))
    if len({j.pin for j in joints}) != 6:
        raise ValueError("two joints share a pin")
    return Calibration(joints, raw["pulse"]["min_us"], raw["pulse"]["max_us"], raw["pulse"]["frequency_hz"],
                       raw["soft_start_pin"], float(raw["max_speed_deg_s"]), int(raw["watchdog_ms"]),
                       raw["watchdog_action"], float(raw["calibration_step_max_deg"]),
                       [float(generated["stand_pose_deg"][name]) for name in JOINTS])


def fmt1(value: float) -> str:
    """One decimal, half away from zero, no negative zero. The firmware
    formats the same way, so replies match character for character."""
    tenths = int(abs(value) * 10.0 + 0.5)
    sign = "-" if value < 0 and tenths else ""
    return f"{sign}{tenths // 10}.{tenths % 10}"


def parse_number(token: str) -> float:
    """Strict decimal: optional sign, digits, optional point and digits.
    No exponents, no inf or nan. Raises ValueError otherwise."""
    if not _NUMBER.fullmatch(token):
        raise ValueError(token)
    return float(token)


def format_joints(q_deg) -> str:
    """A J line. Tenths of a degree, as the sketchbot streams its arm."""
    if len(q_deg) != 6:
        raise ValueError("six joint angles expected")
    return "J " + " ".join(fmt1(q) for q in q_deg) + "\n"


def parse_joints(line: str) -> list:
    parts = line.split()
    if len(parts) != 7 or parts[0] != "J":
        raise ValueError("not a J line")
    return [parse_number(p) for p in parts[1:]]


class Controller:
    """What the firmware does with command lines, tick by tick."""

    def __init__(self, cal: Calibration):
        self.cal = cal
        self.mode = RELAX
        self.current = list(cal.stand_deg)      # commanded joint angles
        self.target = list(cal.stand_deg)
        self.zero = [j.zero_deg for j in cal.joints]
        self.last_cmd_ms = 0
        self.watchdog_ms = cal.watchdog_ms
        self.watchdog_relax = cal.watchdog_action == "relax"
        self.armed = False
        self.cal_index = -1

    # -- outputs --
    def servo_deg(self) -> list:
        return [min(max(z + j.direction * q, 0.0), 180.0)
                for z, j, q in zip(self.zero, self.cal.joints, self.current)]

    def pulses_us(self) -> list:
        """Pulse width per joint, or 0 for no pulse."""
        if self.mode == RELAX:
            return [0] * 6
        return [self.cal.pulse_us(s) for s in self.servo_deg()]

    # -- time --
    def tick(self, now_ms: int) -> None:
        if self.mode == RUN and self.armed and now_ms - self.last_cmd_ms > self.watchdog_ms:
            if self.watchdog_relax:
                self.mode = RELAX
            else:
                self.mode = HOLD
                self.target = list(self.current)
            self.armed = False
        if self.mode != RUN:
            return
        step = self.cal.max_speed_deg_s * TICK_MS / 1000.0
        for i in range(6):
            delta = self.target[i] - self.current[i]
            self.current[i] += min(max(delta, -step), step)

    # -- commands --
    def handle(self, line: str, now_ms: int) -> str:
        parts = line.split()
        if not parts:
            return "ERR EMPTY"
        cmd, args = parts[0], parts[1:]
        arity = {"J": 6, "E": 0, "R": 0, "S": 0, "W": 2, "C": 1, "N": 1, "Z": 0, "X": 0}
        if cmd not in arity:
            return "ERR UNKNOWN"
        if len(args) != arity[cmd]:
            return "ERR ARGS"
        try:
            return getattr(self, "_cmd_" + cmd)(args, now_ms)
        except ValueError:
            return "ERR ARGS"

    def _cmd_J(self, args, now_ms):
        values = [parse_number(a) for a in args]
        if any(abs(v) > 1000.0 for v in values):
            return "ERR ARGS"
        if self.mode == RELAX:
            return "ERR DISABLED"
        if self.mode == CAL:
            return "ERR CAL"
        clamped = self.cal.clamp(values)
        count = sum(1 for a, b in zip(values, clamped) if a != b)
        self.target = clamped
        self.mode, self.armed, self.last_cmd_ms = RUN, True, now_ms
        return f"OK CLAMP {count}" if count else "OK"

    def _cmd_E(self, args, now_ms):
        if self.mode == RELAX:
            self.target = list(self.current)
            self.mode, self.armed = RUN, False
        return "OK"

    def _cmd_R(self, args, now_ms):
        self.mode, self.armed, self.cal_index = RELAX, False, -1
        return "OK"

    def _cmd_S(self, args, now_ms):
        q = ",".join(fmt1(v) for v in self.current)
        return f"STAT mode={self.mode} age_ms={now_ms - self.last_cmd_ms} wd={self.watchdog_ms} q={q}"

    def _cmd_W(self, args, now_ms):
        if not args[0].isdigit() or len(args[0]) > 6 or args[1] not in ("hold", "relax"):
            return "ERR ARGS"
        value = int(args[0])
        if value < 100 or value > 10000:
            return "ERR ARGS"
        self.watchdog_ms, self.watchdog_relax = value, args[1] == "relax"
        return "OK"

    def _cmd_C(self, args, now_ms):
        if args[0] not in ("0", "1", "2", "3", "4", "5"):
            return "ERR ARGS"
        if self.mode == RELAX:
            return "ERR DISABLED"
        self.target = list(self.current)
        self.mode, self.armed, self.cal_index = CAL, False, int(args[0])
        return "OK"

    def _cal_servo(self, delta: float) -> float:
        i = self.cal_index
        joint = self.cal.joints[i]
        return min(max(self.zero[i] + joint.direction * self.current[i] + delta, 0.0), 180.0)

    def _cmd_N(self, args, now_ms):
        delta = parse_number(args[0])
        if self.mode != CAL:
            return "ERR NOT CAL"
        if abs(delta) > self.cal.step_max_deg:
            return "ERR STEP"
        i = self.cal_index
        servo = self._cal_servo(delta)
        self.current[i] = (servo - self.zero[i]) / self.cal.joints[i].direction
        self.target[i] = self.current[i]
        return f"CAL {i} servo={fmt1(servo)} pulse={self.cal.pulse_us(servo)}"

    def _cmd_Z(self, args, now_ms):
        if self.mode != CAL:
            return "ERR NOT CAL"
        i = self.cal_index
        servo = self._cal_servo(0.0)
        self.zero[i] = servo
        self.current[i] = self.target[i] = 0.0
        return f"ZERO {i} {fmt1(servo)}"

    def _cmd_X(self, args, now_ms):
        if self.mode == CAL:
            self.mode, self.cal_index = HOLD, -1
        return "OK"
