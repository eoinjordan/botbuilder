# SPDX-License-Identifier: MIT
"""Open-loop trajectories: stand, and a weight-shift-and-step gait.

A trajectory is a list of (t_ms, [six joint angles in degrees]) at 50 Hz, in
the joint order of microduck.protocol.JOINTS. On disk it is a CSV with the
header t_ms,<six joint names>.

The gait has no feedback. Each cycle it
  1. rolls both hips the same way, which tilts the body and unloads one foot,
  2. swings the unloaded leg forward and the loaded leg back at the hips,
     with the knees turned the other way so the soles stay level,
  3. optionally bends the unloaded knee a little further to lift that foot.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .protocol import JOINTS, ROOT, TICK_MS


def load_params(path: Path | None = None) -> dict:
    with open(path or ROOT / "config" / "gait.json", encoding="utf-8") as handle:
        return json.load(handle)


def stand(stand_deg, seconds: float) -> list:
    return [(t, list(stand_deg)) for t in range(0, int(seconds * 1000) + 1, TICK_MS)]


def gait(stand_deg, params: dict, seconds: float) -> list:
    """Stand for lead_in_s, ramp the gait in over one period, then walk."""
    period = params["period_s"]
    roll = params["roll_amplitude_deg"]
    step = params["step_amplitude_deg"]
    lift = params["lift_deg"]
    lead = params["lead_in_s"]
    phase = math.radians(params["step_phase_deg"])
    out = []
    for t in range(0, int(seconds * 1000) + 1, TICK_MS):
        ts = t / 1000.0 - lead
        q = list(stand_deg)
        if ts > 0:
            ramp = min(1.0, ts / period)
            w = 2.0 * math.pi * ts / period
            sway = math.sin(w)                    # +1: body tilted so the right foot is unloaded
            swing = math.sin(w + phase)
            r = ramp * roll * sway
            s = ramp * step * swing
            left_lift = ramp * lift * max(0.0, -sway)
            right_lift = ramp * lift * max(0.0, sway)
            # roll: same angle on both hips keeps the legs parallel
            q[0] += r
            q[3] += r
            # pitch: positive hip pitch carries the foot backward. With the
            # default 90 degree phase the unloaded leg moves forward.
            q[1] += -s + left_lift
            q[2] += s - 2.0 * left_lift
            q[4] += s + right_lift
            q[5] += -s - 2.0 * right_lift
        out.append((t, q))
    return out


def write_csv(path: Path, trajectory: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["t_ms"] + JOINTS)
        for t, q in trajectory:
            writer.writerow([t] + [f"{v:.1f}" for v in q])


def read_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if header != ["t_ms"] + JOINTS:
            raise ValueError(f"{path}: header must be t_ms,{','.join(JOINTS)}")
        out = []
        for row in reader:
            if not row:
                continue
            if len(row) != 7:
                raise ValueError(f"{path}: seven columns expected")
            out.append((int(row[0]), [float(v) for v in row[1:]]))
    if any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        raise ValueError(f"{path}: t_ms must increase")
    return out


def check_limits(trajectory: list, cal) -> list:
    """Rows that leave the joint limits or ask for more than the speed limit.
    Returns (t_ms, joint, problem) tuples; empty means the trajectory is
    playable as written."""
    problems = []
    previous = None
    for t, q in trajectory:
        for joint, value in zip(cal.joints, q):
            if value < joint.min_deg - 1e-6 or value > joint.max_deg + 1e-6:
                problems.append((t, joint.name, f"{value:.1f} outside [{joint.min_deg}, {joint.max_deg}]"))
        if previous is not None:
            dt = (t - previous[0]) / 1000.0
            for joint, a, b in zip(cal.joints, previous[1], q):
                if abs(b - a) / dt > cal.max_speed_deg_s + 1e-6:
                    problems.append((t, joint.name, f"{abs(b - a) / dt:.0f} deg/s over the {cal.max_speed_deg_s:.0f} deg/s limit"))
        previous = (t, q)
    return problems
