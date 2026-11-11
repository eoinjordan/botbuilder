# SPDX-License-Identifier: MIT
"""Digital assembly test: interference, joint sweeps, cradle fit, board
clearance, mass, centre of mass and static balance.

All geometry tests are exact boolean operations in manifold3d on the printed
STLs and the parametric servos. Lengths in mm, angles in degrees, mass in g.
"""
from __future__ import annotations

import itertools

import numpy as np
from manifold3d import Manifold
from scipy.spatial import ConvexHull

from . import model
from .model import (BLANK_HOLE_RADIUS, JOINTS, PLATE, SLOT_SIZE, SLOT_X_FRACTION, SLOT_Y_OFFSET,
                    Robot, apply, box, cylinder_z, frame, servo_shape, trans, trimesh_from_manifold)

SERVO_HALF_TRAVEL = 90.0


def _bbox(m: Manifold) -> np.ndarray:
    return np.asarray(m.bounding_box(), float).reshape(2, 3)


def _tight_bbox(m: Manifold) -> np.ndarray:
    """Bounding box of the volume of m. Booleans between solids that share a
    face can leave zero-thickness fins that inflate the plain bounding box;
    this trims each side inwards until it cuts real volume."""
    bb = _bbox(m)
    total = m.volume()
    eps = max(1e-3, 1e-4 * total)
    for axis in range(3):
        for side in (0, 1):
            normal = [0.0, 0.0, 0.0]
            normal[axis] = 1.0 if side == 0 else -1.0
            lo, hi = bb[0][axis], bb[1][axis]
            # outside is the far side of the plane; find where volume starts
            a, b = (lo, hi) if side == 0 else (hi, lo)
            for _ in range(24):
                mid = 0.5 * (a + b)
                kept = m.trim_by_plane(normal, mid * normal[axis]).volume()
                if total - kept > eps:
                    b = mid
                else:
                    a = mid
            bb[side][axis] = a
    return bb


def _disjoint(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(np.any(a[1] < b[0]) or np.any(b[1] < a[0]))


def _r(value, digits=2):
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_r(v, digits) for v in value]
    return round(float(value), digits)


# --- interference -----------------------------------------------------------

def interferences(placed, threshold: float) -> list:
    """Pairs of solids whose intersection volume exceeds the threshold."""
    live = [(link, s, m, _bbox(m)) for link, s, m in placed if not m.is_empty()]
    found = []
    for (la, sa, ma, ba), (lb, sb, mb, bb) in itertools.combinations(live, 2):
        if _disjoint(ba, bb):
            continue
        common = ma ^ mb
        volume = common.volume()
        if volume > threshold:
            cb = _tight_bbox(common)
            found.append({"a": sa.name, "b": sb.name, "link_a": la, "link_b": lb,
                          "same_link": la == lb, "volume_mm3": _r(volume, 1),
                          "box_min_mm": _r(cb[0]), "box_max_mm": _r(cb[1]),
                          "depth_mm": _r(float(np.min(cb[1] - cb[0])))})
    return sorted(found, key=lambda f: -f["volume_mm3"])


def sweep_joint(robot: Robot, joint: str, step: float, threshold: float, ignore: set, base_q=None) -> dict:
    """Turn one joint each way from the base pose until something that moves
    with it meets something that does not. Pairs in ignore (already
    interfering at the base pose) are left out."""
    moving_links = set(robot.subtree(robot.link_of_joint(joint)))
    frames0 = robot.fk(base_q)
    fixed = []
    for link, solid in robot.solids():
        if link not in moving_links and not solid.manifold.is_empty():
            m = apply(solid.manifold, frames0[link])
            fixed.append((solid.name, m, _bbox(m)))
    movers = [(link, solid) for link, solid in robot.solids()
              if link in moving_links and not solid.manifold.is_empty()]

    def hits(angle: float) -> list:
        q = dict(base_q or {})
        q[joint] = angle
        frames = robot.fk(q)
        out = []
        for link, solid in movers:
            m = apply(solid.manifold, frames[link])
            mb = _bbox(m)
            for name, fm, fb in fixed:
                if frozenset((solid.name, name)) in ignore or _disjoint(mb, fb):
                    continue
                volume = (m ^ fm).volume()
                if volume > threshold:
                    out.append({"moving": solid.name, "fixed": name, "volume_mm3": _r(volume, 1)})
        return out

    result = {}
    for label, sign in (("positive", 1.0), ("negative", -1.0)):
        angle, free, blockers, first = 0.0, 180.0, [], None
        while angle < 180.0 - 1e-9:
            nxt = min(angle + step, 180.0)
            if hits(sign * nxt):
                lo, hi = angle, nxt
                while hi - lo > 0.25:
                    mid = 0.5 * (lo + hi)
                    if hits(sign * mid):
                        hi = mid
                    else:
                        lo = mid
                free, first, blockers = lo, hi, hits(sign * hi)
                break
            angle = nxt
        result[label] = {"free_deg": _r(free), "first_contact_deg": None if first is None else _r(sign * first),
                         "blocked_by": blockers}
    return {"joint": joint, "collision_free_deg": [_r(-result["negative"]["free_deg"]), _r(result["positive"]["free_deg"])],
            "positive": result["positive"], "negative": result["negative"]}


def joint_limits(sweeps: dict, margin: float) -> dict:
    """Collision-free range, less a margin where a collision sets the end,
    intersected with the servo travel about the neutral pose."""
    limits = {}
    for joint, sweep in sweeps.items():
        lo, hi = sweep["collision_free_deg"]
        lo_lim = -SERVO_HALF_TRAVEL if lo <= -SERVO_HALF_TRAVEL - margin else lo + margin
        hi_lim = SERVO_HALF_TRAVEL if hi >= SERVO_HALF_TRAVEL + margin else hi - margin
        lo_lim, hi_lim = min(lo_lim, 0.0), max(hi_lim, 0.0)
        limits[joint] = {"min_deg": _r(np.ceil(lo_lim)), "max_deg": _r(np.floor(hi_lim)),
                         "min_set_by": "servo travel" if lo_lim == -SERVO_HALF_TRAVEL else "collision",
                         "max_set_by": "servo travel" if hi_lim == SERVO_HALF_TRAVEL else "collision"}
    return limits


# --- cradles and horns ------------------------------------------------------

def _solid(robot: Robot, name: str):
    for link, solid in robot.solids():
        if solid.name == name:
            return link, solid
    raise KeyError(name)


def _largest_clear(test, hi=4.0, tol=0.01) -> float:
    """Largest growth in [0, hi] for which test(growth) reports no overlap."""
    if test(hi):
        return hi
    lo = 0.0
    if not test(lo):
        return -1.0
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if test(mid):
            lo = mid
        else:
            hi = mid
    return lo


def cradle_checks(robot: Robot) -> list:
    out = []
    for c in robot.cradles:
        shape = servo_shape(c.model, robot.hardware)
        l, w, h = shape.length, shape.width, shape.height
        printed = _solid(robot, c.printed)[1].manifold
        body = _solid(robot, c.servo)[1].manifold
        case = apply(shape.case, c.servo_to_link)

        def side_clear(growth):
            probe = box([-l / 4, -w / 2 - growth, 0.3], [l / 4, w / 2 + growth, 3.5])
            return (apply(probe, c.servo_to_link) ^ printed).volume() < 1e-3

        seat = apply(box([-l / 2, -w / 2, -0.2], [l / 2, w / 2, 0.0]), c.servo_to_link)
        slots_open = 0
        for sx, sy in itertools.product((-1, 1), (-1, 1)):
            cx, cy = sx * l * SLOT_X_FRACTION, sy * (w / 2 + SLOT_Y_OFFSET)
            probe = box([cx - SLOT_SIZE[0] / 2 + 0.3, cy - SLOT_SIZE[1] / 2 + 0.3, 0.5],
                        [cx + SLOT_SIZE[0] / 2 - 0.3, cy + SLOT_SIZE[1] / 2 - 0.3, PLATE - 0.5])
            if (apply(probe, c.cradle_to_link) ^ printed).volume() < 1e-3:
                slots_open += 1
        # A tie over the case top at each slot pair: does it cross the output
        # boss or the horn hub?
        ties = []
        for sx in (-1, 1):
            cx = sx * l * SLOT_X_FRACTION
            band = box([cx - SLOT_SIZE[0] / 2, -w / 2, h], [cx + SLOT_SIZE[0] / 2, w / 2, h + 1.5])
            blocked = (band ^ (shape.body + shape.horn)).volume()
            ties.append({"at_x_mm": _r(cx), "shaft_x_mm": _r(shape.shaft_x), "overlap_mm3": _r(blocked, 1),
                         "clear": bool(blocked < 0.5)})
        out.append({
            "servo": c.servo, "model": c.model, "link": c.link, "printed_part": c.printed, "drives": c.joint,
            "rail_clearance_each_side_mm": _r(_largest_clear(side_clear)),
            "rail_clearance_designed_mm": model.RAIL_GAP_EACH_SIDE,
            "seat_support_fraction": _r((seat ^ printed).volume() / (l * w * 0.2)),
            "tie_slots_open": slots_open, "tie_slots_expected": 4,
            "ties": ties,
            "case_interference_mm3": _r((case ^ printed).volume(), 1),
            "body_interference_mm3": _r((body ^ printed).volume(), 1),
        })
    return out


def _axis_frame(origin, axis) -> np.ndarray:
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    other = np.array([0, 0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0, 0])
    x = np.cross(other, axis)
    x /= np.linalg.norm(x)
    return frame(x, np.cross(axis, x), axis, origin)


def horn_checks(robot: Robot, placed) -> list:
    """Horn screw hole on the shaft axis, and a free path for the driver."""
    drv = {k: v["value"] for k, v in robot.hardware["driver"]["assumed"].items()}
    frames = robot.fk()
    out = []
    for name, link in robot.links.items():
        if link.joint is None:
            continue
        to_world = frames[name] @ _axis_frame([0, 0, 0], link.shaft)
        printed = next(s for s in link.solids if s.kind == "print")
        printed_world = apply(printed.manifold, frames[name])
        pin = lambda radius: apply(cylinder_z(radius, -1.0, PLATE + 1.0), to_world)  # noqa: E731
        hole_clear = (pin(BLANK_HOLE_RADIUS - 0.2) ^ printed_world).volume()
        hole_edge = (pin(BLANK_HOLE_RADIUS + 0.3) ^ printed_world).volume()
        seat = apply(cylinder_z(model.BLANK_RADIUS - 0.5, 0.0, PLATE) - cylinder_z(BLANK_HOLE_RADIUS + 0.3, -1, PLATE + 1), to_world)
        seat_fill = (seat ^ printed_world).volume() / seat.volume()
        driver = apply(cylinder_z(drv["screwdriver_radius_mm"], PLATE + 0.5, PLATE + 0.5 + drv["screwdriver_length_mm"]), to_world)
        blockers = []
        for _, solid, m in placed:
            if m.is_empty():
                continue
            volume = (driver ^ m).volume()
            if volume > 0.5:
                blockers.append({"solid": solid.name, "volume_mm3": _r(volume, 1)})
        spec = robot.hardware["servos"][model.servo_for_joint(link.joint)]["assumed"]
        out.append({
            "joint": link.joint, "printed_part": printed.name,
            "hole_on_shaft_axis": bool(hole_clear < 1e-3 and hole_edge > 1e-3),
            "hole_radius_mm": BLANK_HOLE_RADIUS,
            "blank_fill_fraction": _r(seat_fill, 3),
            "horn_radius_mm": spec["horn_radius_mm"]["value"],
            "horn_within_blank": bool(spec["horn_radius_mm"]["value"] <= model.BLANK_RADIUS),
            "driver_path_clear": not blockers, "driver_blocked_by": blockers,
            "driver_from": _r(link.shaft, 0),
        })
    return out


# --- UNO Q on the deck ------------------------------------------------------

def board_checks(robot: Robot) -> dict:
    torso = _solid(robot, "torso_print")[1].manifold
    board = _solid(robot, "unoq")[1].manifold
    shield = _solid(robot, "braccio_shield")[1].manifold
    bb = _bbox(board)
    envelope = robot.envelope
    b = robot.hardware["board"]["published"]

    def side_clear(growth):
        probe = box([bb[0][0] + 10, bb[0][1] - growth, bb[0][2]], [bb[1][0] - 10, bb[1][1] + growth, bb[0][2] + 0.5])
        return (probe ^ torso).volume() < 1e-3

    def blocked(dx):
        return ((board.translate([dx, 0, 0]) ^ torso).volume() > 0.5
                or (shield.translate([dx, 0, 0]) ^ torso).volume() > 0.5)

    shift = None
    for dx in np.arange(0.0, 20.01, 0.25):
        if not blocked(dx):
            shift = float(dx)
            break
    common = board ^ torso
    env_common = envelope ^ torso
    deck_front = 39.0   # build.py: the rectangular deck plate ends at x = +39
    rail_top = 7.8      # build.py: rails from z 3.8 to 7.8
    return {
        "board_outline_mm": [b["length_mm"], b["width_mm"]],
        "board_box_min_mm": _r(bb[0]), "board_box_max_mm": _r(bb[1]),
        "rail_clearance_each_side_mm": _r(_largest_clear(side_clear)),
        "rail_engagement_mm": _r(rail_top - bb[0][2]),
        "board_interference_mm3": _r(common.volume(), 1),
        "board_interference_box_mm": None if common.volume() < 0.5 else _r(_tight_bbox(common)),
        "shield_interference_mm3": _r((shield ^ torso).volume(), 1),
        "stack_envelope_interference_mm3": _r(env_common.volume(), 1),
        "forward_shift_to_clear_mm": shift,
        "front_overhang_after_shift_mm": None if shift is None else _r(max(0.0, bb[1][0] + shift - deck_front)),
    }


# --- camera mount -----------------------------------------------------------

def _cone_hits(robot: Robot, cone: Manifold, q=None, links=None) -> list:
    out = []
    for link, solid, m in robot.placed(q):
        if solid.name == "camera_board" or m.is_empty() or (links and link not in links):
            continue
        volume = (cone ^ m).volume()
        if volume > 0.5:
            out.append({"solid": solid.name, "volume_mm3": _r(volume, 1)})
    return out


def camera_checks(robot: Robot, limits: dict, stand_q: dict) -> dict:
    """The camera board in its mount: fit, clearance to the controller stack,
    and the cone kept clear in front of the lens."""
    cam, spec, pose = robot.camera, robot.camera["spec"], robot.camera["pose"]
    torso = _solid(robot, "torso_print")[1].manifold
    board = _solid(robot, "camera_board")[1].manifold
    to_torso = pose["to_torso"]
    w, l, t = spec["width"], spec["length"], spec["thickness"]

    def pcb(grow_y=0.0, shift_x=0.0, shift_z=0.0):
        # The volume the board sweeps when moved by the shifts.
        return apply(box([min(shift_x, 0.0), -w / 2 - grow_y, min(shift_z, 0.0)],
                         [t + max(shift_x, 0.0), w / 2 + grow_y, l + max(shift_z, 0.0)]), to_torso)

    side = _largest_clear(lambda g: (pcb(grow_y=g) ^ torso).volume() < 1e-3)
    forward = _largest_clear(lambda g: (pcb(shift_x=g) ^ torso).volume() < 1e-3)
    back = _largest_clear(lambda g: (pcb(shift_x=-g) ^ torso).volume() < 1e-3)
    seated = (pcb(shift_z=-0.2) ^ torso).volume() > 1e-3
    lift = _largest_clear(lambda g: (pcb(shift_z=g) ^ torso).volume() < 1e-3, hi=10.0)
    # The printed mount alone: the torso above the deck, ahead of the board bay.
    mount = torso ^ box([34.4, -80, PLATE + 0.05], [200, 80, 300])
    gaps = {}
    for name in ("unoq", "braccio_shield"):
        other = _solid(robot, name)[1].manifold
        gaps[name] = {"to_mount_mm": _r(other.min_gap(mount, 60.0)), "to_camera_board_mm": _r(other.min_gap(board, 60.0))}
    gaps["stack_envelope"] = {"to_mount_mm": _r(robot.envelope.min_gap(mount, 60.0)),
                              "to_camera_board_mm": _r(robot.envelope.min_gap(board, 60.0))}
    cone = model.view_cone(pose, cam["cone_half_angle_deg"])
    # Each joint over its limits, others at the stand pose and at neutral:
    # where does a leg come into the cone?
    sweeps = {}
    for joint in JOINTS:
        links = set(robot.subtree(robot.link_of_joint(joint)))
        lo, hi = limits[joint]["min_deg"], limits[joint]["max_deg"]
        row = {}
        for label, base in (("from_neutral", {}), ("from_stand", stand_q)):
            inside = [float(a) for a in np.arange(lo, hi + 0.5, 3.0)
                      if _cone_hits(robot, cone, {**base, joint: float(a)}, links)]
            row[label] = {"angles_in_cone_deg": [min(inside), max(inside)] if inside else None}
        sweeps[joint] = row
    frames = robot.fk(stand_q)
    sole = model.point(frames["left_shin"], [0, 0, sole_points(robot, "left")[:, 2].min()])[2]
    feet = sole_points(robot, "left")
    return {
        "preset": cam["preset"], "name": spec["name"],
        "board_mm": [w, l, t], "mass_g": spec["mass_g"],
        "tilt_below_level_deg": robot.assumptions["camera"]["tilt_deg"],
        "lens_mm": _r(pose["lens"]), "looks_along": _r(pose["forward"], 3),
        "toes_ahead_of_shin_mm": _r(feet[:, 0].max()), "heel_behind_shin_mm": _r(-feet[:, 0].min()),
        "looks_the_way_the_toes_point": bool(pose["forward"][0] > 0 and feet[:, 0].max() > -feet[:, 0].min()),
        "lens_height_above_floor_at_stand_mm": _r(pose["lens"][2] - sole),
        "clearance_each_side_mm": _r(side), "play_towards_the_lips_mm": _r(forward), "play_towards_the_ledges_mm": _r(back),
        "seated_on_the_corner_seats": bool(seated), "play_upwards_to_the_catch_mm": _r(lift),
        "board_overlap_with_mount_mm3": _r((board ^ torso).volume(), 2),
        "gaps": gaps,
        "cone_half_angle_deg": cam["cone_half_angle_deg"],
        "cone_blocked_at_neutral": _cone_hits(robot, cone),
        "cone_blocked_at_stand": _cone_hits(robot, cone, stand_q),
        "cone_sweeps": sweeps,
    }


def camera_preset_summary(robot: Robot) -> dict:
    """The short form of the checks, for a camera preset the full report does
    not use: fit, clearances, the cone at two poses, mass and balance."""
    threshold = robot.assumptions["interference_threshold_mm3"]
    stand = support(robot, {}, ("left", "right"))
    limits = {j: {"min_deg": -90.0, "max_deg": 90.0} for j in JOINTS}
    bal = balance(robot, limits)
    full = camera_checks(robot, {j: {"min_deg": 0.0, "max_deg": 0.0} for j in JOINTS}, bal["stand_pose"]["q_deg"])
    total, com = centre_of_mass(robot)
    keep = ("preset", "name", "board_mm", "mass_g", "lens_mm", "lens_height_above_floor_at_stand_mm", "clearance_each_side_mm",
            "play_towards_the_lips_mm", "play_towards_the_ledges_mm", "play_upwards_to_the_catch_mm",
            "seated_on_the_corner_seats", "board_overlap_with_mount_mm3", "gaps", "cone_blocked_at_neutral", "cone_blocked_at_stand")
    out = {k: full[k] for k in keep}
    out.update({"neutral_interferences": [(f["a"], f["b"], f["volume_mm3"]) for f in interferences(robot.placed(), threshold)],
                "total_g": _r(total, 1), "com_neutral_mm": _r(com),
                "neutral_margin_mm": stand["margin_mm"], "stand_thigh_swing_deg": bal["stand_pose"]["thigh_swing_deg"],
                "stand_margin_mm": bal["stand_pose"]["margin_mm"]})
    return out


# --- attachment features compatible with LEGO elements -----------------------

def _segment(a, b, radius, inner=0.0) -> Manifold:
    a, b = np.asarray(a, float), np.asarray(b, float)
    length = float(np.linalg.norm(b - a))
    rod = cylinder_z(radius, 0.0, length)
    if inner:
        rod -= cylinder_z(inner, -1.0, length + 1.0)
    return apply(rod, _axis_frame(a, b - a))


def lego_checks(robot: Robot, design: dict) -> dict:
    """Pin holes and studs the generator added: is each hole open for a pin of
    nominal diameter over a full beam thickness, is there wall around it, does
    each stud exist, and how far each is from the nearest joint axis and from
    any other part at the neutral pose."""
    spec = design["lego_compatible"]
    frames = robot.fk()
    placed = robot.placed()
    by_part = {s.part: (link, s) for link, s in robot.solids() if s.kind == "print"}
    axes = [(link.joint, frames[name][:3, 3], frames[name][:3, :3] @ link.axis) for name, link in robot.links.items() if link.joint]

    def to_world(part, p):
        link, solid = by_part[part]
        return model.point(frames[link] @ solid.part_to_link, p), link, solid

    def axis_distance(p):
        return min(float(np.linalg.norm(np.cross(p - o, d))) for _, o, d in axes)

    def neighbour_gap(shape, own):
        gaps = [(shape.min_gap(m, 30.0), s.name) for _, s, m in placed if s.name != own and not m.is_empty()]
        gap, name = min(gaps)
        return _r(gap), name

    holes, studs = [], []
    pin_r = spec["pin_hole"] / 2
    bore_r = (spec["pin_counterbore"][0] + spec["hole_extra"]) / 2
    for h in spec["holes"]:
        a, link, solid = to_world(h["part"], h["start"])
        b = to_world(h["part"], h["end"])[0]
        printed = apply(solid.manifold, frames[link])
        inset = spec["pin_counterbore"][1] * (b - a) / np.linalg.norm(b - a)
        wall = _segment(a + inset, b - inset, bore_r + 0.8, bore_r + 0.1)
        gap, near = neighbour_gap(_segment(a, b, bore_r + 0.8), solid.name)
        holes.append({"part": h["part"], "length_mm": _r(np.linalg.norm(b - a)),
                      "open_for_a_nominal_pin": bool((_segment(a, b, pin_r) ^ printed).volume() < 1e-3),
                      "wall_fill_fraction": _r((wall ^ printed).volume() / wall.volume(), 3),
                      "from_nearest_joint_axis_mm": _r(axis_distance(0.5 * (a + b))),
                      "nearest_other_part": near, "gap_to_it_mm": gap})
    stud_r, stud_h = (spec["stud"][0] - spec["stud_under"]) / 2, spec["stud"][1]
    for s in spec["studs"]:
        base, link, solid = to_world(s["part"], s["base"])
        tip = to_world(s["part"], np.asarray(s["base"]) + stud_h * np.asarray(s["axis"]))[0]
        printed = apply(solid.manifold, frames[link])
        body = _segment(base, tip, stud_r - 0.05)
        gap, near = neighbour_gap(_segment(base, tip, stud_r), solid.name)
        studs.append({"part": s["part"], "present": bool((body ^ printed).volume() > 0.98 * body.volume()),
                      "points_up_at_neutral": bool((tip - base)[2] > 0.99 * stud_h),
                      "from_nearest_joint_axis_mm": _r(axis_distance(base)),
                      "nearest_other_part": near, "gap_to_it_mm": gap})
    cone = model.view_cone(robot.camera["pose"], robot.camera["cone_half_angle_deg"])
    in_cone = 0
    for item, key in [(h, "start") for h in spec["holes"]] + [(s, "base") for s in spec["studs"]]:
        p = to_world(item["part"], item[key])[0]
        in_cone += int((apply(Manifold.sphere(3.0, 12), trans(*p)) ^ cone).volume() > 0)
    return {"nominal_mm": {k: spec[k] for k in ("pitch", "pin_hole", "pin_counterbore", "beam", "stud")},
            "print_allowance_mm": {"hole_extra": spec["hole_extra"], "stud_under": spec["stud_under"]},
            "holes": holes, "studs": studs, "features_in_the_camera_cone_at_neutral": in_cone,
            "counts": {part: {"holes": sum(h["part"] == part for h in holes), "studs": sum(s["part"] == part for s in studs)}
                       for part in sorted({x["part"] for x in holes + studs})}}


def decoration_budget(robot: Robot, stand_q: dict) -> list:
    """How much extra mass the stand pose tolerates at a few places before the
    centre of mass reaches the edge of the support polygon. Static balance on
    two feet only: no servo torque, no motion."""
    frames = robot.fk(stand_q)
    base = support(robot, stand_q, ("left", "right"))
    ground = np.linalg.inv(frames["left_shin"])
    hull = ConvexHull(np.asarray(base["polygon_mm"]))
    total, com = centre_of_mass(robot, stand_q)
    com_g = model.point(ground, com)
    pose = robot.camera["pose"]
    places = [("at the camera, on the mount", [("torso", pose["lens"])]),
              ("on the rear pin holes of the deck", [("torso", [-41.0, 0.0, 12.0])]),
              ("on the deck studs, shared between both sides", [("torso", [-24.0, 48.0, 10.0]), ("torso", [-24.0, -48.0, 10.0])]),
              ("on the thigh pin holes, shared between both thighs", None),
              ("on the shin pin holes, shared between both shins", None),
              ("on the foot studs, shared between both feet", None)]
    by_part = {s.part: (link, s) for link, s in robot.solids() if s.kind == "print"}

    def part_point(part, p):
        link, solid = by_part[part]
        return model.point(frames[link] @ solid.part_to_link, p)

    places[3] = (places[3][0], [(None, part_point(f"{s}_thigh", [36.0, 0.0, -4.0])) for s in ("left", "right")])
    places[4] = (places[4][0], [(None, part_point(f"{s}_shin", [0.0, 0.0, 40.0])) for s in ("left", "right")])
    places[5] = (places[5][0], [(None, part_point(f"{s}_shin", [26.0, 0.0, 12.0])) for s in ("left", "right")])
    out = []
    for label, points in places:
        where = np.mean([model.point(ground, p if link is None else model.point(frames[link], p)) for link, p in points], axis=0)

        def margin(grams):
            c = (total * com_g + grams * where) / (total + grams)
            return float(-np.max(hull.equations[:, :2] @ c[:2] + hull.equations[:, 2]))

        limit = None
        if margin(3000.0) <= 0:
            lo, hi = 0.0, 3000.0
            while hi - lo > 0.5:
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if margin(mid) > 0 else (lo, mid)
            limit = lo
        out.append({"where": label, "point_in_ground_frame_mm": _r(where), "margin_with_50_g_mm": _r(margin(50.0)),
                    "margin_with_100_g_mm": _r(margin(100.0)), "margin_with_200_g_mm": _r(margin(200.0)),
                    "mass_that_uses_up_the_margin_g": None if limit is None else _r(limit, 0)})
    return out


# --- mass and balance -------------------------------------------------------

def solid_mass(solid) -> tuple:
    """Mass in g, centre of mass in mm and inertia about it in g mm2, all in
    the link frame. Uniform density over the solid's volume."""
    if solid.mass_g <= 0 or solid.manifold.is_empty():
        return 0.0, np.zeros(3), np.zeros((3, 3))
    mesh = trimesh_from_manifold(solid.manifold)
    props = mesh.mass_properties
    scale = solid.mass_g / props["mass"]
    return solid.mass_g, np.asarray(props["center_mass"]), np.asarray(props["inertia"]) * scale


_MASS_CACHE: dict = {}
_SOLE_CACHE: dict = {}


def link_mass(link) -> tuple:
    """Mass, centre of mass and inertia about it for a whole link."""
    if id(link) in _MASS_CACHE:
        return _MASS_CACHE[id(link)][1]
    parts = [solid_mass(s) for s in link.solids]
    mass = sum(p[0] for p in parts)
    com = sum(p[0] * p[1] for p in parts) / mass
    inertia = np.zeros((3, 3))
    for m, c, i in parts:
        d = c - com
        inertia += i + m * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    _MASS_CACHE[id(link)] = (link, (mass, com, inertia))   # keeps the link alive, so the id stays unique
    return mass, com, inertia


def centre_of_mass(robot: Robot, q=None) -> tuple:
    frames = robot.fk(q)
    total, moment = 0.0, np.zeros(3)
    for name, link in robot.links.items():
        m, c, _ = link_mass(link)
        total += m
        moment += m * model.point(frames[name], c)
    return total, moment / total


def sole_points(robot: Robot, side: str) -> np.ndarray:
    """Corner points of the flat sole, in the shin link frame."""
    link = robot.links[f"{side}_shin"]
    if id(link) not in _SOLE_CACHE:
        solid = next(s for s in link.solids if s.kind == "print")
        v = trimesh_from_manifold(solid.manifold).vertices
        _SOLE_CACHE[id(link)] = (link, v[v[:, 2] < v[:, 2].min() + 0.05])
    return _SOLE_CACHE[id(link)][1]


def support(robot: Robot, q, stance: tuple) -> dict:
    """Static balance with the named feet flat on the ground. The ground
    frame is the first stance shin's frame; gravity is its -z."""
    frames = robot.fk(q)
    ground = np.linalg.inv(frames[f"{stance[0]}_shin"])
    pts = []
    for side in stance:
        local = sole_points(robot, side)
        pts.append((ground @ frames[f"{side}_shin"] @ np.c_[local, np.ones(len(local))].T).T[:, :3])
    allp = np.vstack(pts)
    coplanar = bool(np.ptp(allp[:, 2]) < 1.0)
    hull = ConvexHull(allp[:, :2])
    mass, com = centre_of_mass(robot, q)
    com_g = model.point(ground, com)
    margin = float(-np.max(hull.equations[:, :2] @ com_g[:2] + hull.equations[:, 2]))
    out = {"stance": list(stance), "feet_coplanar": coplanar, "com_ground_mm": _r(com_g),
           "com_height_above_sole_mm": _r(com_g[2] - allp[:, 2].min()),
           "polygon_mm": _r(allp[hull.vertices, :2]), "margin_mm": _r(margin),
           "inside": bool(margin > 0 and coplanar)}
    others = [s for s in ("left", "right") if s not in stance]
    if others:
        local = sole_points(robot, others[0])
        swing = (ground @ frames[f"{others[0]}_shin"] @ np.c_[local, np.ones(len(local))].T).T[:, :3]
        out["swing_foot_lowest_mm"] = _r(swing[:, 2].min() - allp[:, 2].min())
    return out


def balance(robot: Robot, limits: dict) -> dict:
    out = {"neutral_two_feet": support(robot, {}, ("left", "right"))}
    # Feet flat and shins vertical: thighs swing by t, knees by -t.
    best = None
    lo = max(limits["left_hip_pitch"]["min_deg"], -limits["left_knee"]["max_deg"],
             limits["right_hip_pitch"]["min_deg"], -limits["right_knee"]["max_deg"])
    hi = min(limits["left_hip_pitch"]["max_deg"], -limits["left_knee"]["min_deg"],
             limits["right_hip_pitch"]["max_deg"], -limits["right_knee"]["min_deg"])
    scan = []
    for t in np.arange(np.ceil(lo), np.floor(hi) + 0.5, 1.0):
        q = {"left_hip_pitch": t, "left_knee": -t, "right_hip_pitch": t, "right_knee": -t}
        s = support(robot, q, ("left", "right"))
        scan.append([float(t), s["margin_mm"]])
        if best is None or s["margin_mm"] > best[1]["margin_mm"]:
            best = (float(t), s, q)
    out["stand_scan_deg_margin_mm"] = scan
    out["stand_pose"] = {"thigh_swing_deg": best[0], "q_deg": {j: float(best[2].get(j, 0.0)) for j in JOINTS}, **best[1]}
    stand_q = best[2]
    threshold = robot.assumptions["interference_threshold_mm3"]
    ignore = {frozenset((f["a"], f["b"])) for f in interferences(robot.placed(), threshold)}
    out["stand_pose_interferences"] = [f for f in interferences(robot.placed(stand_q), threshold)
                                       if frozenset((f["a"], f["b"])) not in ignore]
    for stance in ("left", "right"):
        out[f"one_foot_{stance}"] = one_foot(robot, limits, stand_q, stance)
    return out


def one_foot(robot: Robot, limits: dict, stand_q: dict, stance: str) -> dict:
    """Stance foot flat on the ground, other foot free. With no ankle the only
    way to move the centre of mass sideways over the stance foot is to roll
    the stance hip, which tilts the torso and carries the other leg with it.
    Scans both hip rolls over their limits."""
    swing = "right" if stance == "left" else "left"
    local = sole_points(robot, stance)
    hull = ConvexHull(local[:, :2])
    sole_z = local[:, 2].min()
    swing_local = np.c_[sole_points(robot, swing), np.ones(len(sole_points(robot, swing)))]
    masses = {name: link_mass(link) for name, link in robot.links.items()}
    total = sum(m[0] for m in masses.values())
    carried = [n for n in robot.links if n not in robot.subtree(f"{stance}_hip")]
    spec = robot.hardware["servos"]["SR431"]["published"]
    limit_nm = spec["torque_kgcm_4v8"] * 9.80665 / 100.0

    def evaluate(ra, rb):
        q = dict(stand_q)
        q[f"{stance}_hip_roll"], q[f"{swing}_hip_roll"] = float(ra), float(rb)
        frames = robot.fk(q)
        ground = np.linalg.inv(frames[f"{stance}_shin"])
        com = sum(masses[n][0] * model.point(frames[n], masses[n][1]) for n in robot.links) / total
        cg = model.point(ground, com)
        margin = float(-np.max(hull.equations[:, :2] @ cg[:2] + hull.equations[:, 2]))
        swing_low = float((ground @ frames[f"{swing}_shin"] @ swing_local.T)[2].min() - sole_z)
        mc = sum(masses[n][0] for n in carried)
        cc = sum(masses[n][0] * model.point(frames[n], masses[n][1]) for n in carried) / mc
        arm = cc - frames[f"{stance}_hip"][:3, 3]
        gravity = -(frames[f"{stance}_shin"][:3, 2])
        axis = frames["torso"][:3, 0]
        torque = float(np.dot(axis, np.cross(arm, gravity)) * mc * 9.80665 * 1e-6)
        return {"stance_roll_deg": float(ra), "swing_roll_deg": float(rb), "margin_mm": _r(margin),
                "swing_foot_lowest_mm": _r(swing_low), "stance_hip_roll_torque_nm": _r(torque, 3),
                "torque_limit_nm": _r(limit_nm, 3), "inside": bool(margin > 0 and swing_low >= 0),
                "torque_ok": bool(abs(torque) <= limit_nm)}

    a = np.arange(limits[f"{stance}_hip_roll"]["min_deg"], limits[f"{stance}_hip_roll"]["max_deg"] + 0.5, 3.0)
    b = np.arange(limits[f"{swing}_hip_roll"]["min_deg"], limits[f"{swing}_hip_roll"]["max_deg"] + 0.5, 3.0)
    rows = [evaluate(ra, rb) for ra, rb in itertools.product(a, b)]
    lifted = [r for r in rows if r["swing_foot_lowest_mm"] >= 0]
    balanced = [r for r in lifted if r["margin_mm"] > 0]
    small = [r for r in lifted if abs(r["stance_roll_deg"]) <= 30.0]
    return {
        "stance": stance,
        "at_stand_pose": evaluate(0.0, 0.0),
        "best_within_30_deg_stance_roll": max(small, key=lambda r: r["margin_mm"]) if small else None,
        "smallest_stance_roll_that_balances": min(balanced, key=lambda r: (abs(r["stance_roll_deg"]), -r["margin_mm"])) if balanced else None,
        "balances_within_30_deg": bool(any(r["margin_mm"] > 0 for r in small)),
        "balances_anywhere_in_limits": bool(balanced),
    }


def mass_report(robot: Robot) -> dict:
    printing = {k: v["value"] for k, v in robot.hardware["print"]["assumed"].items()}
    rows, by_kind = [], {}
    for link, solid in robot.solids():
        if solid.mass_g > 0:
            rows.append({"solid": solid.name, "link": link, "kind": solid.kind, "mass_g": _r(solid.mass_g, 1)})
            by_kind[solid.kind] = by_kind.get(solid.kind, 0.0) + solid.mass_g
    total, com = centre_of_mass(robot)
    printed = by_kind.get("print", 0.0)
    solid_total = total - printed + printed / printing["solid_fraction"]
    links = {}
    for name, link in robot.links.items():
        m, c, _ = link_mass(link)
        links[name] = {"mass_g": _r(m, 1), "com_link_mm": _r(c)}
    return {"total_g": _r(total, 1), "by_kind_g": {k: _r(v, 1) for k, v in by_kind.items()},
            "total_if_printed_solid_g": _r(solid_total, 1),
            "print_material": printing["material"], "print_density_g_cm3": printing["density_g_cm3"],
            "print_solid_fraction": printing["solid_fraction"],
            "com_neutral_mm": _r(com), "links": links, "solids": rows}


# --- whole report -----------------------------------------------------------

def dimensions(robot: Robot) -> dict:
    placed = [m for _, _, m in robot.placed() if not m.is_empty()]
    lo = np.min([_bbox(m)[0] for m in placed], axis=0)
    hi = np.max([_bbox(m)[1] for m in placed], axis=0)
    frames = robot.fk()
    feet = {}
    for side in ("left", "right"):
        sole = sole_points(robot, side)
        feet[side] = model.point(frames[f"{side}_shin"], 0.5 * (sole.min(axis=0) + sole.max(axis=0)))
    return {"box_min_mm": _r(lo), "box_max_mm": _r(hi), "size_mm": _r(hi - lo),
            "stance_width_between_foot_centres_mm": _r(feet["left"][1] - feet["right"][1]),
            "joint_origins_mm": {link.joint: _r(frames[name][:3, 3]) for name, link in robot.links.items() if link.joint},
            "sole_z_mm": _r(feet["left"][2])}


def analyse(robot: Robot, progress=lambda text: None) -> dict:
    cfg = robot.assumptions
    threshold = cfg["interference_threshold_mm3"]
    placed = robot.placed()
    progress("interference at the neutral pose")
    neutral = interferences(placed, threshold)
    ignore = {frozenset((f["a"], f["b"])) for f in neutral}
    sweeps = {}
    for joint in JOINTS:
        progress(f"sweep {joint}")
        sweeps[joint] = sweep_joint(robot, joint, cfg["sweep_step_deg"], threshold, ignore)
    limits = joint_limits(sweeps, cfg["limit_margin_deg"])
    progress("cradles, horns, board")
    report = {
        "thigh_face": cfg["thigh_face"],
        "dimensions": dimensions(robot),
        "neutral_interferences": neutral,
        "sweeps": sweeps,
        "joint_limits_deg": limits,
        "cradles": cradle_checks(robot),
        "horns": horn_checks(robot, placed),
        "board": board_checks(robot),
        "mass": mass_report(robot),
    }
    progress("balance")
    report["balance"] = balance(robot, limits)
    progress("camera mount")
    report["camera"] = camera_checks(robot, limits, report["balance"]["stand_pose"]["q_deg"])
    progress("pin holes and studs")
    report["lego_compatible"] = lego_checks(robot, model.design_parameters())
    report["decoration_budget"] = decoration_budget(robot, report["balance"]["stand_pose"]["q_deg"])
    return report
