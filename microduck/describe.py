# SPDX-License-Identifier: MIT
"""Generate the robot description from the assembly model and its report.

Outputs, all regenerated together and never edited by hand:

    robot/microduck.urdf    URDF, primitive shapes
    robot/microduck.xml     MuJoCo MJCF, primitive shapes, floor and actuators
    robot/joints.json       joint order, limits, servo limits, stand pose
    robot/model.json        the same primitives for the web viewer
    build/microduck_visual.xml   MJCF with the STLs as visuals (local only)

SI units in the outputs. Link frames are those of microduck.model.
"""
from __future__ import annotations

import json

import numpy as np

from . import assembly, model
from .model import JOINTS, ROOT, Robot, servo_for_joint, servo_shape

G = 9.80665
FLOOR_FRICTION = 0.6            # assumed: printed PLA sole on a table top
JOINT_FRICTIONLOSS = 0.02       # assumed dry friction of the gear train, N m
KP_SATURATION_DEG = 4.0         # assumed: the servo reaches full torque at this error
RGBA = {"print": "0.93 0.80 0.47 1", "servo": "0.24 0.26 0.29 1", "horn": "0.88 0.89 0.90 1",
        "board": "0.08 0.47 0.43 1", "shield": "0.16 0.35 0.63 1",
        "camera": "0.59 0.16 0.24 1", "display": "0.12 0.12 0.14 1", "battery": "0.35 0.43 0.78 1"}


def _f(values, digits=6) -> str:
    return " ".join(f"{float(v):.{digits}g}" for v in np.ravel(values))


def flat_levels(mesh_vertices, mesh_faces, axis=2, min_area=20.0, merge=2.5) -> list:
    """Coordinates along axis where the mesh has flat faces of real area."""
    tri = mesh_vertices[mesh_faces]
    coord = tri[:, :, axis]
    flat = np.ptp(coord, axis=1) < 1e-4
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    levels: dict = {}
    for z, a in zip(np.round(coord[flat, 0], 2), area[flat]):
        levels[z] = levels.get(z, 0.0) + a
    keep = sorted(z for z, a in levels.items() if a >= min_area)
    lo, hi = mesh_vertices[:, axis].min(), mesh_vertices[:, axis].max()
    out = [lo]
    for z in keep + [hi]:
        if z - out[-1] >= merge:
            out.append(z)
    out[-1] = hi
    return out


def box_decomposition(solid, to_link: np.ndarray, min_volume=120.0) -> list:
    """Approximate a printed part by axis-aligned boxes: slabs between its
    flat levels along the part's own z, one box per connected piece of each
    slab. Works in the part frame, returns (lo, hi) pairs in the link frame."""
    part = model.apply(solid.manifold, np.linalg.inv(to_link))
    mesh = part.to_mesh()
    v, f = np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)
    levels = flat_levels(v, f)
    bb = np.asarray(part.bounding_box()).reshape(2, 3)
    boxes = []
    for z0, z1 in zip(levels[:-1], levels[1:]):
        slab = part ^ model.box([bb[0][0] - 1, bb[0][1] - 1, z0], [bb[1][0] + 1, bb[1][1] + 1, z1])
        for piece in slab.decompose():
            if piece.volume() < min_volume:
                continue
            pb = assembly._tight_bbox(piece)
            corners = np.array([[pb[i][0], pb[j][1], pb[k][2]] for i in (0, 1) for j in (0, 1) for k in (0, 1)])
            world = (to_link[:3, :3] @ corners.T).T + to_link[:3, 3]
            boxes.append((world.min(axis=0), world.max(axis=0)))
    return boxes


def link_shapes(robot: Robot) -> dict:
    """Primitive shapes per link, in mm in the link frame."""
    shapes = {}
    for name, link in robot.links.items():
        items = []
        for solid in link.solids:
            if solid.manifold.is_empty():
                continue
            if solid.kind == "print":
                for lo, hi in box_decomposition(solid, solid.part_to_link):
                    items.append({"type": "box", "kind": "print", "solid": solid.name, "min": lo, "max": hi})
            elif solid.kind == "servo":
                cradle = next(c for c in robot.cradles if c.servo == solid.name)
                s = servo_shape(cradle.model, robot.hardware)
                a = {k: v["value"] for k, v in s.spec["assumed"].items()}
                for lo, hi in (([-s.length / 2, -s.width / 2, 0], [s.length / 2, s.width / 2, s.height]),
                               ([-s.length / 2 - a["ear_overhang_mm"], -s.width / 2, a["ear_bottom_height_mm"]],
                                [s.length / 2 + a["ear_overhang_mm"], s.width / 2, a["ear_bottom_height_mm"] + a["ear_thickness_mm"]])):
                    pts = np.array([model.point(cradle.servo_to_link, p) for p in (lo, hi)])
                    items.append({"type": "box", "kind": "servo", "solid": solid.name, "min": pts.min(axis=0), "max": pts.max(axis=0)})
            elif solid.kind == "horn":
                a = {k: v["value"] for k, v in robot.hardware["servos"][servo_for_joint(link.joint)]["assumed"].items()}
                items.append({"type": "cylinder", "kind": "horn", "solid": solid.name, "from": -link.shaft * a["horn_thickness_mm"],
                              "to": np.zeros(3), "radius": a["horn_radius_mm"]})
            else:
                bb = np.asarray(solid.manifold.bounding_box()).reshape(2, 3)
                items.append({"type": "box", "kind": solid.kind, "solid": solid.name, "min": bb[0], "max": bb[1]})
        shapes[name] = items
    return shapes


def joint_table(robot: Robot, report: dict) -> dict:
    rep = report["variants"][report["selected"]]
    supply = robot.hardware["supply"]["published"]["servo_spec_voltage_used_v"]
    joints = {}
    for name, link in robot.links.items():
        if link.joint is None:
            continue
        servo = servo_for_joint(link.joint)
        pub = robot.hardware["servos"][servo]["published"]
        assumed = robot.hardware["servos"][servo]["assumed"]
        lim = rep["joint_limits_deg"][link.joint]
        torque = pub["torque_kgcm_4v8"] * G / 100.0
        speed = 60.0 / pub["speed_s_per_60deg_4v8"]
        joints[link.joint] = {
            "parent": link.parent, "child": name, "servo": servo,
            "origin_m": [round(float(v) / 1000.0, 6) for v in link.origin],
            "axis": [float(v) for v in link.axis],
            "shaft_direction": [round(float(v), 3) for v in link.shaft],
            "min_deg": lim["min_deg"], "max_deg": lim["max_deg"],
            "min_set_by": lim["min_set_by"], "max_set_by": lim["max_set_by"],
            "torque_limit_nm": round(torque, 4), "speed_limit_deg_s": round(speed, 1),
            "spec_voltage_v": supply,
            "armature_kgm2": assumed["armature_kgm2"]["value"],
        }
    stand = rep["balance"]["stand_pose"]["q_deg"]
    frames = robot.fk(stand)
    sole = min(float((frames[f"{s}_shin"] @ np.r_[p, 1.0])[2]) for s in ("left", "right") for p in assembly.sole_points(robot, s))
    neutral_sole = rep["dimensions"]["sole_z_mm"]
    mass = sum(assembly.link_mass(link)[0] for link in robot.links.values())
    return {"generated_by": "scripts/generate_description.py", "order": JOINTS, "joints": joints,
            "stand_pose_deg": {j: float(stand[j]) for j in JOINTS},
            "stand_torso_height_m": round(-sole / 1000.0, 5),
            "neutral_torso_height_m": round(-neutral_sole / 1000.0, 5),
            "mass_kg": round(mass / 1000.0, 4), "thigh_face": report["selected"]}


def _inertial(link) -> tuple:
    mass, com, inertia = assembly.link_mass(link)
    return mass / 1000.0, com / 1000.0, inertia * 1e-9


def mjcf(robot: Robot, table: dict, shapes: dict, mesh_dir: str | None = None) -> str:
    out = ['<!-- Generated by scripts/generate_description.py. Do not edit. -->',
           '<mujoco model="microduck_braccio_unoq">',
           '  <compiler angle="radian" autolimits="true"' + (f' meshdir="{mesh_dir}"' if mesh_dir else "") + '/>',
           '  <option timestep="0.002" integrator="implicitfast"/>',
           '  <default>',
           f'    <geom friction="{FLOOR_FRICTION} 0.005 0.0001" contype="1" conaffinity="0" density="0"/>',
           '    <default class="visual"><geom contype="0" conaffinity="0" group="1"/></default>',
           '  </default>',
           '  <visual><global offwidth="960" offheight="720"/><headlight ambient="0.45 0.45 0.45" diffuse="0.6 0.6 0.6"/></visual>',
           '  <asset>',
           '    <texture type="skybox" builtin="gradient" rgb1="0.97 0.98 0.97" rgb2="0.80 0.87 0.84" width="64" height="384"/>',
           '    <texture name="grid" type="2d" builtin="checker" rgb1="0.93 0.95 0.94" rgb2="0.84 0.89 0.86" width="256" height="256"/>',
           '    <material name="grid" texture="grid" texrepeat="10 10" reflectance="0.05"/>']
    if mesh_dir:
        for key, filename in model.PART_FILES.items():
            out.append(f'    <mesh name="{key}" file="{filename}" scale="0.001 0.001 0.001"/>')
    out += ['  </asset>', '  <worldbody>',
            '    <light pos="0.6 0.4 1.5" dir="-0.4 -0.3 -1" diffuse="0.5 0.5 0.5"/>',
            f'    <geom name="floor" type="plane" size="2 2 0.05" material="grid" contype="1" conaffinity="1" friction="{FLOOR_FRICTION} 0.005 0.0001"/>']

    def body(name: str, depth: int) -> None:
        link = robot.links[name]
        pad = "  " * depth
        if link.parent is None:
            out.append(f'{pad}<body name="{name}" pos="0 0 {table["neutral_torso_height_m"]}">')
            out.append(f'{pad}  <freejoint name="root"/>')
        else:
            j = table["joints"][link.joint]
            out.append(f'{pad}<body name="{name}" pos="{_f(j["origin_m"])}">')
            damping = j["torque_limit_nm"] / np.radians(j["speed_limit_deg_s"])
            out.append(f'{pad}  <joint name="{link.joint}" type="hinge" axis="{_f(j["axis"])}" '
                       f'range="{_f(np.radians([j["min_deg"], j["max_deg"]]))}" damping="{damping:.5g}" '
                       f'armature="{j["armature_kgm2"]}" frictionloss="{JOINT_FRICTIONLOSS}"/>')
        mass, com, inertia = _inertial(link)
        full = [inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2]]
        out.append(f'{pad}  <inertial pos="{_f(com)}" mass="{mass:.6g}" fullinertia="{_f(full)}"/>')
        for i, shape in enumerate(shapes[name]):
            visual_only = mesh_dir and shape["kind"] == "print"
            extra = ' group="3" rgba="0.9 0.2 0.2 0.25"' if visual_only else f' rgba="{RGBA[shape["kind"]]}"'
            if shape["type"] == "box":
                lo, hi = np.asarray(shape["min"]) / 1000.0, np.asarray(shape["max"]) / 1000.0
                out.append(f'{pad}  <geom name="{name}_{i}" type="box" pos="{_f((lo + hi) / 2)}" size="{_f((hi - lo) / 2)}"{extra}/>')
            else:
                a, b = np.asarray(shape["from"]) / 1000.0, np.asarray(shape["to"]) / 1000.0
                out.append(f'{pad}  <geom name="{name}_{i}" class="visual" type="cylinder" fromto="{_f(np.r_[a, b])}" '
                           f'size="{shape["radius"] / 1000.0:.6g}" rgba="{RGBA["horn"]}"/>')
        if mesh_dir:
            for solid in link.solids:
                if solid.kind == "print":
                    m = solid.part_to_link
                    quat = _quat(m[:3, :3])
                    out.append(f'{pad}  <geom class="visual" type="mesh" mesh="{solid.part}" pos="{_f(m[:3, 3] / 1000.0)}" '
                               f'quat="{_f(quat)}" rgba="{RGBA["print"]}"/>')
        for child, item in robot.links.items():
            if item.parent == name:
                body(child, depth + 1)
        out.append(f'{pad}</body>')

    body("torso", 2)
    out += ['  </worldbody>', '  <actuator>']
    for joint in JOINTS:
        j = table["joints"][joint]
        kp = j["torque_limit_nm"] / np.radians(KP_SATURATION_DEG)
        out.append(f'    <position name="{joint}" joint="{joint}" kp="{kp:.5g}" '
                   f'ctrlrange="{_f(np.radians([j["min_deg"], j["max_deg"]]))}" '
                   f'forcerange="{-j["torque_limit_nm"]} {j["torque_limit_nm"]}"/>')
    out += ['  </actuator>', '  <sensor>']
    for joint in JOINTS:
        out.append(f'    <actuatorfrc name="{joint}_torque" actuator="{joint}"/>')
    stand = np.radians([table["stand_pose_deg"][j] for j in JOINTS])
    out += ['  </sensor>', '  <keyframe>',
            f'    <key name="neutral" qpos="0 0 {table["neutral_torso_height_m"]} 1 0 0 0 0 0 0 0 0 0" ctrl="0 0 0 0 0 0"/>',
            f'    <key name="stand" qpos="0 0 {table["stand_torso_height_m"]} 1 0 0 0 {_f(stand)}" ctrl="{_f(stand)}"/>',
            '  </keyframe>', '</mujoco>']
    return "\n".join(out) + "\n"


def _quat(r: np.ndarray) -> np.ndarray:
    """Rotation matrix to (w, x, y, z)."""
    w = np.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    if w > 1e-6:
        return np.array([w, (r[2, 1] - r[1, 2]) / (4 * w), (r[0, 2] - r[2, 0]) / (4 * w), (r[1, 0] - r[0, 1]) / (4 * w)])
    x = np.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2
    y = np.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2
    z = np.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2
    if x >= y and x >= z:
        return np.array([0, x, np.copysign(y, r[0, 1]), np.copysign(z, r[0, 2])])
    if y >= z:
        return np.array([0, np.copysign(x, r[0, 1]), y, np.copysign(z, r[1, 2])])
    return np.array([0, np.copysign(x, r[0, 2]), np.copysign(y, r[1, 2]), z])


def urdf(robot: Robot, table: dict, shapes: dict) -> str:
    out = ['<?xml version="1.0"?>', '<!-- Generated by scripts/generate_description.py. Do not edit. -->',
           '<robot name="microduck_braccio_unoq">']
    for kind, rgba in RGBA.items():
        out.append(f'  <material name="{kind}"><color rgba="{rgba}"/></material>')
    for name, link in robot.links.items():
        mass, com, inertia = _inertial(link)
        out.append(f'  <link name="{name}">')
        out.append(f'    <inertial><origin xyz="{_f(com)}" rpy="0 0 0"/><mass value="{mass:.6g}"/>'
                   f'<inertia ixx="{inertia[0, 0]:.6g}" ixy="{inertia[0, 1]:.6g}" ixz="{inertia[0, 2]:.6g}" '
                   f'iyy="{inertia[1, 1]:.6g}" iyz="{inertia[1, 2]:.6g}" izz="{inertia[2, 2]:.6g}"/></inertial>')
        for shape in shapes[name]:
            if shape["type"] == "box":
                lo, hi = np.asarray(shape["min"]) / 1000.0, np.asarray(shape["max"]) / 1000.0
                geom = f'<origin xyz="{_f((lo + hi) / 2)}" rpy="0 0 0"/><geometry><box size="{_f(hi - lo)}"/></geometry>'
                out.append(f'    <visual>{geom}<material name="{shape["kind"]}"/></visual>')
                out.append(f'    <collision>{geom}</collision>')
            else:
                a, b = np.asarray(shape["from"]) / 1000.0, np.asarray(shape["to"]) / 1000.0
                axis = (b - a) / np.linalg.norm(b - a)
                rpy = "0 1.570796 0" if abs(axis[0]) > 0.5 else "1.570796 0 0"
                out.append(f'    <visual><origin xyz="{_f((a + b) / 2)}" rpy="{rpy}"/><geometry><cylinder radius="{shape["radius"] / 1000.0:.6g}" '
                           f'length="{np.linalg.norm(b - a):.6g}"/></geometry><material name="horn"/></visual>')
        out.append('  </link>')
    for joint in JOINTS:
        j = table["joints"][joint]
        out.append(f'  <joint name="{joint}" type="revolute">')
        out.append(f'    <parent link="{j["parent"]}"/><child link="{j["child"]}"/>')
        out.append(f'    <origin xyz="{_f(j["origin_m"])}" rpy="0 0 0"/><axis xyz="{_f(j["axis"])}"/>')
        damping = j["torque_limit_nm"] / np.radians(j["speed_limit_deg_s"])
        out.append(f'    <limit lower="{np.radians(j["min_deg"]):.6g}" upper="{np.radians(j["max_deg"]):.6g}" '
                   f'effort="{j["torque_limit_nm"]}" velocity="{np.radians(j["speed_limit_deg_s"]):.6g}"/>')
        out.append(f'    <dynamics damping="{damping:.5g}" friction="{JOINT_FRICTIONLOSS}"/>')
        out.append('  </joint>')
    out.append('</robot>')
    return "\n".join(out) + "\n"


def viewer_model(robot: Robot, table: dict, shapes: dict) -> dict:
    links = []
    for name, link in robot.links.items():
        items = []
        for shape in shapes[name]:
            item = {"type": shape["type"], "kind": shape["kind"]}
            if shape["type"] == "box":
                item["min"] = [round(float(v), 2) for v in shape["min"]]
                item["max"] = [round(float(v), 2) for v in shape["max"]]
            else:
                item["from"] = [round(float(v), 2) for v in shape["from"]]
                item["to"] = [round(float(v), 2) for v in shape["to"]]
                item["radius"] = shape["radius"]
            items.append(item)
        meshes = [{"file": model.PART_FILES[s.part], "matrix": [round(float(v), 6) for v in s.part_to_link.ravel()]}
                  for s in link.solids if s.kind == "print"]
        entry = {"name": name, "parent": link.parent, "shapes": items, "meshes": meshes}
        if link.joint:
            j = table["joints"][link.joint]
            entry.update({"joint": link.joint, "origin_mm": [round(float(v), 3) for v in link.origin],
                          "axis": j["axis"], "min_deg": j["min_deg"], "max_deg": j["max_deg"]})
        links.append(entry)
    return {"generated_by": "scripts/generate_description.py", "units": "mm, degrees", "links": links,
            "stand_pose_deg": table["stand_pose_deg"]}


def generate(write_visual: bool = True) -> dict:
    """Regenerate every description file from the STLs and the report."""
    with open(ROOT / "reports" / "assembly.json", encoding="utf-8") as handle:
        report = json.load(handle)
    robot = model.build_robot(report["selected"])
    table = joint_table(robot, report)
    shapes = link_shapes(robot)
    target = ROOT / "robot"
    target.mkdir(exist_ok=True)
    (target / "joints.json").write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
    (target / "microduck.xml").write_text(mjcf(robot, table, shapes), encoding="utf-8", newline="\n")
    (target / "microduck.urdf").write_text(urdf(robot, table, shapes), encoding="utf-8", newline="\n")
    (target / "model.json").write_text(json.dumps(viewer_model(robot, table, shapes), indent=1) + "\n", encoding="utf-8", newline="\n")
    if write_visual:
        (ROOT / "build").mkdir(exist_ok=True)
        (ROOT / "build" / "microduck_visual.xml").write_text(mjcf(robot, table, shapes, mesh_dir="../stl"), encoding="utf-8", newline="\n")
    return {"boxes": {k: len(v) for k, v in shapes.items()}, "table": table}
