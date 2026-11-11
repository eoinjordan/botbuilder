# SPDX-License-Identifier: MIT
"""The joint command format shared by the simulator and the robot.

One ASCII line per command, newline terminated. Angles are joint angles in
degrees in the robot's convention (see docs/sim-to-real.md), in this order:

    left_hip_roll left_hip_pitch left_knee right_hip_roll right_hip_pitch right_knee

    J <q0> .. <q5>      joint targets          -> OK | OK CLAMP <n> | ERR CLEAR | ERR ...
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

Leg clearance. Per-joint limits cannot keep one leg out of the other: a sole
can be swung into the other sole with every joint inside its own range. The
controller therefore carries a small model of the two legs (boxes around the
thigh and the shin with its sole, robot/clearance.json) and refuses a J
target or a calibration nudge that would bring them together (ERR CLEAR),
and it does not take a tick's step if the step would. legs_clear() is that
test. It uses its own sine so that the Python, C++ and JavaScript copies give
bit for bit the same answer.
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
    clearance: dict | None = None       # robot/clearance.json, or None for no leg clearance rule

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
    clearance_path = Path(joints_path or ROOT / "robot" / "joints.json").with_name("clearance.json")
    clearance = None
    if clearance_path.is_file():
        with open(clearance_path, encoding="utf-8") as handle:
            clearance = json.load(handle)
    return Calibration(joints, raw["pulse"]["min_us"], raw["pulse"]["max_us"], raw["pulse"]["frequency_hz"],
                       raw["soft_start_pin"], float(raw["max_speed_deg_s"]), int(raw["watchdog_ms"]),
                       raw["watchdog_action"], float(raw["calibration_step_max_deg"]),
                       [float(generated["stand_pose_deg"][name]) for name in JOINTS], clearance)


# --- leg clearance ------------------------------------------------------------
# Keep this block operation for operation the same as DuckControl.hpp.

_PI = 3.141592653589793
_S3, _S5, _S7 = -0.16666666666666666, 0.008333333333333333, -0.0001984126984126984
_S9, _S11, _S13 = 2.7557319223985893e-06, -2.505210838544172e-08, 1.6059043836821613e-10


def sine(deg: float) -> float:
    """Sine of an angle in degrees, the same arithmetic everywhere."""
    x = deg * (_PI / 180.0)
    while x > _PI:
        x -= 2.0 * _PI
    while x < -_PI:
        x += 2.0 * _PI
    if x > 0.5 * _PI:
        x = _PI - x
    if x < -0.5 * _PI:
        x = -_PI - x
    x2 = x * x
    return x * (1.0 + x2 * (_S3 + x2 * (_S5 + x2 * (_S7 + x2 * (_S9 + x2 * (_S11 + x2 * _S13))))))


def cosine(deg: float) -> float:
    return sine(deg + 90.0)


def _frame(roll: float, pitch: float) -> list:
    """Rotation about x by roll, then about y by pitch; rows of the matrix."""
    sr, cr, sp, cp = sine(roll), cosine(roll), sine(pitch), cosine(pitch)
    return [[cp, 0.0, sp], [sr * sp, cr, -sr * cp], [-cr * sp, sr, cr * cp]]


def _apply(m: list, v: list) -> list:
    return [m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]]


def _leg(shape: dict, roll: float, pitch: float, knee: float) -> tuple:
    """Frames of the thigh and the shin in the torso frame, mm."""
    o = shape["origins_mm"]
    thigh = _frame(roll, pitch)
    shin = _frame(roll, pitch + knee)
    lifted = _apply(_frame(roll, 0.0), o[1])
    p_thigh = [o[0][0] + lifted[0], o[0][1] + lifted[1], o[0][2] + lifted[2]]
    lowered = _apply(thigh, o[2])
    p_shin = [p_thigh[0] + lowered[0], p_thigh[1] + lowered[1], p_thigh[2] + lowered[2]]
    return thigh, p_thigh, shin, p_shin


def _apart(ra: list, pa: list, a: list, rb: list, pb: list, b: list) -> bool:
    """True when two boxes do not touch. A box is centre (3), half size (3)
    and bounding radius in its link frame; ra, pa and rb, pb are the link
    frames. Separating axis test."""
    ca = _apply(ra, a)
    cb = _apply(rb, b)
    d = [pb[0] + cb[0] - pa[0] - ca[0], pb[1] + cb[1] - pa[1] - ca[1], pb[2] + cb[2] - pa[2] - ca[2]]
    reach = a[6] + b[6]
    if d[0] * d[0] + d[1] * d[1] + d[2] * d[2] > reach * reach:
        return True
    # b's axes and the offset in a's frame
    r = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    f = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    for i in range(3):
        for j in range(3):
            r[i][j] = ra[0][i] * rb[0][j] + ra[1][i] * rb[1][j] + ra[2][i] * rb[2][j]
            f[i][j] = (r[i][j] if r[i][j] >= 0.0 else -r[i][j]) + 1e-9
    t = [ra[0][0] * d[0] + ra[1][0] * d[1] + ra[2][0] * d[2],
         ra[0][1] * d[0] + ra[1][1] * d[1] + ra[2][1] * d[2],
         ra[0][2] * d[0] + ra[1][2] * d[1] + ra[2][2] * d[2]]
    for i in range(3):
        s = t[i] if t[i] >= 0.0 else -t[i]
        if s > a[3 + i] + b[3] * f[i][0] + b[4] * f[i][1] + b[5] * f[i][2]:
            return True
    for j in range(3):
        s = t[0] * r[0][j] + t[1] * r[1][j] + t[2] * r[2][j]
        if s < 0.0:
            s = -s
        if s > a[3] * f[0][j] + a[4] * f[1][j] + a[5] * f[2][j] + b[3 + j]:
            return True
    for i in range(3):
        i1 = (i + 1) % 3
        i2 = (i + 2) % 3
        for j in range(3):
            j1 = (j + 1) % 3
            j2 = (j + 2) % 3
            s = t[i2] * r[i1][j] - t[i1] * r[i2][j]
            if s < 0.0:
                s = -s
            if s > a[3 + i1] * f[i2][j] + a[3 + i2] * f[i1][j] + b[3 + j1] * f[i][j2] + b[3 + j2] * f[i][j1]:
                return True
    return False


_SEEN: dict = {}


def legs_clear(clearance: dict | None, q_deg) -> bool:
    """True when no box of one leg touches a box of the other at joint
    angles q_deg. Shin (with its sole) against shin, and shin against the
    other thigh. Without a table every pose is clear. Answers are remembered
    (a gait repeats its poses); that changes the speed, not the answer."""
    if not clearance:
        return True
    legs = clearance["legs"]
    key = (tuple(legs["left"]["shin"][0]), tuple(legs["right"]["shin"][-1]), len(legs["left"]["shin"]), tuple(q_deg))
    if key not in _SEEN:
        if len(_SEEN) > 50000:
            _SEEN.clear()
        _SEEN[key] = _legs_clear(clearance, q_deg)
    return _SEEN[key]


def _legs_clear(clearance: dict, q_deg) -> bool:
    left, right = clearance["legs"]["left"], clearance["legs"]["right"]
    lt, lpt, ls, lps = _leg(left, q_deg[0], q_deg[1], q_deg[2])
    rt, rpt, rs, rps = _leg(right, q_deg[3], q_deg[4], q_deg[5])
    for a in left["shin"]:
        for b in right["shin"]:
            if not _apart(ls, lps, a, rs, rps, b):
                return False
        for b in right["thigh"]:
            if not _apart(ls, lps, a, rt, rpt, b):
                return False
    for a in left["thigh"]:
        for b in right["shin"]:
            if not _apart(lt, lpt, a, rs, rps, b):
                return False
    return True


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
        nxt = [0.0] * 6
        for i in range(6):
            delta = self.target[i] - self.current[i]
            nxt[i] = self.current[i] + min(max(delta, -step), step)
        # a step that would bring the legs together is not taken
        if legs_clear(self.cal.clearance, nxt):
            self.current = nxt

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
        if not legs_clear(self.cal.clearance, clamped):
            return "ERR CLEAR"
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
        moved = list(self.current)
        moved[i] = (servo - self.zero[i]) / self.cal.joints[i].direction
        if not legs_clear(self.cal.clearance, moved):
            return "ERR CLEAR"
        self.current[i] = moved[i]
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
