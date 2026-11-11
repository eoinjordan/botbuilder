# SPDX-License-Identifier: MIT
"""Run the assembly test of the Microduck-look build and draw its pictures.

Writes reports/microduck-look/assembly.json and the pictures in
stl/microduck-look/images (they show the adapted shapes, so they sit with the
parts under the parts' terms).
"""
from __future__ import annotations

import json

import numpy as np

from .. import render
from . import analyse
from .model import FOLDER, HEAD, JOINTS, LEG, ROOT, Robot, to_arrays, union

REPORT = ROOT / "reports" / "microduck-look" / "assembly.json"
IMAGES = FOLDER / "images"
RED = (215, 60, 50)


def _r(value, digits=2):
    return analyse._r(value, digits)


def _extent(robot: Robot, q) -> np.ndarray:
    boxes = np.array([m.bounding_box() for _, _, m in robot.placed(q)])
    return np.array([boxes[:, :3].min(axis=0), boxes[:, 3:].max(axis=0)])


def mass_groups(robot: Robot) -> dict:
    groups = {"printed shells": 0.0, "printed brackets": 0.0, "servos": 0.0, "boards and camera": 0.0}
    for name in robot.order:
        for s in robot.links[name].solids:
            key = {"shell": "printed shells", "frame": "printed brackets", "servo": "servos"}.get(s.kind, "boards and camera")
            groups[key] += s.mass_g
    return {k: _r(v, 1) for k, v in groups.items()}


def leg_table(robot: Robot, stand: dict) -> dict:
    """Smallest gap between the two legs' printed parts and servos for the two hip roll angles, other joints at
    the stand pose. Negative is the volume of overlap in mm3."""
    angles = [-20.0, -10.0, 0.0, 10.0, 20.0]
    legs = {side: set(robot.subtree(f"{side}_hip_yaw")) for side in ("left", "right")}
    rows = []
    for left in angles:
        row = []
        for right in angles:
            q = {**stand, "left_hip_roll": left, "right_hip_roll": right}
            placed = robot.placed(q)
            a = union(m for link, s, m in placed if link in legs["left"] and s.kind != "horn")
            b = union(m for link, s, m in placed if link in legs["right"] and s.kind != "horn")
            overlap = (a ^ b).volume()
            row.append(_r(-overlap, 0) if overlap > analyse.THRESHOLD else _r(a.min_gap(b, 60.0), 1))
        rows.append(row)
    return {"hip_roll_deg": angles, "rows_are": "left_hip_roll", "columns_are": "right_hip_roll", "gap_mm_or_minus_overlap_mm3": rows}


def sway_range(robot: Robot, stand: dict) -> dict:
    """Both hips rolled the same way: how far before anything meets."""
    out = {}
    for name, sign in (("to_the_left_deg", 1.0), ("to_the_right_deg", -1.0)):
        free = 0.0
        for angle in np.arange(2.0, 30.1, 2.0):
            q = {**stand, "left_hip_roll": sign * angle, "right_hip_roll": sign * angle}
            if analyse.interferences(robot, q):
                break
            free = angle
        out[name] = _r(free, 1)
    return out


def bought_part_gaps(robot: Robot, stand: dict) -> list:
    """Each board and the camera: smallest gap to a printed part or servo at the stand pose."""
    placed = robot.placed(stand)
    out = []
    for link, s, m in placed:
        if s.kind not in ("board", "camera"):
            continue
        gaps = [(m.min_gap(other, 30.0), o.name) for _, o, other in placed if o is not s and o.kind != "horn"]
        gap, name = min(gaps)
        out.append({"part": s.name, "nearest": name, "gap_mm": _r(gap, 2)})
    return out


def analyse_all(robot: Robot, progress=print) -> dict:
    p = robot.p
    progress("stand pose")
    stand = analyse.stand_pose(robot)
    poses = analyse.in_stance_frame(robot, stand, "left")
    two = analyse.support(robot, poses)
    extent = _extent(robot, stand)
    zero_extent = _extent(robot, None)
    progress("one foot")
    feet = {side: analyse.one_foot(robot, stand, side) for side in ("left", "right")}
    progress("joint sweeps")
    ranges = {j: analyse.sweep(robot, j, stand) for j in JOINTS}
    progress("torques")
    cases = analyse.torque_cases(robot, stand, feet)
    progress("legs")
    report = {
        "generated_by": "scripts/run_look.py",
        "licence_of_the_shapes": p["_licence"],
        "scale": p["scale"], "eye": p["eye"], "camera": p["camera"], "feet": p["feet"],
        "dimensions": {"height_stand_mm": _r(extent[1][2] - extent[0][2], 1), "height_zero_pose_mm": _r(zero_extent[1][2] - zero_extent[0][2], 1),
                       "width_mm": _r(extent[1][1] - extent[0][1], 1), "length_mm": _r(extent[1][0] - extent[0][0], 1),
                       "original_height_mm_in_the_source_meshes": 263.9},
        "mass": {"total_kg": _r(robot.mass_kg(), 4), "by_group_g": mass_groups(robot),
                 "by_link_g": {name: _r(robot.link_inertial(name)[0], 1) for name in robot.order},
                 "original_kg_in_its_simulation_model": 0.737,
                 "original_scaled_by_volume_kg": _r(0.737 * p["scale"] ** 3, 3)},
        "interferences": {"zero_pose": analyse.interferences(robot), "stand_pose": analyse.interferences(robot, stand)},
        "stand_pose": {"q_deg": stand, "trunk_height_m": _r((poses["trunk"][2, 3]) / 1000.0, 5), "com_mm": two["com_mm"],
                       "margin_mm": two["margin_mm"], "polygon_mm": two["polygon_mm"]},
        "one_foot": feet,
        "sway_both_hips": sway_range(robot, stand),
        "joint_ranges": ranges,
        "torque": analyse.torque_table(robot, cases),
        "leg_clearance": leg_table(robot, stand),
        "bought_part_gaps": bought_part_gaps(robot, stand),
        "servo_clearance_in_cradle_mm": p["clearance_mm"],
        "servo_count": {kind: sum(1 for j in JOINTS if robot.joints[j].servo == kind) for kind in p["servo_types"]},
        "triangles": {"parts": int(sum(e["triangles"] for e in p["parts"])), "source_parts_used": int(sum(p["source_triangles"].values())),
                      "simplification_tolerance_mm": p["decimate_mm"]},
    }
    progress("assignments")
    report["assignments"] = analyse.compare(robot.folder)
    return report


# ---------------------------------------------------------------- pictures
def _items(placed, cut=None):
    items = []
    for _, s, m in placed:
        if cut is not None:
            m = m.trim_by_plane(cut[0], cut[1])
            if m.is_empty():
                continue
        colour = RED if cut is not None and s.kind == "servo" else s.colour
        items.append((*to_arrays(m), colour))
    return items


def _save(image, name: str) -> str:
    IMAGES.mkdir(parents=True, exist_ok=True)
    image.quantize(colors=64, dither=0).save(IMAGES / name, optimize=True)
    return f"stl/microduck-look/images/{name}"


def pictures(robot: Robot, report: dict) -> dict:
    stand = report["stand_pose"]["q_deg"]
    placed = robot.placed(stand)
    out = {}
    for name, view, size in (("front", "front", (620, 760)), ("side", "left", (620, 760)), ("three-quarter", "iso", (700, 760)),
                             ("back", "iso_back", (700, 760))):
        out[name] = _save(render.render(_items(placed), view=view, size=size, supersample=2), f"look-{name}.png")
    thigh_y = float(robot.joints["left_knee"].anchor[1]) + 26.0
    out["section-leg"] = _save(render.render(_items(placed, ([0.0, -1.0, 0.0], -thigh_y)), view="left", size=(620, 760), supersample=2,
                                             title=f"section at y = {thigh_y:.0f} mm, seen from the left; servo cases red"), "look-section-leg.png")
    out["section-centre"] = _save(render.render(_items(placed, ([0.0, -1.0, 0.0], 0.0)), view="left", size=(620, 760), supersample=2,
                                                title="section on the centre plane, seen from the left; servo cases red"), "look-section-centre.png")
    out["section-hips"] = _save(render.render(_items(placed, ([-1.0, 0.0, 0.0], -8.0)), view="front", size=(620, 760), supersample=2,
                                              title="section at x = 8 mm, seen from the front; servo cases red"), "look-section-hips.png")
    foot = report["one_foot"]["left"]
    if foot.get("found"):
        out["one-foot"] = _save(render.render(_items(robot.placed(foot["q_deg"])), view="front", size=(620, 760), supersample=2,
                                              title="on the left foot, the right lifted"), "look-one-foot.png")
    return out


def run(progress=print) -> dict:
    robot = Robot()
    report = analyse_all(robot, progress)
    progress("pictures")
    report["pictures"] = pictures(robot, report)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    return report
