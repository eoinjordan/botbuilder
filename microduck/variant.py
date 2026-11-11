# SPDX-License-Identifier: MIT
"""The robot for the motion study, built from robot/microduck.xml, and the
presets it is compared with.

"comb" is the robot as generated: no overrides. Another preset is the
generated model plus a short list of overrides (config/presets.json), used
for comparison only; "flat_feet" puts back the sole plates as first drawn.

build() edits the generated MJCF in memory:

  * the servo model of microduck/motionsim.py: torque motors in place of the
    position actuators and a series spring between each horn and its link,
  * joint ranges opened to the servo travel: the soft limits act on the
    commands, as on the robot, and a relaxed joint runs to its travel stop,
  * the overrides of the preset: head mass, sole plates.

As in the generated model, parts of the robot collide with the floor only.
The generated collision boxes are bounding boxes of slices of the parts; the
comb soles pass each other with a few millimetres to spare and their boxes
do not, so leg against leg and leg against torso are checked on the exact
meshes after a run (motionsim.run, motion_experiments) instead of being
simulated on the boxes.

Lengths in the overrides are millimetres in the left leg's frames; the right
leg is the mirror image.
"""
from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from dataclasses import replace

import numpy as np

from . import protocol
from .protocol import JOINTS, ROOT

SIDES = (("left", 1.0), ("right", -1.0))
VARIANT_RGBA = "0.85 0.45 0.25 1"      # changed parts are drawn in another colour
SOLE_ZONE_M = 0.014                    # the sole and its ribs are within this of the underside
SERVO_TRAVEL_RAD = 1.5708


def load_json(name: str) -> dict:
    with open(ROOT / "config" / name, encoding="utf-8") as handle:
        return json.load(handle)


def physics_defaults() -> dict:
    return {k: v["value"] for k, v in load_json("motion.json")["physics"].items()}


def load_presets() -> dict:
    return load_json("presets.json")["presets"]


def preset_overrides(preset) -> dict:
    """Overrides of a named preset, or the dict itself."""
    if isinstance(preset, dict):
        return copy.deepcopy(preset)
    return copy.deepcopy(load_presets()[preset]["overrides"])


def _vec(text: str) -> np.ndarray:
    return np.array([float(v) for v in text.split()])


def _fmt(values) -> str:
    return " ".join(f"{float(v):.6g}" for v in np.ravel(values))


def _box_inertia(mass: float, half: np.ndarray) -> np.ndarray:
    full = 2.0 * np.asarray(half)
    return mass / 12.0 * np.diag([full[1] ** 2 + full[2] ** 2, full[0] ** 2 + full[2] ** 2, full[0] ** 2 + full[1] ** 2])


def _read_inertial(body: ET.Element) -> tuple:
    node = body.find("inertial")
    f = _vec(node.get("fullinertia"))
    inertia = np.array([[f[0], f[3], f[4]], [f[3], f[1], f[5]], [f[4], f[5], f[2]]])
    return float(node.get("mass")), _vec(node.get("pos")), inertia


def _write_inertial(body: ET.Element, mass: float, com: np.ndarray, inertia: np.ndarray) -> None:
    node = body.find("inertial")
    node.set("mass", f"{mass:.6g}")
    node.set("pos", _fmt(com))
    node.set("fullinertia", _fmt([inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2]]))


def combine(parts: list) -> tuple:
    """Mass, centre of mass and inertia about it of (mass, com, inertia about
    own com) parts. A part with negative mass removes material."""
    mass = sum(p[0] for p in parts)
    com = sum(p[0] * np.asarray(p[1]) for p in parts) / mass
    inertia = np.zeros((3, 3))
    for m, c, i in parts:
        d = np.asarray(c) - com
        inertia += np.asarray(i) + m * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return mass, com, inertia


def _body(root: ET.Element, name: str) -> ET.Element:
    return next(b for b in root.iter("body") if b.get("name") == name)


def _parent_map(root: ET.Element) -> dict:
    return {child: parent for parent in root.iter() for child in parent}


def _sole_boxes(shin: ET.Element) -> tuple:
    """The boxes of a shin that make up its sole (everything within the sole
    zone of the underside), and the height of the underside."""
    boxes = [g for g in shin.findall("geom") if g.get("type") == "box"]
    bottom = min(_vec(g.get("pos"))[2] - _vec(g.get("size"))[2] for g in boxes)
    sole = [g for g in boxes if _vec(g.get("pos"))[2] + _vec(g.get("size"))[2] <= bottom + SOLE_ZONE_M]
    return sole, bottom


def _apply_foot(root: ET.Element, foot: dict) -> None:
    """Replace the sole of each shin by flat plates. foot["plates"] are
    rectangles (min, max in mm, x forward, y outboard, in the shin frame),
    thickness_mm thick, underside where the generated sole's is. The shin's
    mass and inertia are rebuilt from its boxes at the density the generated
    shin has over its own boxes."""
    thickness = foot.get("thickness_mm", 5.0) / 1000.0
    for side, sign in SIDES:
        shin = _body(root, f"{side}_shin")
        old, bottom = _sole_boxes(shin)
        boxes = [g for g in shin.findall("geom") if g.get("type") == "box"]
        density = _read_inertial(shin)[0] / sum(8.0 * np.prod(_vec(g.get("size"))) for g in boxes)
        index = list(shin).index(old[0])
        for geom in old:
            shin.remove(geom)
        for i, plate in enumerate(foot["plates"]):
            lo = np.array([plate["min"][0], plate["min"][1]]) / 1000.0
            hi = np.array([plate["max"][0], plate["max"][1]]) / 1000.0
            if sign < 0:
                lo, hi = np.array([lo[0], -hi[1]]), np.array([hi[0], -lo[1]])
            centre = np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), bottom + 0.5 * thickness])
            half = np.array([0.5 * (hi[0] - lo[0]), 0.5 * (hi[1] - lo[1]), 0.5 * thickness])
            shin.insert(index + i, ET.Element("geom", {"name": f"{side}_sole_{i}", "type": "box", "pos": _fmt(centre),
                                                       "size": _fmt(half), "rgba": VARIANT_RGBA}))
        parts = []
        for geom in shin.findall("geom"):
            if geom.get("type") == "box":
                half = _vec(geom.get("size"))
                mass = density * 8.0 * np.prod(half)
                parts.append((mass, _vec(geom.get("pos")), _box_inertia(mass, half)))
        _write_inertial(shin, *combine(parts))


def _apply_head(root: ET.Element, head: dict) -> None:
    mass = head.get("extra_mass_g", 0.0) / 1000.0
    if mass == 0.0:
        return
    torso = _body(root, "torso")
    _write_inertial(torso, *combine([_read_inertial(torso), (mass, np.array(head["position_mm"]) / 1000.0, np.zeros((3, 3)))]))


def build(preset="comb", physics: dict | None = None, head: dict | None = None) -> tuple:
    """MJCF text and facts about it for a preset name or an overrides dict."""
    phys = {**physics_defaults(), **(physics or {})}
    overrides = preset_overrides(preset)
    motion = load_json("motion.json")
    root = ET.parse(ROOT / "robot" / "microduck.xml").getroot()
    info = {"overrides": overrides, "physics": phys}
    root.find("option").set("timestep", f"{phys['timestep_s']:g}")
    solref = f"{phys['contact_timeconst_s']:g} 1"
    root.find("default").find("geom").set("solref", solref)
    for geom in root.iter("geom"):
        if geom.get("name") == "floor":
            geom.set("solref", solref)
    for tag in ("keyframe", "sensor"):
        node = root.find(tag)
        if node is not None:
            root.remove(node)

    if "foot" in overrides:
        _apply_foot(root, overrides["foot"])
    _apply_head(root, {**motion["head"], **overrides.get("head", {}), **(head or {})})

    info["sole_geoms"], info["foot_geoms"] = {}, {}
    for side, _ in SIDES:
        sole, bottom = _sole_boxes(_body(root, f"{side}_shin"))
        info["sole_geoms"][side] = [g.get("name") for g in sole]
        info["foot_geoms"][side] = [g.get("name") for g in sole
                                    if _vec(g.get("pos"))[2] - _vec(g.get("size"))[2] <= bottom + 0.0005]

    # Series spring between each horn and its link; joints free over the servo travel.
    parents = _parent_map(root)
    for joint_name in JOINTS:
        body = next(b for b in root.iter("body") if b.find("joint") is not None and b.find("joint").get("name") == joint_name)
        joint = body.find("joint")
        joint.set("range", f"{-SERVO_TRAVEL_RAD} {SERVO_TRAVEL_RAD}")
        servo = "SR311" if joint_name.endswith("knee") else "SR431"
        parent = parents[body]
        horn = ET.Element("body", {"name": f"{joint_name}_horn", "pos": body.get("pos")})
        body.remove(joint)
        horn.append(joint)
        ET.SubElement(horn, "inertial", {"pos": "0 0 0", "mass": "0.0001", "diaginertia": "1e-8 1e-8 1e-8"})
        index = list(parent).index(body)
        parent.remove(body)
        parent.insert(index, horn)
        body.set("pos", "0 0 0")
        body.insert(0, ET.Element("joint", {"name": f"{joint_name}_flex", "type": "hinge", "axis": joint.get("axis"),
                                            "stiffness": f"{phys['flex_nm_per_rad'][servo]:g}",
                                            "damping": f"{phys['flex_damping_nms_per_rad'][servo]:g}",
                                            "range": "-0.15 0.15"}))
        horn.append(body)

    actuators = root.find("actuator")
    for node in list(actuators):
        limit = node.get("forcerange").split()[1]
        actuators.remove(node)
        ET.SubElement(actuators, "motor", {"name": node.get("name"), "joint": node.get("joint"),
                                           "ctrlrange": f"-{limit} {limit}", "forcerange": f"-{limit} {limit}"})
    return ET.tostring(root, encoding="unicode"), info


def calibration(preset="comb") -> protocol.Calibration:
    """The firmware calibration with the preset's joint limits and stand
    pose. A preset that changes the soles has no clearance table: the leg
    clearance rule belongs to the soles the robot is built with."""
    cal = protocol.load_calibration()
    overrides = preset_overrides(preset)
    joints = list(cal.joints)
    for name, (lo, hi) in overrides.get("joint_limits_deg", {}).items():
        i = JOINTS.index(name)
        joints[i] = replace(joints[i], min_deg=float(lo), max_deg=float(hi))
    stand = overrides.get("stand_pose_deg")
    return replace(cal, joints=joints, stand_deg=[float(v) for v in stand] if stand else list(cal.stand_deg),
                   clearance=None if "foot" in overrides else cal.clearance)
