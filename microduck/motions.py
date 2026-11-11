# SPDX-License-Identifier: MIT
"""Open-loop motions for the motion study: a parametric stepping gait with
speed and turn inputs, a jump, and keyframe motions (sit, stand up).

A trajectory is the repository's joint-command format: (t_ms, six joint
angles in degrees) at 50 Hz in the order of protocol.JOINTS. Every generator
ends with rate_limit(), so what is written to a file is what the firmware
will play: nothing in it asks for more than the speed limit it was made for.
"""
from __future__ import annotations

import math

from .protocol import TICK_MS

# name, lower bound, upper bound. Angles in degrees, phases in turns.
GAIT_SPACE = [
    ("period_s", 0.40, 1.60),
    ("hip_pitch_offset_deg", -25.0, 30.0),      # added to both hip pitches: crouch and lean
    ("knee_offset_deg", -30.0, 25.0),           # added to both knees
    ("splay_deg", -4.0, 15.0),                  # both legs rolled outward
    ("sway_deg", 0.0, 25.0),                    # both hips rolled the same way, sine
    ("abduct_deg", -10.0, 25.0),                # swing leg rolled outward during its swing
    ("stride_deg", 0.0, 25.0),                  # hip pitch fore and aft, sine
    ("knee_follow", 0.0, 1.5),                  # knee turned against the stride (1 keeps the sole level)
    ("lift_knee_deg", -40.0, 40.0),             # knee bend added during the swing
    ("lift_hip_deg", -30.0, 30.0),              # hip pitch added during the swing
    ("swing_phase", 0.0, 1.0),                  # where in the cycle the left swing starts
    ("stride_phase", 0.0, 1.0),                 # stride sine against the sway sine
    ("swing_duty", 0.15, 0.60),                 # part of the cycle a swing lasts
]
GAIT_KEYS = [name for name, _, _ in GAIT_SPACE]


def gait_from_unit(x) -> dict:
    """Map a point of the unit cube to gait parameters."""
    return {name: lo + min(max(float(v), 0.0), 1.0) * (hi - lo) for (name, lo, hi), v in zip(GAIT_SPACE, x)}


def gait_to_unit(params: dict) -> list:
    return [(params[name] - lo) / (hi - lo) for name, lo, hi in GAIT_SPACE]


def _bump(turns: float, duty: float) -> float:
    u = turns % 1.0
    return math.sin(math.pi * u / duty) ** 2 if u < duty else 0.0


def gait_pose(stand_deg, p: dict, phase: float, speed: float = 1.0, turn: float = 0.0, amplitude: float = 1.0) -> list:
    """Joint angles at a phase (in turns). speed scales the stride and the
    swing-leg lift, which is what drives the robot forward; turn in [-1, 1]
    scales them down on the left leg (positive: turn left) and up on the
    right."""
    q = list(stand_deg)
    sway = math.sin(2.0 * math.pi * phase)
    out = []
    for side, mirror, shift in (("left", 1.0, 0.0), ("right", -1.0, 0.5)):
        ph = phase + shift
        swing = _bump(ph - p["swing_phase"], p["swing_duty"])
        stride = math.sin(2.0 * math.pi * (ph - p["stride_phase"]))
        scale = speed * min(max(1.0 - mirror * turn, 0.0), 2.0)
        a = amplitude
        roll = mirror * a * p["splay_deg"] + a * p["sway_deg"] * sway + mirror * a * p["abduct_deg"] * swing
        pitch = a * p["hip_pitch_offset_deg"] + a * scale * (p["stride_deg"] * stride + p["lift_hip_deg"] * swing)
        knee = a * p["knee_offset_deg"] + a * scale * (-p["knee_follow"] * p["stride_deg"] * stride + p["lift_knee_deg"] * swing)
        out += [roll, pitch, knee]
    return [b + d for b, d in zip(q, out)]


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


def walk(stand_deg, p: dict, seconds: float, speed: float = 1.0, turn: float = 0.0, lead_in_s: float = 0.5,
         max_speed_deg_s: float = 120.0, cal=None, lead_out_s: float = 0.0) -> list:
    """Stand, blend into the gait over one period, walk, and optionally
    blend back to the stand pose over lead_out_s at the end."""
    out = []
    period = p["period_s"]
    for t in range(0, int(round(seconds * 1000)) + 1, TICK_MS):
        ts = t / 1000.0 - lead_in_s
        if ts <= 0:
            out.append((t, list(stand_deg)))
            continue
        amplitude = min(1.0, ts / period)
        if lead_out_s > 0:
            amplitude = min(amplitude, max(0.0, (seconds - t / 1000.0) / lead_out_s))
        out.append((t, gait_pose(stand_deg, p, ts / period, speed, turn, amplitude)))
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
    ("crouch_hip_deg", 55.0, 90.0),
    ("crouch_knee_deg", -90.0, -40.0),
    ("push_hip_deg", 0.0, 60.0),
    ("push_knee_deg", -90.0, 0.0),
    ("knee_delay_s", -0.10, 0.10),              # knee starts this long after the hips
    ("tuck_after_s", 0.06, 0.30),               # from the start of the push to the landing pose
    ("land_hip_deg", 30.0, 80.0),
    ("land_knee_deg", -80.0, -30.0),
]
JUMP_KEYS = [name for name, _, _ in JUMP_SPACE]


def jump_from_unit(x) -> dict:
    return {name: lo + min(max(float(v), 0.0), 1.0) * (hi - lo) for (name, lo, hi), v in zip(JUMP_SPACE, x)}


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


# --- a statically stable step-together gait for feet that interleave ---------

THIGH_MM = 82.4             # hip pitch axis to knee axis (robot/joints.json origins)
HIP_ROLL_SPACING_MM = 114.0  # between the two hip roll axes
MAX_STRIDE_MM = 22.0        # the comb soles have 26 mm between fingers; one foot never leads by more than this

CRAWL_SPACE = [
    ("period_s", 0.8, 3.0),
    ("stride_mm", 5.0, MAX_STRIDE_MM),      # each foot advances this far per cycle
    ("stand_reach_mm", -60.0, -15.0),       # sole position ahead of the hip at the start of a cycle (negative: behind)
    ("lift_knee_deg", -50.0, -5.0),         # knee bend added in mid swing (toe up)
    ("lift_hip_deg", -10.0, 30.0),          # hip pitch added in mid swing
    ("swing_fraction", 0.15, 0.45),         # part of the cycle each swing takes
    ("right_phase", 0.25, 0.75),            # where in the cycle the right swing starts (the left starts at 0)
    ("roll_gain", 0.0, 1.5),                # hip roll that levels the body when one leg is longer
    ("lean_deg", -8.0, 8.0),                # knee offset: pitches the body on flat soles
    ("turn_trim", -1.0, 1.0),               # stride difference that makes the gait go straight
    ("roll_trim_deg", -6.0, 6.0),           # constant roll of both hips
]
CRAWL_KEYS = [name for name, _, _ in CRAWL_SPACE]


def crawl_from_unit(x) -> dict:
    return {name: lo + min(max(float(v), 0.0), 1.0) * (hi - lo) for (name, lo, hi), v in zip(CRAWL_SPACE, x)}


def _smooth(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


def _hip_for_reach(x_mm: float) -> float:
    """Hip pitch that puts a level sole x_mm ahead of the hip axis."""
    return math.degrees(math.asin(min(max(-x_mm / THIGH_MM, -0.99), 0.99)))


def crawl_pose(p: dict, phase: float, speed: float = 1.0, turn: float = 0.0, amplitude: float = 1.0) -> list:
    """Joint angles of the step-together gait at a phase (turns). The body
    glides forward at a steady rate; each foot in turn is lifted, carried one
    stride forward and set down while the other foot carries the load. turn
    in [-1, 1] shortens the left stride and lengthens the right one
    (positive: turn left)."""
    u = phase % 1.0
    fs = p["swing_fraction"]
    hip, knee, swings = {}, {}, {}
    for side, start, mirror in (("left", 0.0, 1.0), ("right", p["right_phase"], -1.0)):
        stride = amplitude * speed * p["stride_mm"] * min(max(1.0 - mirror * (turn + p.get("turn_trim", 0.0)), 0.0), 2.0)
        stride = min(stride, MAX_STRIDE_MM)
        v = (u - start) / fs
        carried = _smooth(v) if u >= start else 0.0
        swings[side] = math.sin(math.pi * v) ** 2 if 0.0 <= v <= 1.0 else 0.0
        hip[side] = _hip_for_reach(p["stand_reach_mm"] + stride * (carried - u))
        knee[side] = -hip[side] + amplitude * p["lean_deg"]
    longer = THIGH_MM * (math.cos(math.radians(hip["left"])) - math.cos(math.radians(hip["right"])))
    roll = -p["roll_gain"] * math.degrees(math.asin(min(max(longer / HIP_ROLL_SPACING_MM, -0.9), 0.9)))
    roll += amplitude * p.get("roll_trim_deg", 0.0)
    for side in hip:
        hip[side] += amplitude * p["lift_hip_deg"] * swings[side]
        knee[side] += amplitude * p["lift_knee_deg"] * swings[side]
    return [roll, hip["left"], knee["left"], roll, hip["right"], knee["right"]]


def crawl(p: dict, seconds: float, speed: float = 1.0, turn: float = 0.0, lead_in_s: float = 1.0,
          max_speed_deg_s: float = 120.0, cal=None, stand_deg=None) -> list:
    """Move from stand_deg (if given) to the gait's rest pose during the
    lead-in, then step. The first cycle is blended in."""
    out = []
    rest = crawl_pose(p, 0.0, 0.0, 0.0, 0.0)
    start = list(stand_deg) if stand_deg is not None else rest
    for t in range(0, int(round(seconds * 1000)) + 1, TICK_MS):
        ts = t / 1000.0 - lead_in_s
        if ts <= 0:
            w = _smooth(min(1.0, (t / 1000.0) / max(0.6 * lead_in_s, 1e-6)))
            out.append((t, [a + w * (b - a) for a, b in zip(start, rest)]))
            continue
        out.append((t, crawl_pose(p, ts / p["period_s"], speed, turn, min(1.0, ts / p["period_s"]))))
    return rate_limit(out, max_speed_deg_s, cal)
