# SPDX-License-Identifier: MIT
"""The Microduck-look build as a kinematic tree of placed solids.

Everything is read from stl/microduck-look/parameters.json, written by the
part generator: the printed parts with the matrix that takes each from its
print orientation to the robot frame, the fifteen joints, where each servo
sits and the boards. Lengths are millimetres, the robot frame is x forward,
y left, z up with the origin of the original's trunk frame.

The code is MIT. The parts and parameters.json are adapted from the
Microduck by Pollen Robotics and carry CC BY-NC-SA 4.0
(stl/microduck-look/LICENSE).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh, OpType

ROOT = Path(__file__).resolve().parents[2]
FOLDER = Path(os.environ.get("MICRODUCK_LOOK_DIR", ROOT / "stl" / "microduck-look"))
COLORS = {"shell": (238, 234, 222), "orange": (240, 150, 45), "frame": (70, 72, 78), "servo": (38, 40, 46),
          "horn": (200, 202, 206), "board": (40, 120, 110), "camera": (30, 90, 160)}
ORANGE_PARTS = ("left_foot", "right_foot", "left_foot_comb", "right_foot_comb", "beak_jaw", "beak_top")
FEET = ("web", "comb")       # the feet as the part generator wrote them; the comb feet of combfeet.py
LEG = ("hip_yaw", "hip_roll", "hip_pitch", "knee", "ankle")
HEAD = ("neck_pitch", "head_pitch", "head_yaw", "head_roll", "beak")
JOINTS = [f"left_{j}" for j in LEG] + [f"right_{j}" for j in LEG] + list(HEAD)


def parameters(folder: Path | None = None) -> dict:
    with open((folder or FOLDER) / "parameters.json", encoding="utf-8") as handle:
        return json.load(handle)


def part_list(folder: Path | None = None, feet: str = "web") -> list:
    """The printed parts of parameters.json, with the comb feet in place of the feet when asked for."""
    folder = folder or FOLDER
    parts = parameters(folder)["parts"]
    if feet == "comb":
        with open(folder / "comb_feet.json", encoding="utf-8") as handle:
            swap = {part["replaces"]: part for part in json.load(handle)["parts"]}
        parts = [swap.get(part["file"], part) for part in parts]
    elif feet != "web":
        raise ValueError(f"feet: {feet}")
    return parts


def have_parts(folder: Path | None = None) -> bool:
    folder = folder or FOLDER
    return (folder / "parameters.json").is_file() and all((folder / p["file"]).is_file() for p in parameters(folder)["parts"])


def from_trimesh(mesh: trimesh.Trimesh) -> Manifold:
    return Manifold(Mesh(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.uint32)))


def to_arrays(solid: Manifold):
    mesh = solid.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts)


def apply(solid: Manifold, matrix) -> Manifold:
    return solid.transform(np.asarray(matrix, float)[:3].tolist())


def box(lo, hi) -> Manifold:
    lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)
    return Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def rotation(anchor, axis, degrees: float) -> np.ndarray:
    """4x4 rotation by an angle about an axis through a point."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    a = np.radians(degrees)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    r = np.eye(3) + np.sin(a) * k + (1.0 - np.cos(a)) * (k @ k)
    out = np.eye(4)
    out[:3, :3] = r
    out[:3, 3] = np.asarray(anchor, float) - r @ np.asarray(anchor, float)
    return out


def servo_solids(spec: dict):
    """Case with ears, and horn with the output boss, in the servo frame (horn face at z = 0, shaft along +z)."""
    bottom = -spec["hf"] - spec["H"]
    case = box([-spec["e"], -spec["W"] / 2, bottom], [spec["L"] - spec["e"], spec["W"] / 2, -spec["hf"]])
    ears = box([-spec["e"] - spec["ear_o"], -spec["W"] / 2, bottom + spec["ear_b"]],
               [spec["L"] - spec["e"] + spec["ear_o"], spec["W"] / 2, bottom + spec["ear_b"] + spec["ear_t"]])
    boss = Manifold.cylinder(spec["hf"] - spec["horn_t"], 0.3 * spec["W"], 0.3 * spec["W"], 32).translate([0, 0, -spec["hf"]])
    horn = Manifold.cylinder(spec["horn_t"], spec["horn_r"], spec["horn_r"], 40).translate([0, 0, -spec["horn_t"]])
    return case + ears + boss, horn


@dataclass
class Solid:
    name: str
    kind: str                 # shell, frame, servo, horn, board, camera
    solid: Manifold           # in the robot frame at the zero pose
    mass_g: float
    colour: tuple
    file: str | None = None


@dataclass
class Link:
    name: str
    parent: str | None = None
    joint: str | None = None
    solids: list = field(default_factory=list)


@dataclass
class Joint:
    name: str
    parent: str
    child: str
    anchor: np.ndarray
    axis: np.ndarray
    original_range: tuple
    servo: str


class Robot:
    def __init__(self, folder: Path | None = None, assignment: dict | None = None, feet: str = "web"):
        self.folder = folder or FOLDER
        self.feet = feet
        self.p = dict(parameters(self.folder), parts=part_list(self.folder, feet))
        self.types = self.p["servo_types"]
        self.floor_z = self.p["floor_z_mm"]
        self.joints = {j["name"]: Joint(j["name"], j["parent"], j["child"], np.array(j["anchor_mm"], float), np.array(j["axis"], float),
                                        tuple(j["original_range_deg"]), j["servo"]) for j in self.p["joints"]}
        self.links = {"trunk": Link("trunk")}
        for j in self.joints.values():
            self.links[j.child] = Link(j.child, j.parent, j.name)
        self.order = ["trunk"] + [self.joints[name].child for name in JOINTS]
        for entry in self.p["parts"]:
            if entry["link"] is None:
                continue
            mesh = trimesh.load_mesh(self.folder / entry["file"])
            solid = apply(from_trimesh(mesh), entry["print_to_robot"])
            name = entry["file"][:-4]
            colour = COLORS["orange"] if name in ORANGE_PARTS else COLORS[entry["kind"]]
            self.links[entry["link"]].solids.append(Solid(name, entry["kind"], solid, entry["mass_g"], colour, entry["file"]))
        for s in self.p["servos"]:
            kind = (assignment or {}).get(s["joint"], s["type"])
            if kind is None:
                continue
            spec = self.types[kind]
            case, horn = servo_solids(self.types[s["type"]])
            # the horn turns with the joint's child; its mass is counted with the case
            self.links[s["link"]].solids.append(Solid(f"{s['joint']}_servo", "servo", apply(case, s["frame"]), spec["mass"], COLORS["servo"]))
            joint = self.joints[s["joint"]]
            other = joint.child if s["link"] == joint.parent else joint.parent
            self.links[other].solids.append(Solid(f"{s['joint']}_horn", "horn", apply(horn, s["frame"]), 0.0, COLORS["horn"]))
            joint.servo = kind
        for e in self.p["electronics"]:
            kind = "camera" if e["link"] == "head" else "board"
            self.links[e["link"]].solids.append(Solid(e["name"], kind, box(*e["box_mm"]), e["mass_g"], COLORS[kind]))

    # -- kinematics --
    def poses(self, q: dict | None = None) -> dict:
        """4x4 of every link for joint angles in degrees (missing joints are zero)."""
        q = q or {}
        out = {"trunk": np.eye(4)}
        for name in self.order[1:]:
            link = self.links[name]
            joint = self.joints[link.joint]
            out[name] = out[link.parent] @ rotation(joint.anchor, joint.axis, q.get(joint.name, 0.0))
        return out

    def placed(self, q: dict | None = None, kinds=None) -> list:
        """(link, Solid, manifold in the robot frame) for every solid."""
        poses = self.poses(q)
        return [(name, s, apply(s.solid, poses[name])) for name in self.order for s in self.links[name].solids
                if kinds is None or s.kind in kinds]

    def subtree(self, link: str) -> list:
        out = [link]
        for name in self.order:
            if self.links[name].parent in out and name not in out:
                out.append(name)
        return out

    # -- mass --
    def _props(self, s: Solid):
        """Centre of mass (mm) and inertia about it (g mm2) of one solid at the zero pose, uniform density."""
        if not hasattr(s, "_com"):
            v, f = to_arrays(s.solid)
            mesh = trimesh.Trimesh(v, f, process=False)
            mesh.density = s.mass_g / max(float(mesh.volume), 1e-9)
            s._com = np.asarray(mesh.center_mass, float)
            s._inertia = np.asarray(mesh.moment_inertia, float)
        return s._com, s._inertia

    def masses(self, q: dict | None = None) -> list:
        """(link, solid name, kg, centre of mass in metres) for every solid with mass."""
        poses = self.poses(q)
        out = []
        for name in self.order:
            for s in self.links[name].solids:
                if s.mass_g <= 0.0:
                    continue
                com = self._props(s)[0]
                out.append((name, s.name, s.mass_g / 1000.0, (poses[name][:3, :3] @ com + poses[name][:3, 3]) / 1000.0))
        return out

    def link_inertial(self, name: str) -> tuple:
        """Mass (g), centre of mass (mm) and inertia about it (g mm2) of a link at the zero pose."""
        rows = [(s.mass_g, *self._props(s)) for s in self.links[name].solids if s.mass_g > 0.0]
        mass = sum(r[0] for r in rows)
        com = sum(r[0] * r[1] for r in rows) / mass
        inertia = np.zeros((3, 3))
        for m, c, i in rows:
            d = c - com
            inertia += i + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
        return mass, com, inertia

    def mass_kg(self) -> float:
        return float(sum(s.mass_g for name in self.order for s in self.links[name].solids)) / 1000.0

    def com(self, q: dict | None = None, links=None) -> tuple:
        rows = [r for r in self.masses(q) if links is None or r[0] in links]
        total = sum(r[2] for r in rows)
        return total, sum(r[2] * r[3] for r in rows) / total


def union(solids) -> Manifold:
    solids = list(solids)
    return Manifold.batch_boolean(solids, OpType.Add) if solids else Manifold()
