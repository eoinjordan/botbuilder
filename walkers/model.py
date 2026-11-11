# SPDX-License-Identifier: MIT
"""Geometry of the two crank walkers: printed parts from stl/lego/, bought
parts as boxes from walkers/config/components.json, and the crank kinematics.

Frame: x forward, y left, z up, origin on the centre axle midway between the
side panels (the frame the parts were designed in). Lengths in mm, masses in g.

The crank phase is the rotation of the left cranks about +y, in degrees, from
the position where they point forward. The right cranks are half a turn
ahead. Phase increasing walks the robot forward.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh
from scipy.spatial import ConvexHull

ROOT = Path(__file__).resolve().parents[1]
STL = ROOT / "stl" / "lego"
CONFIG = Path(__file__).resolve().parent / "config"
BUILDS = ("ev3-pixy2", "pi-zero-2w-51515")
TITLES = {"ev3-pixy2": "EV3 brick, two large motors, Pixy2",
          "pi-zero-2w-51515": "Raspberry Pi Zero 2 W, Build HAT, two 51515 motors"}

CRANK_R = 12.0                      # crank radius
AXLES_X = (-16.0, 0.0, 16.0)        # rear, centre (idler), front
PIVOT_SPACING = 32.0
LEG_Y = 75.0                        # inner face of each leg from the centreline
LEG_DROP = 84.0                     # leg pivot row above the sole
PANEL_IN, PANEL_OUT = 50.2, 58.0
DECK_TOP = 42.0
SHELF_TOP = 45.8
HEAD_X = 84.0
GEAR_T = 5.0
GEAR_GAP = 1.0                      # gear face to the panel's inner face
CRANK_T = 7.8
CRANK_OUT = 8.0                     # crank inner face outboard of the panel
STRIDE = 4 * CRANK_R                # ideal travel per crank turn, both feet


def load_json(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as handle:
        return json.load(handle)


def have_stls() -> bool:
    return all((STL / b / "chassis.stl").is_file() for b in BUILDS)


def trans(x, y, z) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def rot(axis: str, degrees: float) -> np.ndarray:
    c, s = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    m = np.eye(4)
    if axis == "x":
        m[1:3, 1:3] = [[c, -s], [s, c]]
    elif axis == "y":
        m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    else:
        m[:2, :2] = [[c, -s], [s, c]]
    return m


def mirror_x() -> np.ndarray:
    return np.diag([-1.0, 1.0, 1.0, 1.0])


def apply(solid: Manifold, matrix: np.ndarray) -> Manifold:
    return solid.transform(np.asarray(matrix, float)[:3, :])


def manifold_of(mesh: trimesh.Trimesh) -> Manifold:
    return Manifold(Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                         tri_verts=np.asarray(mesh.faces, np.uint32)))


def arrays(solid: Manifold):
    mesh = solid.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts).astype(int)


def box(lo, hi) -> Manifold:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def cylinder_y(radius: float, y0: float, y1: float, x: float = 0.0, z: float = 0.0) -> Manifold:
    return Manifold.cylinder(y1 - y0, radius, radius, 48).rotate([-90.0, 0.0, 0.0]).translate([x, y0, z])


_MESHES: dict = {}


def part_mesh(build: str, name: str) -> trimesh.Trimesh:
    key = (build, name)
    if key not in _MESHES:
        _MESHES[key] = trimesh.load_mesh(STL / build / f"{name}.stl")
    return _MESHES[key]


def leg_shift(side: str, phase_deg: float) -> np.ndarray:
    """Offset of a leg from its mid position at a crank phase."""
    a = np.radians(phase_deg)
    shift = np.array([CRANK_R * np.cos(a), 0.0, -CRANK_R * np.sin(a)])
    return shift if side == "left" else -shift


def crank_angle(side: str, phase_deg: float) -> float:
    return phase_deg if side == "left" else phase_deg + 180.0


def stance(phase_deg: float, tolerance_mm: float = 0.3) -> tuple:
    """Which feet are on the ground: the lower one, or both when level."""
    dz = leg_shift("left", phase_deg)[2] - leg_shift("right", phase_deg)[2]
    if abs(dz) <= tolerance_mm:
        return ("left", "right")
    return ("left",) if dz < 0 else ("right",)


def ground_z(phase_deg: float) -> float:
    return -LEG_DROP + min(leg_shift("left", phase_deg)[2], leg_shift("right", phase_deg)[2])


@dataclass
class Item:
    name: str
    kind: str                       # print, motor, controller, camera, technic, ballast
    mass_g: float
    com: np.ndarray                 # in the item's own frame
    solid: Manifold | None = None   # in the item's own frame; None for a lumped mass
    matrix: np.ndarray = field(default_factory=lambda: np.eye(4))
    motion: tuple | None = None     # ("leg", side) or ("crank", side, axle_x)
    source: str = ""                # where the mass comes from
    part: str | None = None         # STL name for printed parts

    def pose(self, phase_deg: float = 90.0) -> np.ndarray:
        if self.motion is None:
            return self.matrix
        if self.motion[0] == "leg":
            side = self.motion[1]
            return trans(*leg_shift(side, phase_deg)) @ self.matrix
        _, side, axle_x, y0 = self.motion
        return trans(axle_x, y0, 0.0) @ rot("y", crank_angle(side, phase_deg)) @ rot("x", 90.0)

    def placed(self, phase_deg: float = 90.0) -> Manifold:
        return apply(self.solid, self.pose(phase_deg))

    def com_world(self, phase_deg: float = 90.0) -> np.ndarray:
        return (self.pose(phase_deg) @ np.append(self.com, 1.0))[:3]


@dataclass
class Walker:
    build: str
    options: dict
    items: list
    components: dict
    notes: list

    def mass_g(self) -> float:
        return float(sum(i.mass_g for i in self.items))

    def com(self, phase_deg: float = 90.0) -> np.ndarray:
        total = np.zeros(3)
        for item in self.items:
            total += item.mass_g * item.com_world(phase_deg)
        return total / self.mass_g()

    def foot_polygon(self, side: str, phase_deg: float) -> np.ndarray:
        """Convex outline of a sole on the ground, body frame, counter-clockwise."""
        mesh = part_mesh(self.build, f"{side}_leg")
        low = mesh.vertices[mesh.vertices[:, 2] < 0.01][:, :2]
        hull = low[ConvexHull(low).vertices]
        sign = 1.0 if side == "left" else -1.0
        return hull + [0.0, sign * LEG_Y] + leg_shift(side, phase_deg)[:2]

    def support_polygon(self, phase_deg: float) -> np.ndarray:
        points = np.vstack([self.foot_polygon(s, phase_deg) for s in stance(phase_deg)])
        return points[ConvexHull(points).vertices]

    def item(self, name: str) -> Item:
        return next(i for i in self.items if i.name == name)


def margin(polygon: np.ndarray, point) -> float:
    """Signed distance from a point to the edge of a convex counter-clockwise
    polygon: positive inside."""
    p = np.asarray(point, float)[:2]
    a = polygon
    b = np.roll(polygon, -1, axis=0)
    edge = b - a
    normal = np.stack([edge[:, 1], -edge[:, 0]], axis=1)        # outward for counter-clockwise
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    return float(-np.max(((p - a) * normal).sum(axis=1)))


def _printed(build: str, name: str, part: str, printing: dict, matrix=None, motion=None, kind="print") -> Item:
    mesh = part_mesh(build, part)
    mass = mesh.volume / 1000.0 * printing["density_g_cm3"]["value"] * printing["solid_fraction"]["value"]
    return Item(name, kind, float(mass), np.asarray(mesh.center_mass, float), manifold_of(mesh),
                np.eye(4) if matrix is None else matrix, motion, "volume x density x solid fraction (assumed)", part)


def _bought(name: str, kind: str, mass: float, lo, hi, source: str) -> Item:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return Item(name, kind, float(mass), (lo + hi) / 2.0, box(lo, hi), source=source)


def _lump(name: str, kind: str, mass: float, at, source: str) -> Item:
    return Item(name, kind, float(mass), np.asarray(at, float), None, source=source)


def motor_item(name: str, spec: dict, direction: str, y_centre: float, axle_x: float = AXLES_X[0]) -> Item:
    env = spec["envelope"]
    solid = box(*env["hub"]) + box(*env["body"])
    lo = np.minimum(env["hub"][0], env["body"][0])
    hi = np.maximum(env["hub"][1], env["body"][1])
    # Centre of mass at the middle of the body box: the motor and gears are there.
    com = (np.asarray(env["body"][0], float) + np.asarray(env["body"][1], float)) / 2.0
    matrix = trans(axle_x, y_centre, 0.0) @ (mirror_x() if direction == "rear" else np.eye(4))
    if direction == "rear":
        solid = apply(solid, mirror_x())
        com = com * [-1.0, 1.0, 1.0]
    item = Item(name, "motor", spec["mass_g"]["value"], com, solid, trans(axle_x, y_centre, 0.0),
                source=f"{spec['mass_g']['class']}")
    item.envelope = (lo, hi)
    return item


DEFAULTS = {
    "ev3-pixy2": {"motor_direction": "rear", "camera": "pantilt", "brick_x": 0.0, "battery": "six AA"},
    "pi-zero-2w-51515": {"motor_direction": "rear", "camera": "camera_module_2", "ballast_g": 0.0, "ballast_x": 0.0},
}


def build_walker(build: str, **overrides) -> Walker:
    comp = load_json("components.json")
    printing = comp["printing"]
    options = {**DEFAULTS[build], **overrides}
    items, notes = [], []
    ev3 = build == "ev3-pixy2"

    items.append(_printed(build, "chassis", "chassis", printing))
    head_part = "camera_head_pantilt" if (ev3 and options["camera"] == "pantilt") else "camera_head"
    items.append(_printed(build, "head", head_part, printing, trans(HEAD_X, 0.0, SHELF_TOP)))
    notes.append("Head fixed: pinned through its two holes 32 mm apart to the shelf holes at x = 84, y = +/-16. "
                 "The optional pan motor under the shelf is not modelled.")
    for side, sign in (("left", 1.0), ("right", -1.0)):
        items.append(_printed(build, f"{side} leg", f"{side}_leg", printing,
                              trans(0.0, sign * LEG_Y, -LEG_DROP), ("leg", side)))
        y_gear = PANEL_IN - GEAR_GAP if sign > 0 else -(PANEL_IN - GEAR_GAP) + GEAR_T
        for label, x in zip(("rear", "centre", "front"), AXLES_X):
            items.append(_printed(build, f"{side} {label} gear", "gear_16t_print_6", printing,
                                  trans(x, y_gear, 0.0) @ rot("x", 90.0)))
        y_crank = PANEL_OUT + CRANK_OUT + CRANK_T if sign > 0 else -(PANEL_OUT + CRANK_OUT)
        for label, x in (("rear", AXLES_X[0]), ("front", AXLES_X[2])):
            items.append(_printed(build, f"{side} {label} crank", "crank_print_4", printing,
                                  motion=("crank", side, x, y_crank)))
        # The idler axle is held by one bush outboard of the panel, under the cranks' sweep.
        bush = comp["technic"]["bush_length_mm"]["value"]
        y0, y1 = (PANEL_OUT, PANEL_OUT + bush) if sign > 0 else (-PANEL_OUT - bush, -PANEL_OUT)
        items.append(Item(f"{side} idler axle bush", "technic", 0.0, np.array([0.0, (y0 + y1) / 2, 0.0]),
                          cylinder_y(3.7, y0, y1), source="geometry only"))
        items.append(_lump(f"{side} axles, bushes and pins", "technic", comp["technic"]["hardware_per_side_g"]["value"],
                           (0.0, sign * 62.0, 0.0), "assumed"))
    notes.append("Gears inside each panel with 1 mm to the panel face, all three in one plane.")
    notes.append("Cranks 8 mm outboard of the panel, legs outside the cranks with their inner faces 75 mm from the "
                 "centreline: 1.2 mm between crank and leg.")
    notes.append("The idler axle is retained by one full bush outboard of the panel; the cranks sweep past its end.")

    direction = options["motor_direction"]
    if ev3:
        spec = comp["ev3_large_motor"]
        y_motor = 30.0 if direction == "rear" else 23.5
    else:
        spec = comp["angular_motor"]
        y_motor = 31.0
    for side, sign in (("left", 1.0), ("right", -1.0)):
        items.append(motor_item(f"{side} motor", spec, direction, sign * y_motor))
        bracket_at = items[-1].com_world()
        items.append(_lump(f"{side} motor bracket", "technic", comp["technic"]["motor_bracket_g"]["value"],
                           bracket_at, "assumed"))
    notes.append(f"Motors between the panels, output hub on the rear gear axle (x = -16), body pointing "
                 f"{'backward' if direction == 'rear' else 'forward'}, centred {y_motor:g} mm from the centreline. "
                 "The README says only: one motor per side on the rear gear axle, held by stock beams.")

    if ev3:
        brick = comp["ev3_brick"]
        size = brick["size_mm"]["value"]
        cells = brick["mass_six_aa_g"]["value"] if options["battery"] == "six AA" else brick["mass_rechargeable_pack_g"]["value"]
        x = options["brick_x"]
        items.append(_bought("EV3 brick", "controller", brick["mass_bare_g"]["value"] + cells,
                             (x - size[0] / 2, -size[1] / 2, DECK_TOP), (x + size[0] / 2, size[1] / 2, DECK_TOP + size[2]),
                             f"assumed ({options['battery']})"))
        notes.append(f"Brick flat on the deck, long side fore and aft between the two rows of strap slots, centred at "
                     f"x = {x:g}. The README says only: strapped across the deck through the four slots.")
        if options["camera"] == "pantilt":
            kit = comp["pixy2_pan_tilt"]
            k = kit["size_mm"]["value"]
            z0 = SHELF_TOP + 70.0
            items.append(_bought("pan-tilt kit", "camera", kit["mass_g"]["value"],
                                 (HEAD_X + 8 - k[0] / 2, -k[1] / 2, z0), (HEAD_X + 8 + k[0] / 2, k[1] / 2, z0 + k[2] - 20),
                                 "assumed"))
            p = comp["pixy2"]["size_mm"]["value"]
            items.append(_bought("Pixy2", "camera", comp["pixy2"]["mass_g"]["value"],
                                 (HEAD_X + 20, -p[1] / 2, z0 + k[2] - 20), (HEAD_X + 20 + p[0], p[1] / 2, z0 + k[2] - 20 + p[2]),
                                 "maker"))
            notes.append("Pan-tilt kit on the head's top platform with the Pixy2 on its tilt bracket; kit size and "
                         "mass are assumed.")
        else:
            p = comp["pixy2"]["size_mm"]["value"]
            x0 = HEAD_X + 31.8 + 8.0
            items.append(_bought("Pixy2", "camera", comp["pixy2"]["mass_g"]["value"] + comp["pixy2"]["lego_brackets_g"]["value"],
                                 (x0, -p[1] / 2, SHELF_TOP + 55 - p[2] / 2), (x0 + p[0], p[1] / 2, SHELF_TOP + 55 + p[2] / 2),
                                 "maker, brackets assumed"))
            notes.append("Pixy2 on its LEGO-edition brackets 8 mm in front of the perforated face.")
    else:
        zero = comp["pi_zero_2w"]
        hat = comp["build_hat"]
        z0 = 47.0
        items.append(_bought("Pi Zero 2 W", "controller", zero["mass_g"]["value"] + zero["header_and_spacers_g"]["value"],
                             (-32.5, -15.0, z0), (32.5, 15.0, z0 + 1.5), "third-party, header assumed"))
        zh = z0 + 1.5 + hat["spacer_mm"]["value"]
        items.append(_bought("Build HAT", "controller", hat["mass_g"]["value"],
                             (-32.5, 15.0 - 56.5, zh), (32.5, 15.0, zh + 12.0), "assumed"))
        notes.append("Pi Zero 2 W on the four bosses, header along the left edge, Build HAT on 9 mm spacers above it "
                     "overhanging 26.5 mm to the right. Which way round the Pi sits is not stated in the README.")
        cam = comp["camera_module_2"]
        items.append(_bought("Camera Module 2", "camera", cam["mass_g"]["value"],
                             (HEAD_X + 27.0, -12.5, SHELF_TOP + 55 - 12), (HEAD_X + 36.0, 12.5, SHELF_TOP + 55 + 12), "maker"))
        notes.append("Camera Module 2 on the forward side of the head's face plate.")
        if options["ballast_g"] > 0:
            items.append(_lump("ballast or battery", "ballast", options["ballast_g"], (options["ballast_x"], 0.0, 20.0),
                               "option"))
        notes.append("No battery: the Build HAT's supported supply is a mains adapter, so the robot is tethered. "
                     "The cable is not modelled.")
    return Walker(build, options, items, comp, notes)
