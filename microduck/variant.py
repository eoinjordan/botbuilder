# SPDX-License-Identifier: MIT
"""Presets of the robot for the motion study, built from robot/microduck.xml.

A preset is the generated model plus a short list of overrides
(config/presets.json). "drawn" has none: it is the published geometry.
Every other preset is a design variant explored in simulation only and is
never the owner's original design.

build() edits the generated MJCF in memory:

  * the servo model of microduck/motionsim.py: torque motors in place of the
    position actuators and a series spring between each horn and its link,
  * the overrides of the preset: head mass, sole plates, hip position.

Nothing here needs the STLs. Lengths in the overrides are millimetres in the
left leg's frames; the right leg is the mirror image.
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
FOOT_RGBA = "0.93 0.80 0.47 1"
VARIANT_RGBA = "0.85 0.45 0.25 1"      # changed parts are drawn in another colour


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


def _sole_geom(shin: ET.Element) -> ET.Element:
    boxes = [g for g in shin.findall("geom") if g.get("type") == "box"]
    return min(boxes, key=lambda g: _vec(g.get("pos"))[2])


def print_density_kg_m3() -> float:
    printing = load_json("hardware.json")["print"]["assumed"]
    return printing["density_g_cm3"]["value"] * 1000.0 * printing["solid_fraction"]["value"]


def _rocker_vertices(lo, hi, bottom, edge, radius, centre_y, n=13) -> np.ndarray:
    """Points of a sole whose underside is an arc of the given radius across
    the foot (about an axis along x above y = centre_y), flat along the foot.
    The lowest point of the arc is at 'bottom'; the flat top is 'edge' above
    the highest point of the underside. Metres."""
    ys = np.unique(np.r_[np.linspace(lo[1], hi[1], n), np.clip(centre_y, lo[1], hi[1])])
    rise = radius - np.sqrt(radius ** 2 - (ys - centre_y) ** 2)
    top = bottom + rise.max() + edge
    pts = [[x, y, z] for x in (lo[0], hi[0]) for y, r in zip(ys, rise) for z in (bottom + r, top)]
    return np.array(pts)


def _apply_foot(root: ET.Element, foot: dict, info: dict) -> None:
    """Replace the sole plate of each shin. foot["plates"] are rectangles
    (min, max in mm, x forward, y outboard, in the shin frame) for both feet,
    or left_plates and right_plates when the feet differ. A plate is a
    flat box thickness_mm thick, or with rocker_radius_mm a sole curved
    across the foot whose lowest line is at rocker_centre_y_mm."""
    from scipy.spatial import ConvexHull
    density = print_density_kg_m3()
    asset = root.find("asset")
    for side, sign in SIDES:
        shin = _body(root, f"{side}_shin")
        old = _sole_geom(shin)
        pos, half = _vec(old.get("pos")), _vec(old.get("size"))
        bottom = pos[2] - half[2]
        thickness = foot.get("thickness_mm", 2000.0 * half[2]) / 1000.0
        parts = [_read_inertial(shin)]
        old_mass = density * 8.0 * np.prod(half)
        parts.append((-old_mass, pos, -_box_inertia(old_mass, half)))
        index = list(shin).index(old)
        shin.remove(old)
        names = []
        for i, plate in enumerate(foot.get(f"{side}_plates", foot.get("plates"))):
            lo = np.array([plate["min"][0], plate["min"][1]]) / 1000.0
            hi = np.array([plate["max"][0], plate["max"][1]]) / 1000.0
            if sign < 0:
                lo, hi = np.array([lo[0], -hi[1]]), np.array([hi[0], -lo[1]])
            name = f"{side}_sole_{i}"
            if plate.get("rocker_radius_mm"):
                centre_y = sign * plate.get("rocker_centre_y_mm", 0.5 * (plate["min"][1] + plate["max"][1])) / 1000.0
                verts = _rocker_vertices(lo, hi, bottom, thickness, plate["rocker_radius_mm"] / 1000.0, centre_y)
                hull = ConvexHull(verts)
                mass = density * hull.volume
                mean_t = hull.volume / np.prod(hi - lo)
                centre = np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), verts[:, 2].max() - 0.5 * mean_t])
                h = np.array([0.5 * (hi[0] - lo[0]), 0.5 * (hi[1] - lo[1]), 0.5 * mean_t])
                ET.SubElement(asset, "mesh", {"name": name, "vertex": _fmt(verts)})
                geom = ET.Element("geom", {"name": name, "type": "mesh", "mesh": name, "rgba": VARIANT_RGBA})
            else:
                low = bottom + plate.get("raise_mm", 0.0) / 1000.0
                centre = np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), low + 0.5 * thickness])
                h = np.array([0.5 * (hi[0] - lo[0]), 0.5 * (hi[1] - lo[1]), 0.5 * thickness])
                mass = density * 8.0 * np.prod(h)
                geom = ET.Element("geom", {"name": name, "type": "box", "pos": _fmt(centre), "size": _fmt(h), "rgba": VARIANT_RGBA})
            shin.insert(index + i, geom)
            parts.append((mass, centre, _box_inertia(mass, h)))
            names.append(name)
            info.setdefault("sole_mass_g", {})[name] = round(float(mass) * 1000.0, 1)
        _write_inertial(shin, *combine(parts))
        info["foot_geoms"][side] = names


def _apply_head(root: ET.Element, head: dict) -> None:
    mass = head.get("extra_mass_g", 0.0) / 1000.0
    if mass == 0.0:
        return
    torso = _body(root, "torso")
    _write_inertial(torso, *combine([_read_inertial(torso), (mass, np.array(head["position_mm"]) / 1000.0, np.zeros((3, 3)))]))


def _apply_hips(root: ET.Element, shift_mm, info: dict) -> None:
    """Move both hip roll cradles (servo, cradle and everything below) by
    shift_mm = [dx, dy outboard] on the torso. The deck is unchanged."""
    dx, dy = shift_mm[0] / 1000.0, shift_mm[1] / 1000.0
    torso = _body(root, "torso")
    parts = [_read_inertial(torso)]
    for side, sign in SIDES:
        hip = _body(root, f"{side}_hip")
        delta = np.array([dx, sign * dy, 0.0])
        hip.set("pos", _fmt(_vec(hip.get("pos")) + delta))
        y0 = _vec(hip.get("pos"))[1] - sign * dy
        for geom in torso.findall("geom"):
            pos, half = _vec(geom.get("pos")), _vec(geom.get("size"))
            # the cradle and its servo hang below the deck at the hip's y
            if geom.get("type") == "box" and abs(pos[1] - y0) < 1e-3 and pos[2] < 0.0:
                geom.set("pos", _fmt(pos + delta))
                servo = geom.get("rgba", "").startswith("0.24")
                mass = info["roll_servo_kg"] * 8.0 * np.prod(half) / info["roll_servo_box_volume"] if servo \
                    else print_density_kg_m3() * 8.0 * np.prod(half)
                parts.append((-mass, pos, -_box_inertia(mass, half)))
                parts.append((mass, pos + delta, _box_inertia(mass, half)))
    _write_inertial(torso, *combine(parts))


def build(preset="drawn", physics: dict | None = None, head: dict | None = None) -> tuple:
    """MJCF text and facts about it for a preset name or an overrides dict."""
    phys = {**physics_defaults(), **(physics or {})}
    overrides = preset_overrides(preset)
    motion = load_json("motion.json")
    root = ET.parse(ROOT / "robot" / "microduck.xml").getroot()
    info = {"foot_geoms": {}, "overrides": overrides, "physics": phys}
    root.find("option").set("timestep", f"{phys['timestep_s']:g}")
    solref = f"{phys['contact_timeconst_s']:g} 1"
    root.find("default").find("geom").set("solref", solref)
    for geom in root.iter("geom"):
        if geom.get("name") == "floor":
            geom.set("solref", solref)
    key = root.find("keyframe")
    if key is not None:
        root.remove(key)
    sensor = root.find("sensor")
    if sensor is not None:
        root.remove(sensor)

    hardware = load_json("hardware.json")
    big = hardware["servos"]["SR431"]["published"]
    info["roll_servo_kg"] = big["mass_g"] / 1000.0
    # the generated servo is two boxes (case and ears); mass is spread over both
    torso = _body(root, "torso")
    servo_boxes = [g for g in torso.findall("geom") if g.get("rgba", "").startswith("0.24") and _vec(g.get("pos"))[1] > 0]
    info["roll_servo_box_volume"] = sum(8.0 * np.prod(_vec(g.get("size"))) for g in servo_boxes)

    for side, _ in SIDES:
        info["foot_geoms"][side] = [_sole_geom(_body(root, f"{side}_shin")).get("name")]
    if "hip_shift_mm" in overrides:
        _apply_hips(root, overrides["hip_shift_mm"], info)
    if "foot" in overrides:
        _apply_foot(root, overrides["foot"], info)
    _apply_head(root, {**motion["head"], **overrides.get("head", {}), **(head or {})})

    # Series spring between each horn and its link.
    parents = _parent_map(root)
    for joint_name in JOINTS:
        body = next(b for b in root.iter("body") if b.find("joint") is not None and b.find("joint").get("name") == joint_name)
        joint = body.find("joint")
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

    # The legs can hit each other; everything else only meets the floor.
    for side, contype, conaffinity in (("left", "3", "0"), ("right", "1", "2")):
        for part in ("thigh", "shin"):
            for geom in _body(root, f"{side}_{part}").findall("geom"):
                if geom.get("class") != "visual":
                    geom.set("contype", contype)
                    geom.set("conaffinity", conaffinity)

    actuators = root.find("actuator")
    for node in list(actuators):
        limit = node.get("forcerange").split()[1]
        actuators.remove(node)
        ET.SubElement(actuators, "motor", {"name": node.get("name"), "joint": node.get("joint"),
                                           "ctrlrange": f"-{limit} {limit}", "forcerange": f"-{limit} {limit}"})
    return ET.tostring(root, encoding="unicode"), info


def calibration(preset="drawn") -> protocol.Calibration:
    """The firmware calibration with the preset's joint limits and stand pose."""
    cal = protocol.load_calibration()
    overrides = preset_overrides(preset)
    joints = list(cal.joints)
    for name, (lo, hi) in overrides.get("joint_limits_deg", {}).items():
        i = JOINTS.index(name)
        joints[i] = replace(joints[i], min_deg=float(lo), max_deg=float(hi))
    stand = overrides.get("stand_pose_deg")
    return replace(cal, joints=joints, stand_deg=[float(v) for v in stand] if stand else list(cal.stand_deg))
