# SPDX-License-Identifier: MIT
"""Generate a MuJoCo model of each crank walker from the assembly model.

    python -m walkers.mjcf          writes robot/lego/<build>.xml and robot/lego/<build>.json

The closed linkage is modelled as it is built. On each side the rear crank is
a hinge on the chassis driven by the motor; the leg hangs from the rear crank
tip on a second hinge; the front crank is a third hinge on the chassis. Two
equality constraints close the loop: a connect constraint pins the front
crank tip to the leg (the second pivot), and a joint constraint ties the
front crank angle to the rear one (the three equal gears, ratio +1). The gear
constraint is what carries the linkage through its two change points, where
the cranks lie along the leg's pivot row and the pin constraint alone cannot
tell which way the front crank should go. Gear backlash is not modelled.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import trimesh
from scipy.spatial import ConvexHull

from . import model
from .model import AXLES_X, BUILDS, CRANK_R, LEG_DROP, LEG_Y, ROOT, Walker, build_walker

OUT = ROOT / "robot" / "lego"
CRANK_Y = 70.0          # crank body plane
START_PHASE = 90.0      # left foot down, mid stance
JOINT_FRICTION_NM = 0.004   # assumed: bearings and gear mesh, per crank joint
MM = 0.001


def _box_inertia(mass, size):
    x, y, z = size
    return mass / 12.0 * np.diag([y * y + z * z, x * x + z * z, x * x + y * y])


def _item_inertia(item, phase=START_PHASE):
    """Mass (kg), centre (m) and inertia about the centre (kg m2), body frame."""
    mass = item.mass_g / 1000.0
    pose = item.pose(phase)
    com = (pose @ np.append(item.com, 1.0))[:3] * MM
    if item.solid is None or mass == 0.0:
        return mass, com, np.zeros((3, 3))
    if item.part:
        mesh = model.part_mesh(item_build[0], item.part)
        inertia = np.asarray(mesh.moment_inertia) / mesh.volume * mass * MM * MM
    else:
        b = item.solid.bounding_box()
        inertia = _box_inertia(mass, (np.array(b[3:]) - np.array(b[:3])) * MM)
    r = pose[:3, :3]
    return mass, com, r @ inertia @ r.T


item_build = [BUILDS[0]]


def _combine(parts):
    mass = sum(p[0] for p in parts)
    com = sum(p[0] * p[1] for p in parts) / mass
    inertia = np.zeros((3, 3))
    for m, c, i in parts:
        d = c - com
        inertia += i + m * (d @ d * np.eye(3) - np.outer(d, d))
    return mass, com, inertia


def _inertial(mass, com, inertia, origin=(0, 0, 0)) -> str:
    c = com - np.asarray(origin, float)
    i = inertia
    return (f'<inertial pos="{c[0]:.5f} {c[1]:.5f} {c[2]:.5f}" mass="{mass:.5f}" '
            f'fullinertia="{i[0, 0]:.3e} {i[1, 1]:.3e} {i[2, 2]:.3e} {i[0, 1]:.3e} {i[0, 2]:.3e} {i[1, 2]:.3e}"/>')


def _stadium(a, b, r, n=10):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([np.cos(ang), np.sin(ang)], axis=1) * r
    pts = np.vstack([a + ring, b + ring])
    return pts[ConvexHull(pts).vertices]


def foot_pieces(build: str, side: str) -> dict:
    """Convex pieces of a foot in the leg STL frame (mm): the sole and the
    two bars of each finger, as 2D outlines of 5 mm thick prisms."""
    mesh = model.part_mesh(build, f"{side}_leg")
    sign = 1.0 if side == "left" else -1.0
    low = mesh.vertices[mesh.vertices[:, 2] < 0.01][:, :2]
    sole = low[(low[:, 0] >= -36.01) & (low[:, 0] <= 44.01) & (sign * low[:, 1] >= -60.51)]
    pieces = {"sole": sole[ConvexHull(sole).vertices]}
    reach = 70.0 if side == "left" else 27.0
    for label, s in (("rear", -1.0), ("front", 1.0)):
        pieces[f"{label}_link"] = _stadium((s * 17, sign * -12), (s * reach, sign * -18), 5.0)
        pieces[f"{label}_finger"] = _stadium((s * reach, sign * -18), (s * reach, sign * -80.5), 5.0)
    return pieces


def _prism_vertices(outline, z0, z1, offset) -> str:
    pts = [(x + offset[0], y + offset[1], z + offset[2]) for z in (z0, z1) for x, y in outline]
    return " ".join(f"{v * MM:.5f}" for p in pts for v in p)


def _viewer(walker: Walker, spec: dict) -> dict:
    """What the site's 3D view needs: where each STL goes, how it moves, and
    the bought parts as boxes. Lengths in mm, matrices row-major."""
    printed, boxes = [], []
    for item in walker.items:
        if item.part:
            printed.append({"name": item.name, "file": f"lego/{walker.build}/{item.part}.stl",
                            "matrix": [round(float(v), 4) for v in item.matrix.flatten()],
                            "motion": list(item.motion) if item.motion else None})
        elif item.solid is not None and item.kind == "motor":
            flip = -1.0 if walker.options["motor_direction"] == "rear" else 1.0
            origin = item.matrix[:3, 3]
            for lo, hi in (spec["envelope"]["hub"], spec["envelope"]["body"]):
                a, b = np.array(lo, float) * [flip, 1, 1] + origin, np.array(hi, float) * [flip, 1, 1] + origin
                boxes.append({"name": item.name, "kind": "motor", "min": np.minimum(a, b).round(2).tolist(),
                              "max": np.maximum(a, b).round(2).tolist()})
        elif item.solid is not None and item.kind in ("controller", "camera"):
            b = item.placed().bounding_box()
            boxes.append({"name": item.name, "kind": item.kind, "min": [round(v, 2) for v in b[:3]],
                          "max": [round(v, 2) for v in b[3:]]})
    return {"printed": printed, "boxes": boxes, "crank_radius_mm": CRANK_R, "leg_drop_mm": LEG_DROP,
            "stride_per_turn_mm": model.STRIDE}


def generate(build: str, visual_meshes: bool = True, **options) -> tuple:
    item_build[0] = build
    walker = build_walker(build, **options)
    comp = walker.components
    spec = comp["ev3_large_motor"] if build == "ev3-pixy2" else comp["angular_motor"]
    fixed = [i for i in walker.items if i.motion is None and i.mass_g > 0]
    chassis = _combine([_item_inertia(i) for i in fixed])
    name = build.replace("-", "_")
    height = -model.ground_z(START_PHASE) * MM
    mu = comp["floor"]["friction"]["value"]
    head_part = walker.item("head").part

    x = []
    x.append(f'<mujoco model="lego_walker_{name}">')
    x.append("  <!-- SPDX-License-Identifier: MIT -->")
    x.append("  <!-- Generated by python -m walkers.mjcf; do not edit. Units: m, kg, rad. -->")
    x.append(f'  <compiler angle="radian" meshdir="../../stl/lego/{build}"/>')
    x.append('  <option timestep="0.001" integrator="implicitfast" cone="elliptic" impratio="5"/>')
    x.append('  <size memory="20M"/>')
    x.append("  <default>")
    x.append('    <joint damping="0.0002" armature="0.00001"/>')
    x.append(f'    <geom contype="1" conaffinity="0" friction="{mu} 0.005 0.0001" solref="0.004 1" condim="3"/>')
    x.append('    <default class="visual"><geom contype="0" conaffinity="0" group="1" rgba="0.93 0.78 0.47 1"/></default>')
    x.append('    <default class="bought"><geom contype="0" conaffinity="0" group="1" type="box"/></default>')
    x.append("  </default>")
    x.append("  <asset>")
    if visual_meshes:
        for part in ("chassis", head_part, "left_leg", "right_leg", "crank_print_4", "gear_16t_print_6"):
            x.append(f'    <mesh name="{part}" file="{part}.stl" scale="0.001 0.001 0.001"/>')
    for side in ("left", "right"):
        for piece, outline in foot_pieces(build, side).items():
            sign = 1.0 if side == "left" else -1.0
            offset = (16.0, sign * (LEG_Y - CRANK_Y), -LEG_DROP)
            x.append(f'    <mesh name="{side}_{piece}" vertex="{_prism_vertices(outline, 0.0, 5.0, offset)}"/>')
    x.append('    <texture name="grid" type="2d" builtin="checker" rgb1="0.86 0.9 0.87" rgb2="0.8 0.85 0.82" width="256" height="256"/>')
    x.append('    <material name="grid" texture="grid" texrepeat="20 20" reflectance="0"/>')
    x.append("  </asset>")
    x.append("  <visual><headlight ambient=\"0.5 0.5 0.5\" diffuse=\"0.6 0.6 0.6\"/><global offwidth=\"640\" offheight=\"480\"/></visual>")
    x.append("  <worldbody>")
    x.append('    <light pos="0.3 -0.4 1.2" dir="-0.2 0.3 -1" diffuse="0.5 0.5 0.5"/>')
    x.append('    <geom name="floor" type="plane" size="4 4 0.1" contype="0" conaffinity="1" material="grid"/>')
    # The step is a mocap body so an experiment can place it; it starts out of the way.
    x.append('    <body name="step" mocap="true" pos="0 0 -1"><geom name="step" type="box" size="0.5 0.5 0.05" contype="0" conaffinity="1" rgba="0.6 0.45 0.3 1"/></body>')
    x.append(f'    <body name="chassis" pos="0 0 {height:.5f}">')
    x.append('      <freejoint name="root"/>')
    x.append("      " + _inertial(*chassis))
    if visual_meshes:
        x.append('      <geom class="visual" type="mesh" mesh="chassis"/>')
        x.append(f'      <geom class="visual" type="mesh" mesh="{head_part}" pos="{model.HEAD_X * MM} 0 {model.SHELF_TOP * MM}"/>')
    for item in fixed:
        if item.solid is None or item.kind == "print":
            continue
        b = np.array(item.placed().bounding_box()) * MM
        centre, half = (b[:3] + b[3:]) / 2, (b[3:] - b[:3]) / 2
        if item.kind == "motor":       # hub and body boxes
            env = spec["envelope"]
            flip = -1.0 if walker.options["motor_direction"] == "rear" else 1.0
            origin = item.matrix[:3, 3]
            for lo, hi in (env["hub"], env["body"]):
                lo, hi = np.array(lo, float), np.array(hi, float)
                c = (lo + hi) / 2 * [flip, 1, 1] + origin
                h = (hi - lo) / 2
                x.append(f'      <geom class="bought" pos="{c[0] * MM:.4f} {c[1] * MM:.4f} {c[2] * MM:.4f}" '
                         f'size="{h[0] * MM:.4f} {h[1] * MM:.4f} {h[2] * MM:.4f}" rgba="0.6 0.62 0.65 1"/>')
            continue
        colour = "0.28 0.47 0.67 1" if item.kind == "controller" else "0.25 0.6 0.43 1"
        x.append(f'      <geom class="bought" name="{item.name.replace(" ", "_")}" pos="{centre[0]:.4f} {centre[1]:.4f} {centre[2]:.4f}" '
                 f'size="{half[0]:.4f} {half[1]:.4f} {half[2]:.4f}" rgba="{colour}"/>')
    # What can hit the floor if the robot tips: the deck, the panels, the head.
    x.append('      <geom name="deck_hit" type="box" pos="0.019 0 0.0165" size="0.084 0.058 0.0285" rgba="0 0 0 0"/>')
    x.append(f'      <geom name="head_hit" type="box" pos="{(model.HEAD_X + 2) * MM} 0 {(model.SHELF_TOP + 35) * MM}" size="0.03 0.028 0.035" rgba="0 0 0 0"/>')
    for name in ("EV3 brick", "51515 hub"):
        if not any(i.name == name for i in walker.items):
            continue
        b = np.array(walker.item(name).placed().bounding_box()) * MM
        c, h = (b[:3] + b[3:]) / 2, (b[3:] - b[:3]) / 2
        x.append(f'      <geom name="brick_hit" type="box" pos="{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}" size="{h[0]:.4f} {h[1]:.4f} {h[2]:.4f}" rgba="0 0 0 0"/>')
    rotor = spec["rotor_inertia_kgm2"]["value"]
    for side, sign in (("left", 1.0), ("right", -1.0)):
        y = sign * CRANK_Y * MM
        crank = walker.item(f"{side} rear crank")
        gear = walker.item(f"{side} rear gear")
        crank_mass = (crank.mass_g + gear.mass_g + 1.0) / 1000.0
        crank_inertia = f'<inertial pos="0.004 0 0" mass="{crank_mass:.5f}" diaginertia="2e-7 4e-7 4e-7"/>'
        mesh_y = (3.8 if sign > 0 else 4.0) * MM
        quat = "0.70711 0.70711 0 0"
        leg = walker.item(f"{side} leg")
        mesh = model.part_mesh(build, leg.part)
        leg_mass = leg.mass_g / 1000.0
        leg_offset = np.array([16.0, sign * (LEG_Y - CRANK_Y), -LEG_DROP])
        leg_com = (np.asarray(mesh.center_mass) + leg_offset) * MM
        leg_inertia = np.asarray(mesh.moment_inertia) / mesh.volume * leg_mass * MM * MM
        x.append(f'      <body name="{side}_rear_crank" pos="{AXLES_X[0] * MM} {y:.4f} 0">')
        x.append(f'        <joint name="{side}_rear_crank" type="hinge" axis="0 1 0" armature="{rotor}" frictionloss="{JOINT_FRICTION_NM}"/>')
        x.append("        " + crank_inertia)
        if visual_meshes:
            x.append(f'        <geom class="visual" type="mesh" mesh="crank_print_4" pos="0 {mesh_y:.4f} 0" quat="{quat}" rgba="0.85 0.4 0.3 1"/>')
        x.append(f'        <body name="{side}_leg" pos="{CRANK_R * MM} 0 0">')
        x.append(f'          <joint name="{side}_leg_pivot" type="hinge" axis="0 1 0"/>')
        x.append("          " + _inertial(leg_mass, leg_com, leg_inertia))
        if visual_meshes:
            x.append(f'          <geom class="visual" type="mesh" mesh="{side}_leg" pos="{leg_offset[0] * MM:.4f} {leg_offset[1] * MM:.4f} {leg_offset[2] * MM:.4f}"/>')
        for piece in foot_pieces(build, side):
            x.append(f'          <geom name="{side}_{piece}" type="mesh" mesh="{side}_{piece}" rgba="0.93 0.78 0.47 {0 if visual_meshes else 1}"/>')
        x.append("        </body>")
        x.append("      </body>")
        x.append(f'      <body name="{side}_front_crank" pos="{AXLES_X[2] * MM} {y:.4f} 0">')
        x.append(f'        <joint name="{side}_front_crank" type="hinge" axis="0 1 0" frictionloss="{JOINT_FRICTION_NM}"/>')
        x.append("        " + crank_inertia)
        if visual_meshes:
            x.append(f'        <geom class="visual" type="mesh" mesh="crank_print_4" pos="0 {mesh_y:.4f} 0" quat="{quat}" rgba="0.85 0.4 0.3 1"/>')
        x.append("      </body>")
    x.append("    </body>")
    x.append("  </worldbody>")
    x.append("  <equality>")
    for side in ("left", "right"):
        x.append(f'    <connect name="{side}_front_pivot" body1="{side}_front_crank" body2="{side}_leg" anchor="{CRANK_R * MM} 0 0" solref="0.002 1"/>')
        x.append(f'    <joint name="{side}_gear_train" joint1="{side}_front_crank" joint2="{side}_rear_crank" polycoef="0 1 0 0 0" solref="0.002 1"/>')
    x.append("  </equality>")
    stall = spec["stall_torque_nm"]["value"]
    x.append("  <actuator>")
    for side in ("left", "right"):
        x.append(f'    <motor name="{side}_motor" joint="{side}_rear_crank" gear="1" ctrllimited="true" ctrlrange="{-stall} {stall}"/>')
    x.append("  </actuator>")
    x.append("</mujoco>")
    meta = {
        "build": build, "options": walker.options, "mass_kg": round(walker.mass_g() / 1000.0, 4),
        "start_phase_deg": START_PHASE, "start_height_m": round(height, 5),
        "crank_radius_m": CRANK_R * MM, "stride_per_turn_m": model.STRIDE * MM,
        "motor": {"name": spec["name"], "stall_torque_nm": stall, "running_torque_nm": spec["running_torque_nm"]["value"],
                  "no_load_rpm": spec["no_load_rpm"]["value"], "gear_ratio_motor_to_crank": 1.0,
                  "rotor_inertia_kgm2": rotor, "joint_friction_nm": JOINT_FRICTION_NM},
        "floor_friction": mu,
        "closed_loop": "connect constraint at the front crank tip plus a joint constraint for the gear train, per side",
        "viewer": _viewer(walker, spec),
    }
    return "\n".join(x) + "\n", meta


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for build in BUILDS:
        xml, meta = generate(build)
        (OUT / f"{build}.xml").write_text(xml, encoding="utf-8", newline="\n")
        (OUT / f"{build}.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"robot/lego/{build}.xml  {meta['mass_kg']} kg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
