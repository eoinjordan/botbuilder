# SPDX-License-Identifier: MIT
"""Open-loop motions for the motion study: the walking gait with forward and
turn inputs, a jump, and keyframe motions (sit, stand up).

The gait is the one of microduck/gait.py and config/gait.json (sway, step,
lift), with the two inputs the control page sends: forward scales the step of
both legs, turn is the difference in step scale between them (left step
scaled by forward minus turn, right by forward plus turn, each clipped to
-1..1). Roll and lift are not scaled. walk_pose() is that formula; anything
that plays the gait from its parameter file gets the motion tested here.

A trajectory is the repository's joint-command format: (t_ms, six joint
angles in degrees) at 50 Hz in the order of protocol.JOINTS. Every generator
ends with rate_limit(), so what is written to a file is what the firmware
will play: nothing in it asks for more than the speed limit it was made for.
"""
from __future__ import annotations

import math

from .protocol import TICK_MS

# name, lower bound, upper bound. Angles in degrees.
GAIT_SPACE = [
    ("period_s", 0.50, 2.00),
    ("roll_amplitude_deg", 0.0, 14.0),       # both hips rolled the same way, sine
    ("step_amplitude_deg", 2.0, 16.0),       # hip pitch fore and aft, knee turned against it
    ("lift_deg", 0.0, 30.0),                 # extra bend of the unloaded leg
    ("step_phase_deg", 30.0, 150.0),         # step sine against the sway sine
]
GAIT_KEYS = [name for name, _, _ in GAIT_SPACE]


def from_unit(space: list, x) -> dict:
    """Map a point of the unit cube to named parameters."""
    return {name: lo + min(max(float(v), 0.0), 1.0) * (hi - lo) for (name, lo, hi), v in zip(space, x)}


def _clip(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def walk_pose(stand_deg, p: dict, ts: float, forward: float = 1.0, turn: float = 0.0) -> list:
    """Joint angles ts seconds into the gait. Same formula as gait.gait()
    with the page's forward and turn inputs."""
    q = list(stand_deg)
    if ts <= 0:
        return q
    ramp = min(1.0, ts / p["period_s"])
    w = 2.0 * math.pi * ts / p["period_s"]
    sway = math.sin(w)                          # +1: the right foot is unloaded
    swing = math.sin(w + math.radians(p["step_phase_deg"]))
    roll = ramp * p["roll_amplitude_deg"] * sway
    left = ramp * p["step_amplitude_deg"] * _clip(forward - turn, -1.0, 1.0) * swing
    right = ramp * p["step_amplitude_deg"] * _clip(forward + turn, -1.0, 1.0) * swing
    left_lift = ramp * p["lift_deg"] * max(0.0, -sway)
    right_lift = ramp * p["lift_deg"] * max(0.0, sway)
    q[0] += roll
    q[3] += roll
    q[1] += -left + left_lift
    q[2] += left - 2.0 * left_lift
    q[4] += right + right_lift
    q[5] += -right - 2.0 * right_lift
    return q


def rate_limit(trajectory: list, max_speed_deg_s: float, cal=None) -> list:
    """What the firmware's rate limiter (and soft limits, if cal is given)
    makes of a trajectory: each joint moves at most max_speed per tick."""
    out, current = [], list(trajectory[0][1])
    previous_t = trajectory[0][0]
    for t, q in trajectory:
        step = max_speed_deg_s * (t - previous_t) / 1000.0
        target = cal.clamp(q) if cal is not None else q
        if t == trajectory[0][0]:
            current = list(target)
        else:
            current = [c + min(max(g - c, -step), step) for c, g in zip(current, target)]
        previous_t = t
        out.append((t, [round(c, 1) for c in current]))
    return out


def walk(stand_deg, p: dict, seconds: float, forward: float = 1.0, turn: float = 0.0, lead_in_s: float = 1.0,
         max_speed_deg_s: float = 120.0, cal=None) -> list:
    """Stand for lead_in_s, ramp the gait in over one period, then walk."""
    out = [(t, walk_pose(stand_deg, p, t / 1000.0 - lead_in_s, forward, turn))
           for t in range(0, int(round(seconds * 1000)) + 1, TICK_MS)]
    return rate_limit(out, max_speed_deg_s, cal)


def keyframes(frames: list, max_speed_deg_s: float, cal=None) -> list:
    """Linear moves between (seconds, pose) keyframes, 50 Hz. The first
    keyframe is the start pose at 0 s; each later one is reached at its time
    and held until the next."""
    out = []
    end_ms = int(round(frames[-1][0] * 1000))
    index = 0
    for t in range(0, end_ms + 1, TICK_MS):
        while index + 1 < len(frames) and t / 1000.0 >= frames[index + 1][0]:
            index += 1
        if index + 1 >= len(frames):
            out.append((t, list(frames[-1][1])))
            continue
        (t0, a), (t1, b) = frames[index], frames[index + 1]
        u = (t / 1000.0 - t0) / (t1 - t0)
        out.append((t, [x + u * (y - x) for x, y in zip(a, b)]))
    return rate_limit(out, max_speed_deg_s, cal)


def symmetric(roll: float, pitch: float, knee: float) -> list:
    """A left-right symmetric pose; roll is outward on both legs."""
    return [roll, pitch, knee, -roll, pitch, knee]


JUMP_SPACE = [
    ("crouch_hip_deg", 45.0, 62.0),
    ("crouch_knee_deg", -90.0, -40.0),
    ("push_hip_deg", 0.0, 50.0),
    ("push_knee_deg", -90.0, 0.0),
    ("knee_delay_s", -0.10, 0.10),              # knee starts this long after the hips
    ("tuck_after_s", 0.06, 0.30),               # from the start of the push to the landing pose
    ("land_hip_deg", 30.0, 62.0),
    ("land_knee_deg", -80.0, -30.0),
]
JUMP_KEYS = [name for name, _, _ in JUMP_SPACE]


def jump(stand_deg, p: dict, max_speed_deg_s: float, crouch_speed_deg_s: float = 60.0, cal=None,
         settle_s: float = 0.6, after_s: float = 1.5) -> tuple:
    """Crouch slowly, push off as fast as the rate limit allows, go to the
    landing pose, then back to the stand pose. Returns the trajectory and the
    time the push starts (s)."""
    crouch = symmetric(0.0, p["crouch_hip_deg"], p["crouch_knee_deg"])
    push = symmetric(0.0, p["push_hip_deg"], p["push_knee_deg"])
    land = symmetric(0.0, p["land_hip_deg"], p["land_knee_deg"])
    t_crouch = 0.4 + max(abs(a - b) for a, b in zip(stand_deg, crouch)) / crouch_speed_deg_s
    t_push = t_crouch + settle_s
    t_land = t_push + p["tuck_after_s"]
    end = t_land + after_s
    slow = keyframes([(0.0, list(stand_deg)), (0.4, list(stand_deg)), (t_crouch, crouch), (t_push, crouch)], crouch_speed_deg_s, cal)
    out = list(slow)
    delay = p["knee_delay_s"]
    for t in range(slow[-1][0] + TICK_MS, int(round(end * 1000)) + 1, TICK_MS):
        ts = t / 1000.0
        if ts < t_land:
            q = list(crouch)
            for i in (1, 4):
                if ts >= t_push + max(0.0, -delay):
                    q[i] = push[i]
            for i in (2, 5):
                if ts >= t_push + max(0.0, delay):
                    q[i] = push[i]
        elif ts < t_land + 0.6:
            q = land
        else:
            u = min(1.0, (ts - t_land - 0.6) / 0.6)
            q = [a + u * (b - a) for a, b in zip(land, stand_deg)]
        out.append((t, q))
    fast = rate_limit(out[len(slow) - 1:], max_speed_deg_s, cal)
    return slow + fast[1:], t_push
