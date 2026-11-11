# SPDX-License-Identifier: MIT
"""Digital assembly test of the Microduck-look build.

Interference at the zero and stand poses, the collision-free range of every
joint against the original's range, mass, centre of mass, balance on two
feet and on each foot, and the static torque each joint has to hold against
what its servo can hold. Holding limit: half of stall torque.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import ConvexHull

from .model import HEAD, JOINTS, LEG, Robot

G = 9.80665
HOLD = 0.5                 # part of stall torque a servo is asked to hold
THRESHOLD = 8.0            # mm3 below which an overlap of two solids is contact, not interference
SWEEP_STEP = 3.0
MARGIN_DEG = 3.0           # taken off each collision-free end for the soft limit
SERVO_TRAVEL = 90.0        # each side of the centre, for every servo used
ONE_FOOT_MARGIN = 8.0      # mm the centre of mass has to be inside the stance sole
SWING_LIFT = 10.0          # mm the swing sole is lifted in the one-foot poses


def _r(value, digits=2):
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_r(v, digits) for v in value]
    return round(float(value), digits)


def _bbox_apart(a, b) -> bool:
    ba, bb = a.bounding_box(), b.bounding_box()
    return any(ba[k] > bb[k + 3] or bb[k] > ba[k + 3] for k in range(3))


def _skip(a, b) -> bool:
    """Pairs that touch by design: a servo and its own horn."""
    return a.name.rsplit("_", 1)[0] == b.name.rsplit("_", 1)[0] and {a.kind, b.kind} == {"servo", "horn"}


def interferences(robot: Robot, q=None, moving=None, threshold: float = THRESHOLD) -> list:
    """Overlaps above the threshold. With 'moving' (a set of links) only pairs across that set are tested."""
    placed = robot.placed(q)
    out = []
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            (la, a, ma), (lb, b, mb) = placed[i], placed[j]
            if moving is not None and (la in moving) == (lb in moving):
                continue
            if la == lb and moving is None and a.kind == b.kind == "servo":
                continue
            if _skip(a, b) or _bbox_apart(ma, mb):
                continue
            cut = ma ^ mb
            volume = cut.volume()
            if volume > threshold:
                box = cut.bounding_box()
                out.append({"a": a.name, "b": b.name, "volume_mm3": _r(volume, 1), "at_mm": _r([(box[k] + box[k + 3]) / 2 for k in range(3)], 1)})
    return sorted(out, key=lambda row: -row["volume_mm3"])


# ---------------------------------------------------------------- feet and balance
def sole_points(robot: Robot, side: str) -> np.ndarray:
    """Points of a foot within 0.6 mm of its lowest level, at the zero pose."""
    foot = next(s for s in robot.links[f"{side}_foot"].solids if s.kind == "shell")
    mesh = foot.solid.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3].astype(float)
    return v[v[:, 2] < v[:, 2].min() + 0.6]


def in_stance_frame(robot: Robot, q: dict, side: str):
    """Poses of all links with the stance foot flat on the floor (z = 0) and where it stands at the zero pose in x, y."""
    poses = robot.poses(q)
    foot = poses[f"{side}_foot"]
    back = np.linalg.inv(foot)
    lift = np.eye(4)
    lift[2, 3] = -robot.floor_z
    return {name: lift @ back @ m for name, m in poses.items()}


def _com(robot: Robot, poses: dict, links=None) -> tuple:
    total, moment = 0.0, np.zeros(3)
    for name in robot.order:
        if links is not None and name not in links:
            continue
        for s in robot.links[name].solids:
            if s.mass_g > 0.0:
                c = robot._props(s)[0]
                moment += s.mass_g * (poses[name][:3, :3] @ c + poses[name][:3, 3])
                total += s.mass_g
    return total / 1000.0, moment / total


def _inside(polygon: np.ndarray, p) -> float:
    """Signed distance of a point inside a convex polygon (counter-clockwise); negative is outside."""
    d = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        e = b - a
        n = np.array([-e[1], e[0]]) / np.linalg.norm(e)
        d.append(float((np.asarray(p) - a) @ n))
    return min(d)


def support(robot: Robot, poses: dict, feet=("left", "right")) -> dict:
    """Centre of mass against the convex hull of the soles that are down."""
    pts = []
    for side in feet:
        m = poses[f"{side}_foot"]
        p = sole_points(robot, side)
        pts.append(p @ m[:3, :3].T + m[:3, 3])
    pts = np.vstack(pts)
    hull = pts[ConvexHull(pts[:, :2]).vertices][:, :2]
    mass, com = _com(robot, poses)
    return {"com_mm": _r(com, 1), "margin_mm": _r(_inside(hull, com[:2]), 1), "polygon_mm": _r(hull, 1), "mass_kg": _r(mass, 4)}


def sagittal(robot: Robot, side: str, hip: float, knee: float) -> dict:
    """Joint angles for a hip pitch and a knee angle given as rotations about +y (the left side's sense), with
    the ankle angle that keeps the sole parallel to the trunk. The right side's axes are mirrored, so its joint
    angles come out with the other sign."""
    s = {j: float(robot.joints[f"{side}_{j}"].axis[1]) for j in ("hip_pitch", "knee", "ankle")}
    return {f"{side}_hip_pitch": hip * s["hip_pitch"], f"{side}_knee": knee * s["knee"], f"{side}_ankle": -(hip + knee) * s["ankle"]}


def physical(robot: Robot, q: dict, side: str) -> tuple:
    """Hip pitch and knee of a leg as rotations about +y."""
    return tuple(q.get(f"{side}_{j}", 0.0) * float(robot.joints[f"{side}_{j}"].axis[1]) for j in ("hip_pitch", "knee"))


def _foot_height(robot: Robot, poses: dict, side: str) -> float:
    m = poses[f"{side}_foot"]
    p = sole_points(robot, side)
    return float((p @ m[:3, :3].T + m[:3, 3])[:, 2].min())


# ---------------------------------------------------------------- torques
def static_torques(robot: Robot, poses: dict, stance) -> dict:
    """Torque each joint holds against gravity (N m, signed about its axis).

    stance is 'left', 'right' or 'both'. On one foot a stance-leg joint carries everything on the far side
    of it from the foot. On both feet each leg is taken to carry half of the trunk, neck and head and its own
    links: exact for the sagittal joints of a symmetric pose, an estimate otherwise."""
    rows = []
    for name in robot.order:
        for s in robot.links[name].solids:
            if s.mass_g > 0.0:
                c = robot._props(s)[0]
                rows.append((name, s.mass_g / 1000.0, (poses[name][:3, :3] @ c + poses[name][:3, 3]) / 1000.0))
    legs = {side: set(robot.subtree(f"{side}_hip_yaw")) for side in ("left", "right")}
    upper = set(robot.order) - legs["left"] - legs["right"]
    out = {}
    for joint in JOINTS:
        j = robot.joints[joint]
        m = poses[j.parent]
        anchor = (m[:3, :3] @ j.anchor + m[:3, 3]) / 1000.0
        axis = m[:3, :3] @ j.axis
        side = joint.split("_")[0] if joint.split("_")[0] in legs else None
        below = set(robot.subtree(j.child))
        weights = {}
        if side and (stance == side or stance == "both"):
            share = 1.0 if stance == side else 0.5
            other = "right" if side == "left" else "left"
            for name in robot.order:
                if name in below:
                    continue
                if name in upper:
                    weights[name] = share
                elif name in legs[side]:
                    weights[name] = 1.0
                elif stance == side:
                    weights[name] = 1.0
            sign = -1.0             # the joint holds the body side up against the leg side
        else:
            weights = {name: 1.0 for name in below}
            sign = 1.0
        moment = np.zeros(3)
        for name, mass, com in rows:
            if name in weights:
                moment += weights[name] * mass * np.cross(com - anchor, [0.0, 0.0, -G])
        out[joint] = sign * float(moment @ axis)
    return out


def torque_table(robot: Robot, cases: dict) -> dict:
    """Per joint: the largest holding torque over the cases against half of stall."""
    out = {}
    for joint in JOINTS:
        spec = robot.types[robot.joints[joint].servo]
        worst = max(cases, key=lambda name: abs(cases[name][joint]))
        need = abs(cases[worst][joint])
        out[joint] = {"servo": robot.joints[joint].servo, "stall_nm": spec["torque"], "hold_limit_nm": _r(HOLD * spec["torque"], 3),
                      "required_nm": _r(need, 3), "worst_case": worst, "required_over_hold_limit": _r(need / (HOLD * spec["torque"]), 2),
                      "required_over_stall": _r(need / spec["torque"], 2),
                      "by_case_nm": {name: _r(values[joint], 3) for name, values in cases.items()}}
    return out


# ---------------------------------------------------------------- poses
def stand_pose(robot: Robot) -> dict:
    """Both legs alike, soles level, centre of mass over the middle of the soles fore and aft, and of the poses
    that do that, the one that asks least of the leg servos."""
    best = None
    for hip in np.arange(-40.0, 40.1, 2.0):
        for knee in np.arange(-40.0, 40.1, 2.0):
            q = {**sagittal(robot, "left", hip, knee), **sagittal(robot, "right", hip, knee)}
            if any(abs(v) > 60.0 for v in q.values()):
                continue
            poses = in_stance_frame(robot, q, "left")
            sup = support(robot, poses)
            pts = np.array(sup["polygon_mm"])
            middle = (pts[:, 0].min() + pts[:, 0].max()) / 2
            off = sup["com_mm"][0] - middle
            torque = static_torques(robot, poses, "both")
            load = max(abs(torque[f"left_{j}"]) / (HOLD * robot.types[robot.joints[f"left_{j}"].servo]["torque"]) for j in ("hip_pitch", "knee", "ankle"))
            cost = load + abs(off) / 10.0 + 0.004 * (abs(hip) + abs(knee))
            if best is None or cost < best[0]:
                best = (cost, q, off)
    return {j: _r(best[1].get(j, 0.0), 1) for j in JOINTS}


def one_foot(robot: Robot, stand: dict, stance: str) -> dict:
    """Smallest equal roll of both hips that brings the centre of mass ONE_FOOT_MARGIN inside the stance sole,
    with the other sole lifted SWING_LIFT. The trunk tilts; the legs stay parallel."""
    swing = "right" if stance == "left" else "left"
    result = {"stance": stance, "found": False}
    # swing leg: the smallest bend that lifts its sole with the sole kept level
    hip0, knee0 = physical(robot, stand, swing)
    base = in_stance_frame(robot, stand, stance)
    lifts = []
    for dh in np.arange(-40.0, 40.1, 5.0):
        for dk in np.arange(-60.0, 60.1, 5.0):
            q = {**stand, **sagittal(robot, swing, hip0 + dh, knee0 + dk)}
            if abs(q[f"{swing}_ankle"]) > 80.0:
                continue
            poses = in_stance_frame(robot, q, stance)
            rise = _foot_height(robot, poses, swing)
            shift = abs(poses[f"{swing}_foot"][0, 3] - base[f"{swing}_foot"][0, 3])
            if rise >= SWING_LIFT and shift < 12.0:
                lifts.append((abs(dh) + abs(dk), q))
    if not lifts:
        return result
    lifted = next((q for _, q in sorted(lifts, key=lambda row: row[0]) if not interferences(robot, q, set(robot.subtree(f"{swing}_hip_yaw")))), None)
    if lifted is None:
        return result
    for sign in (1.0, -1.0):
        for roll in np.arange(0.0, 30.1, 1.0):
            q = dict(lifted)
            q["left_hip_roll"] = sign * roll
            q["right_hip_roll"] = sign * roll
            poses = in_stance_frame(robot, q, stance)
            sup = support(robot, poses, (stance,))
            if sup["margin_mm"] >= ONE_FOOT_MARGIN and _foot_height(robot, poses, swing) >= SWING_LIFT - 2.0:
                hits = interferences(robot, q)
                result.update({"found": True, "roll_deg": _r(sign * roll, 1), "q_deg": {j: _r(q.get(j, 0.0), 1) for j in JOINTS},
                               "com_mm": sup["com_mm"], "margin_mm": sup["margin_mm"], "polygon_mm": sup["polygon_mm"],
                               "swing_sole_height_mm": _r(_foot_height(robot, poses, swing), 1),
                               "interferences": hits, "torque_nm": {k: _r(v, 3) for k, v in static_torques(robot, poses, stance).items()}})
                return result
    # not reached: report how far the centre of mass gets at the largest roll tried
    best = None
    for sign in (1.0, -1.0):
        q = dict(lifted)
        q["left_hip_roll"] = q["right_hip_roll"] = sign * 22.0
        sup = support(robot, in_stance_frame(robot, q, stance), (stance,))
        if best is None or sup["margin_mm"] > best["margin_mm"]:
            best = sup
    result.update({"margin_at_22_deg_mm": best["margin_mm"], "com_mm": best["com_mm"]})
    return result


# ---------------------------------------------------------------- joint ranges
def sweep(robot: Robot, joint: str, base: dict, step: float = SWEEP_STEP) -> dict:
    """Collision-free travel of one joint from the stand pose, the other joints held there."""
    j = robot.joints[joint]
    moving = set(robot.subtree(j.child))
    centre = base.get(joint, 0.0)
    out = {"joint": joint, "from_deg": _r(centre, 1), "original_range_deg": list(j.original_range)}
    for name, direction in (("max", 1.0), ("min", -1.0)):
        end, stop = centre, None
        angle = centre
        while True:
            angle = angle + direction * step
            if abs(angle) > SERVO_TRAVEL + 1e-6:
                stop = "servo travel"
                break
            hits = interferences(robot, {**base, joint: angle}, moving)
            if hits:
                stop = f"{hits[0]['a']} against {hits[0]['b']}"
                break
            end = angle
        out[f"{name}_free_deg"] = _r(end, 1)
        out[f"{name}_set_by"] = stop
    lo, hi = out["min_free_deg"], out["max_free_deg"]
    lo_limit = lo if out["min_set_by"] == "servo travel" else min(lo + MARGIN_DEG, centre)
    hi_limit = hi if out["max_set_by"] == "servo travel" else max(hi - MARGIN_DEG, centre)
    o_lo, o_hi = j.original_range
    out["min_deg"], out["max_deg"] = _r(max(lo_limit, o_lo), 1), _r(min(hi_limit, o_hi), 1)
    span = o_hi - o_lo
    out["part_of_original_range"] = _r(max(0.0, out["max_deg"] - out["min_deg"]) / span, 2)
    return out


# ---------------------------------------------------------------- alternatives
ASSIGNMENTS = {
    "one kit, lightest": {"hip_yaw": "M5_180", "hip_roll": "M5_180", "hip_pitch": "SR311", "knee": "SR431", "ankle": "SR431",
                          "neck_pitch": "M5_180", "head_pitch": "M5_180", "head_yaw": "M5_180", "head_roll": "M5_180", "beak": "M5_180"},
    "two kits, built": {"hip_yaw": "SR311", "hip_roll": "SR431", "hip_pitch": "SR431", "knee": "SR431", "ankle": "SR431",
                        "neck_pitch": "SR311", "head_pitch": "SR311", "head_yaw": "M5_180", "head_roll": "M5_180", "beak": "M5_180"},
    "two kits, light hips": {"hip_yaw": "M5_180", "hip_roll": "SR311", "hip_pitch": "SR431", "knee": "SR431", "ankle": "SR431",
                             "neck_pitch": "SR311", "head_pitch": "SR311", "head_yaw": "M5_180", "head_roll": "M5_180", "beak": "M5_180"},
}


def assignment(name: str) -> dict:
    return {f"{side}{joint}": kind for joint, kind in ASSIGNMENTS[name].items()
            for side in (("left_", "right_") if joint in LEG else ("",))}


def torque_cases(robot: Robot, stand: dict, feet: dict) -> dict:
    """The poses the torque table is taken over."""
    cases = {"stand, two feet": static_torques(robot, in_stance_frame(robot, stand, "left"), "both")}
    for side in ("left", "right"):
        cases[f"stand pose, all weight on the {side} foot"] = static_torques(robot, in_stance_frame(robot, stand, side), side)
        if feet[side].get("found"):
            q = feet[side]["q_deg"]
            cases[f"on the {side} foot, other lifted"] = static_torques(robot, in_stance_frame(robot, q, side), side)
    # walking: the stance leg 12 degrees either way at the hip with the sole level, and the trunk leaning with it
    for lean in (-12.0, 12.0):
        q = dict(stand)
        for side in ("left", "right"):
            hip, knee = physical(robot, stand, side)
            q.update(sagittal(robot, side, hip + lean, knee))
        cases[f"step, hips {lean:+.0f} deg, left foot"] = static_torques(robot, in_stance_frame(robot, q, "left"), "left")
    # the head as far forward as the neck's soft range is meant to go
    q = dict(stand)
    q["neck_pitch"] = 30.0 * float(np.sign(robot.joints["neck_pitch"].axis[1]))
    cases["neck 30 deg forward"] = static_torques(robot, in_stance_frame(robot, q, "left"), "both")
    q = dict(stand)
    q["head_pitch"] = 30.0 * float(np.sign(robot.joints["head_pitch"].axis[1]))
    cases["head 30 deg down"] = static_torques(robot, in_stance_frame(robot, q, "left"), "both")
    q = dict(stand)
    q["head_roll"] = 25.0
    cases["head rolled 25 deg"] = static_torques(robot, in_stance_frame(robot, q, "left"), "both")
    return cases


def compare(folder=None) -> dict:
    """Mass and worst holding torque of each candidate assignment on the same printed structure and scale."""
    out = {}
    for name in ASSIGNMENTS:
        robot = Robot(folder, assignment(name))
        stand = stand_pose(robot)
        feet = {side: one_foot(robot, stand, side) for side in ("left", "right")}
        table = torque_table(robot, torque_cases(robot, stand, feet))
        count = {}
        for joint in JOINTS:
            count[robot.joints[joint].servo] = count.get(robot.joints[joint].servo, 0) + 1
        worst = max(table, key=lambda j: table[j]["required_over_hold_limit"])
        out[name] = {"assignment": ASSIGNMENTS[name], "servos": count, "mass_kg": _r(robot.mass_kg(), 3),
                     "leg_mass_kg": _r(robot.com(None, set(robot.subtree("left_hip_yaw")))[0], 3),
                     "one_foot": {side: bool(feet[side].get("found")) for side in feet},
                     "worst_joint": worst, "worst_required_over_hold_limit": table[worst]["required_over_hold_limit"],
                     "over_hold_limit": sorted(j for j in table if table[j]["required_over_hold_limit"] > 1.0),
                     "over_stall": sorted(j for j in table if table[j]["required_over_stall"] > 1.0),
                     "joints": {j: {k: table[j][k] for k in ("servo", "required_nm", "hold_limit_nm", "required_over_hold_limit", "worst_case")} for j in JOINTS}}
    return out
