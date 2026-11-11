# SPDX-License-Identifier: MIT
"""The robot as data: printed parts, servos, link frames, forward kinematics.

Lengths are millimetres and angles are degrees throughout this module.

Frames
------
Robot frame: x forward, y left, z up, origin at the origin of the torso STL.
Every link frame is parallel to the robot frame at the neutral pose and has
its origin on the joint axis, at the centre of the outer face of the servo
horn (where the printed horn blank sits). Hip roll turns about +x, hip pitch
and knee pitch about +y.

Where the cradles are comes from the design's build.py. How each servo lies in
its cradle and which face of a blank meets a horn is not stated by the design;
those choices live in config/assembly.json and are reported as assumptions.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

ROOT = Path(__file__).resolve().parents[1]
JOINTS = ["left_hip_roll", "left_hip_pitch", "left_knee",
          "right_hip_roll", "right_hip_pitch", "right_knee"]
CAMERAS = ("esp32cam", "esp_eye", "esp32_s3_eye")
with open(ROOT / "config" / "assembly.json", encoding="utf-8") as _handle:
    CAMERA = json.load(_handle)["camera"]["preset"]
PART_FILES = {
    "torso": f"01_torso_unoq_cam_{CAMERA}.stl",
    "left_yoke": "left_hip_roll_pitch_yoke.stl",
    "right_yoke": "right_hip_roll_pitch_yoke.stl",
    "left_thigh": "left_thigh_knee_cradle.stl",
    "right_thigh": "right_thigh_knee_cradle.stl",
    "left_shin": "left_shin_fixed_foot.stl",
    "right_shin": "right_shin_fixed_foot.stl",
}
FIT_FILES = {"SR431": "fit_SR431.stl", "SR311": "fit_SR311.stl", "horn": "fit_horn_drill_blank.stl",
             **{"cam_" + name: f"fit_cam_{name}.stl" for name in CAMERAS}}
# Torsos for the camera presets the assembly does not use, and the record of
# the generator parameters; fetched with the rest.
OTHER_FILES = [f"01_torso_unoq_cam_{name}.stl" for name in CAMERAS] + ["parameters.json"]
COLORS = {"print": (236, 205, 120), "servo": (60, 66, 74), "horn": (225, 228, 230),
          "board": (20, 120, 110), "shield": (40, 90, 160), "camera": (150, 40, 60)}
# From build.py: cradle plate thickness, torso cradle position, yoke cradle
# position, thigh cradle position, knee axis height in the shin, blank thickness.
PLATE = 4.0
TORSO_CRADLE_Y, TORSO_CRADLE_Z = 57.0, -19.0
YOKE_CRADLE_Y, YOKE_CRADLE_Z = 15.0, 40.0
THIGH_CRADLE_X = 75.0
SHIN_KNEE_Z = 82.0
SHIN_HALF_THICKNESS = 2.0
BLANK_HOLE_RADIUS = 4.0
BLANK_RADIUS = 17.0
SLOT_X_FRACTION, SLOT_Y_OFFSET, SLOT_SIZE = 0.26, 5.5, (4.4, 2.8)
RAIL_GAP_EACH_SIDE = 0.5


def load_json(name: str) -> dict:
    with open(ROOT / "config" / name, encoding="utf-8") as handle:
        return json.load(handle)


def stl_dir() -> Path:
    """Where the seven printable STLs are read from (never committed)."""
    return Path(os.environ.get("MICRODUCK_STL_DIR", ROOT / "build" / "stl"))


def have_stls() -> bool:
    return all((stl_dir() / name).is_file() for name in PART_FILES.values())


# --- transforms -------------------------------------------------------------

def trans(x, y, z) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def rot(axis, degrees) -> np.ndarray:
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    a = np.radians(degrees)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    m = np.eye(4)
    m[:3, :3] = np.eye(3) + np.sin(a) * k + (1 - np.cos(a)) * (k @ k)
    return m


def frame(x_axis, y_axis, z_axis, origin=(0, 0, 0)) -> np.ndarray:
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x_axis, y_axis, z_axis, origin
    assert abs(np.linalg.det(m[:3, :3]) - 1.0) < 1e-9, "frame must be right handed"
    return m


def apply(manifold: Manifold, matrix: np.ndarray) -> Manifold:
    return manifold.transform(np.asarray(matrix, float)[:3, :])


def point(matrix: np.ndarray, p) -> np.ndarray:
    return matrix[:3, :3] @ np.asarray(p, float) + matrix[:3, 3]


# --- meshes -----------------------------------------------------------------

def manifold_from_trimesh(mesh: trimesh.Trimesh) -> Manifold:
    solid = Manifold(Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                          tri_verts=np.asarray(mesh.faces, np.uint32)))
    if solid.is_empty() or solid.volume() <= 0:
        raise ValueError("mesh is not a closed positive-volume solid")
    return solid


def trimesh_from_manifold(solid: Manifold) -> trimesh.Trimesh:
    mesh = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)


def load_part(name: str, camera: str | None = None) -> Manifold:
    files = {**PART_FILES, **{"fit_" + k: v for k, v in FIT_FILES.items()}}
    if name == "torso" and camera:
        files["torso"] = f"01_torso_unoq_cam_{camera}.stl"
    return manifold_from_trimesh(trimesh.load_mesh(stl_dir() / files[name]))


def box(lo, hi) -> Manifold:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return Manifold.cube((hi - lo).tolist()).translate(lo.tolist())


def cylinder_z(radius, z0, z1, x=0.0, y=0.0) -> Manifold:
    return Manifold.cylinder(z1 - z0, radius, radius, 64).translate([x, y, z0])


# --- servos -----------------------------------------------------------------

@dataclass
class ServoShape:
    """A servo in its own frame: origin at the centre of the case bottom,
    x along the length towards the shaft end, z along the output shaft."""
    name: str
    length: float
    width: float
    height: float
    body: Manifold          # case, ears and bearing boss
    case: Manifold          # the published box only
    horn: Manifold          # horn disc and hub, turns with the driven part
    shaft_x: float          # shaft axis offset from the case centre
    face_z: float           # outer horn face, where the printed blank sits
    mass_g: float
    spec: dict


def servo_shape(name: str, hardware: dict | None = None) -> ServoShape:
    hardware = hardware or load_json("hardware.json")
    spec = hardware["servos"][name]
    pub = spec["published"]
    a = {k: v["value"] for k, v in spec["assumed"].items()}
    l, w, h = pub["length_mm"], pub["width_mm"], pub["height_mm"]
    case = box([-l / 2, -w / 2, 0], [l / 2, w / 2, h])
    e, te, ze = a["ear_overhang_mm"], a["ear_thickness_mm"], a["ear_bottom_height_mm"]
    ears = box([-l / 2 - e, -w / 2, ze], [l / 2 + e, w / 2, ze + te])
    sx = l / 2 - a["shaft_from_end_mm"]
    boss = cylinder_z(a["boss_radius_mm"], h, h + a["boss_height_mm"], sx)
    face = h + a["horn_face_above_case_mm"]
    horn = (cylinder_z(a["horn_radius_mm"], face - a["horn_thickness_mm"], face, sx)
            + cylinder_z(a["horn_hub_radius_mm"], h + a["boss_height_mm"], face, sx))
    return ServoShape(name, l, w, h, case + ears + boss, case, horn, sx, face, pub["mass_g"], spec)


def servo_in_cradle(flip: bool, slide: float = 0.0) -> np.ndarray:
    """Servo frame to cradle frame. The cradle frame is the fit piece's own:
    plate from z 0 to 4, rails along x. flip turns the servo end for end."""
    return trans(slide, 0, PLATE) @ rot([0, 0, 1], 180.0 if flip else 0.0)


# --- camera -----------------------------------------------------------------

def camera_spec(name: str, hardware: dict) -> dict:
    """Outline, mass and lens position of a camera preset. A value the maker
    publishes wins over an assumed one."""
    spec = hardware["cameras"][name]
    values = {k: v["value"] for k, v in spec["assumed"].items()}
    values.update(spec["published"])
    return {"name": spec["name"], "width": values["width_mm"], "length": values["length_mm"],
            "thickness": values["pcb_thickness_mm"], "mass_g": values["mass_g"],
            "lens_v": values["lens_centre_above_lower_edge_mm"], "lens_standoff": values["lens_front_above_board_mm"],
            "lens_diameter": values["lens_diameter_mm"]}


def camera_pose(spec: dict, mount: dict) -> dict:
    """Board and lens in the torso frame, from the mount parameters build.py
    uses: the back face of the board stands at back_x and its lower edge at
    base_z, then the mount is turned nose down by tilt about (back_x, deck top)."""
    a = np.radians(mount["tilt_deg"])
    forward = np.array([np.cos(a), 0.0, -np.sin(a)])
    up = np.array([np.sin(a), 0.0, np.cos(a)])
    origin = np.array([mount["back_x_mm"], 0.0, PLATE]) + up * (mount["base_z_mm"] - PLATE)
    lens = origin + up * spec["lens_v"] + forward * (spec["thickness"] + spec["lens_standoff"])
    return {"origin": origin, "forward": forward, "up": up, "lens": lens,
            "to_torso": frame(forward, [0.0, 1.0, 0.0], up, origin)}


def camera_solid(spec: dict, pose: dict) -> Manifold:
    """PCB and lens barrel. Local frame: x out of the camera face, y to the
    left of the robot, z up the board from its lower edge; origin on the back face."""
    w, l, t = spec["width"], spec["length"], spec["thickness"]
    lens = (Manifold.cylinder(spec["lens_standoff"], spec["lens_diameter"] / 2, spec["lens_diameter"] / 2, 32)
            .rotate([0, 90, 0]).translate([t, 0, spec["lens_v"]]))
    return apply(box([0, -w / 2, 0], [t, w / 2, l]) + lens, pose["to_torso"])


def view_cone(pose: dict, half_angle_deg: float, length: float = 400.0) -> Manifold:
    """The cone kept clear in front of the lens, apex at the lens front."""
    r = length * np.tan(np.radians(half_angle_deg))
    cone = Manifold.cylinder(length, 0.0, r, 64).rotate([0, 90, 0])
    return apply(cone, frame(pose["forward"], [0.0, 1.0, 0.0], pose["up"], pose["lens"]))


# --- robot ------------------------------------------------------------------

@dataclass
class Solid:
    name: str
    kind: str               # print, servo, horn, board, shield
    manifold: Manifold      # in the link frame
    mass_g: float
    part: str | None = None         # key into PART_FILES for printed parts
    part_to_link: np.ndarray | None = None


@dataclass
class Cradle:
    servo: str              # solid name of the servo body
    model: str              # SR431 or SR311
    link: str
    printed: str            # solid name of the printed part that carries it
    cradle_to_link: np.ndarray
    servo_to_link: np.ndarray
    joint: str              # joint this servo drives


@dataclass
class Link:
    name: str
    parent: str | None
    joint: str | None
    origin: np.ndarray      # link origin in the parent link frame, neutral pose
    axis: np.ndarray        # joint axis in the link frame
    shaft: np.ndarray       # direction the servo shaft points, parent frame
    solids: list = field(default_factory=list)


@dataclass
class Robot:
    links: dict
    cradles: list
    assumptions: dict
    hardware: dict
    envelope: Manifold | None = None    # plug clearance volume above the shield, torso frame
    camera: dict | None = None          # preset, spec and pose of the camera board

    def subtree(self, link: str) -> list:
        names = [link]
        for name, item in self.links.items():
            if item.parent in names and name not in names:
                names.append(name)
        return names

    def link_of_joint(self, joint: str) -> str:
        return next(name for name, item in self.links.items() if item.joint == joint)

    def fk(self, q: dict | None = None) -> dict:
        """Link frame to robot frame for joint angles in degrees."""
        q = q or {}
        out = {}
        for name, item in self.links.items():   # insertion order is parent first
            if item.parent is None:
                out[name] = np.eye(4)
            else:
                out[name] = out[item.parent] @ trans(*item.origin) @ rot(item.axis, q.get(item.joint, 0.0))
        return out

    def solids(self):
        for link in self.links.values():
            for solid in link.solids:
                yield link.name, solid

    def placed(self, q: dict | None = None) -> list:
        """(link, solid, manifold in the robot frame) for a pose."""
        frames = self.fk(q)
        return [(link, solid, apply(solid.manifold, frames[link])) for link, solid in self.solids()]


def build_robot(thigh_face: str | None = None, hardware: dict | None = None,
                assembly: dict | None = None, load_meshes: bool = True) -> Robot:
    """Assemble the robot. With load_meshes False the printed parts are left
    out (their manifold is empty); servos, horns and the joint chain do not
    need the STLs."""
    hardware = hardware or load_json("hardware.json")
    assembly = dict(assembly or load_json("assembly.json"))
    if thigh_face:
        assembly["thigh_face"] = thigh_face
    printing = {k: v["value"] for k, v in hardware["print"]["assumed"].items()}
    big, small = servo_shape("SR431", hardware), servo_shape("SR311", hardware)

    def printed(name: str, part: str, to_link: np.ndarray) -> Solid:
        if not load_meshes:
            return Solid(name, "print", Manifold(), 0.0, part, to_link)
        raw = load_part(part, assembly["camera"]["preset"])
        mass = raw.volume() / 1000.0 * printing["density_g_cm3"] * printing["solid_fraction"]
        return Solid(name, "print", apply(raw, to_link), mass, part, to_link)

    links: dict = {}
    cradles: list = []
    torso = Link("torso", None, None, np.zeros(3), np.zeros(3), np.zeros(3))
    torso.solids.append(printed("torso_print", "torso", np.eye(4)))
    links["torso"] = torso

    # UNO Q between the deck rails, long side along x, on spacers; the Braccio
    # shield stacked above it.
    b, ba = hardware["board"]["published"], {k: v["value"] for k, v in hardware["board"]["assumed"].items()}
    sa = {k: v["value"] for k, v in hardware["shield"]["assumed"].items()}
    bx = assembly.get("board_x_offset_mm", 0.0)
    z0 = PLATE + ba["spacer_mm"]
    z1 = z0 + ba["pcb_thickness_mm"]
    half = np.array([b["length_mm"] / 2, b["width_mm"] / 2])
    torso.solids.append(Solid("unoq", "board", box([bx - half[0], -half[1], z0], [bx + half[0], half[1], z1]), ba["mass_g"]))
    zs = z1 + sa["pcb_gap_mm"]
    torso.solids.append(Solid("braccio_shield", "shield",
                              box([bx - half[0], -half[1], zs], [bx + half[0], half[1], zs + ba["pcb_thickness_mm"]]),
                              sa["mass_g"]))
    envelope = box([bx - half[0], -half[1], z1], [bx + half[0], half[1], z1 + sa["stack_height_mm"]])

    # Camera board in the mount at the front edge of the deck.
    mount = assembly["camera"]
    cam = camera_spec(mount["preset"], hardware)
    pose = camera_pose(cam, mount)
    torso.solids.append(Solid("camera_board", "camera", camera_solid(cam, pose), cam["mass_g"]))
    camera = {"preset": mount["preset"], "spec": cam, "pose": pose,
              "cone_half_angle_deg": hardware["camera_optics"]["assumed"]["clear_cone_half_angle_deg"]["value"]}

    for side, s in (("left", 1.0), ("right", -1.0)):
        # Hip roll servo on the torso cradle. build.py: cradle rotated 90
        # degrees about y, so the shaft points along +x.
        c_roll = trans(0, s * TORSO_CRADLE_Y, TORSO_CRADLE_Z) @ rot([0, 1, 0], 90)
        s_roll = c_roll @ servo_in_cradle(assembly["roll_servo_flip"])
        torso.solids.append(Solid(f"{side}_roll_servo", "servo", apply(big.body, s_roll), big.mass_g))
        cradles.append(Cradle(f"{side}_roll_servo", "SR431", "torso", "torso_print", c_roll, s_roll, f"{side}_hip_roll"))
        p_roll = point(s_roll, [big.shaft_x, 0, big.face_z])
        a_roll = s_roll[:3, :3] @ [0, 0, 1]

        # Yoke: its z axis is the roll shaft, its x axis points up at neutral.
        hip = Link(f"{side}_hip", "torso", f"{side}_hip_roll", p_roll, np.array([1.0, 0, 0]), a_roll)
        yoke_to_link = frame([0, 0, 1], [0, -1, 0], [1, 0, 0])
        hip.solids.append(printed(f"{side}_yoke_print", f"{side}_yoke", yoke_to_link))
        hip.solids.append(Solid(f"{side}_roll_horn", "horn", apply(big.horn, trans(*-p_roll) @ s_roll), 0.0))
        # Hip pitch servo on the yoke cradle. build.py: cradle rotated -90
        # degrees about x at (0, 15, 40); the left yoke is the mirror image.
        if side == "left":
            c_pitch = trans(0, -YOKE_CRADLE_Y, YOKE_CRADLE_Z) @ rot([1, 0, 0], 90)
        else:
            c_pitch = trans(0, YOKE_CRADLE_Y, YOKE_CRADLE_Z) @ rot([1, 0, 0], -90)
        c_pitch = yoke_to_link @ c_pitch
        s_pitch = c_pitch @ servo_in_cradle(assembly["pitch_servo_flip"])
        hip.solids.append(Solid(f"{side}_pitch_servo", "servo", apply(big.body, s_pitch), big.mass_g))
        cradles.append(Cradle(f"{side}_pitch_servo", "SR431", hip.name, f"{side}_yoke_print", c_pitch, s_pitch, f"{side}_hip_pitch"))
        p_pitch = point(s_pitch, [big.shaft_x, 0, big.face_z])
        a_pitch = s_pitch[:3, :3] @ [0, 0, 1]
        links[hip.name] = hip

        # Thigh: its x axis points down the leg. The hip horn meets either the
        # flat face (thigh z along the shaft) or the rail face (thigh z against
        # the shaft, knee servo beside the hip servo).
        thigh = Link(f"{side}_thigh", hip.name, f"{side}_hip_pitch", p_pitch, np.array([0, 1.0, 0]), a_pitch)
        down = np.array([0, 0, -1.0])
        if assembly["thigh_face"] == "flat":
            thigh_to_link = frame(down, np.cross(a_pitch, down), a_pitch)
        elif assembly["thigh_face"] == "rail":
            thigh_to_link = frame(down, np.cross(-a_pitch, down), -a_pitch, PLATE * a_pitch)
        else:
            raise ValueError("thigh_face must be 'flat' or 'rail'")
        thigh.solids.append(printed(f"{side}_thigh_print", f"{side}_thigh", thigh_to_link))
        thigh.solids.append(Solid(f"{side}_pitch_horn", "horn", apply(big.horn, trans(*-p_pitch) @ s_pitch), 0.0))
        c_knee = thigh_to_link @ trans(THIGH_CRADLE_X, 0, 0)
        s_knee = c_knee @ servo_in_cradle(assembly["knee_servo_flip"])
        thigh.solids.append(Solid(f"{side}_knee_servo", "servo", apply(small.body, s_knee), small.mass_g))
        cradles.append(Cradle(f"{side}_knee_servo", "SR311", thigh.name, f"{side}_thigh_print", c_knee, s_knee, f"{side}_knee"))
        p_knee = point(s_knee, [small.shaft_x, 0, small.face_z])
        a_knee = s_knee[:3, :3] @ [0, 0, 1]
        links[thigh.name] = thigh

        # Shin: x forward (toes), z up; the knee axis runs along its y at z 82.
        shin = Link(f"{side}_shin", thigh.name, f"{side}_knee", p_knee, np.array([0, 1.0, 0]), a_knee)
        shin_to_link = trans(0, SHIN_HALF_THICKNESS * a_knee[1], -SHIN_KNEE_Z)
        shin.solids.append(printed(f"{side}_shin_print", f"{side}_shin", shin_to_link))
        shin.solids.append(Solid(f"{side}_knee_horn", "horn", apply(small.horn, trans(*-p_knee) @ s_knee), 0.0))
        links[shin.name] = shin

    return Robot(links, cradles, assembly, hardware, envelope, camera)


def servo_for_joint(joint: str) -> str:
    return "SR311" if joint.endswith("knee") else "SR431"
