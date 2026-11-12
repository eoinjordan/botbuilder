# SPDX-License-Identifier: MIT
"""Comb feet for the Microduck-look build: the feet of stl/microduck-look
with fingers that cross the robot's centre line between the fingers of the
other foot, as the comb soles of the plate biped do.

Each comb foot is made from the committed foot (left_foot.stl,
right_foot.stl): the web under the body is cut away where the other foot's
fingers pass, and fingers of the web's thickness are added from the foot to
past the centre line, each with a rib on top. The left foot has a finger at
the heel and one at the toe, the right foot one between them. Lengths are
millimetres in the robot frame at the zero pose (x forward, y left, z up).

Writes left_foot_comb.stl and right_foot_comb.stl in the print frame of the
feet they are made from (sole on the bed) and comb_feet.json, which holds
the dimensions and the two part entries in the shape of parameters.json.

This code is MIT. The files it writes are adapted from the feet of the
Microduck by Pollen Robotics and carry CC BY-NC-SA 4.0
(stl/microduck-look/LICENSE).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

from .model import FOLDER, apply, box, from_trimesh, parameters, union

RECORD = "comb_feet.json"
COMB = {
    "t": 4.0,                        # finger thickness: the web's
    "finger_x": {"left": [[-60.75, -50.75], [-10.25, -0.25]],      # heel and toe
                 "right": [[-35.5, -25.5]]},                       # one, between them
    "root_y": 51.0,                  # fingers start here, inside the foot
    "tip_past_centre": 32.0,         # finger tips, past the centre line
    "clear_x": 6.0,                  # fore and aft, between a finger and the other foot
    "clear_tip": 4.0,                # between a finger tip and the other foot
    "slot_x": {"left": [[-43.0, -19.5]],                           # cut from each web for the other foot's fingers
               "right": [[-200.0, -44.75], [-16.25, 200.0]]},
    "rib_w": 4.0, "rib_h": 9.0,      # one rib on top of each finger, to this height above the floor
    "rib_y": [40.0, -28.0],
}
ORIENTATION = "sole on the bed"
SUPPORTS = "supports under the cheek and inside the well"


def _side(y0: float, y1: float, sign: float):
    return sorted((sign * y0, sign * y1))


def comb_foot(foot: Manifold, side: str, floor: float) -> Manifold:
    """The comb foot of one side from its foot, both in the robot frame at the zero pose."""
    c = COMB
    sign = 1.0 if side == "left" else -1.0
    top = floor + c["rib_h"] + 1.5
    slot_y = _side(-200.0, c["tip_past_centre"] + c["clear_tip"], sign)
    slots = union(box([x0, slot_y[0], floor - 1.0], [x1, slot_y[1], top]) for x0, x1 in c["slot_x"][side])
    added = []
    finger_y = _side(c["root_y"], -c["tip_past_centre"], sign)
    rib_y = _side(c["rib_y"][0], c["rib_y"][1], sign)
    for x0, x1 in c["finger_x"][side]:
        mid = (x0 + x1) / 2.0
        added.append(box([x0, finger_y[0], floor], [x1, finger_y[1], floor + c["t"]]))
        added.append(box([mid - c["rib_w"] / 2.0, rib_y[0], floor + c["t"] - 0.1], [mid + c["rib_w"] / 2.0, rib_y[1], floor + c["rib_h"]]))
    return union([foot - slots] + added)


def _closed(solid: Manifold) -> trimesh.Trimesh:
    """The solid as a single precision mesh that reads back from an STL as one closed volume."""
    tri = None
    for _ in range(4):
        mesh = solid.to_mesh()
        tri = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3].astype(np.float32).astype(float), np.asarray(mesh.tri_verts), process=True)
        if tri.is_volume:
            return tri
        solid = Manifold(Mesh(np.asarray(tri.vertices, np.float32), np.asarray(tri.faces, np.uint32)))
    raise SystemExit("a comb foot is not one closed volume")


def build(folder: Path | None = None) -> dict:
    """Write the two comb feet and comb_feet.json into the parts folder."""
    folder = folder or FOLDER
    p = parameters(folder)
    floor = p["floor_z_mm"]
    parts = []
    for side in ("left", "right"):
        source = next(part for part in p["parts"] if part["file"] == f"{side}_foot.stl")
        to_robot = np.array(source["print_to_robot"], float)
        foot = apply(from_trimesh(trimesh.load_mesh(folder / source["file"])), to_robot)
        solid = comb_foot(foot, side, floor)
        if len(solid.decompose()) != 1:
            raise SystemExit(f"{side} comb foot: {len(solid.decompose())} separate solids")
        tri = _closed(apply(solid, np.linalg.inv(to_robot)))
        name = f"{side}_foot_comb.stl"
        tri.export(folder / name)
        if not trimesh.load_mesh(folder / name).is_volume:
            raise SystemExit(f"{name}: the file is not one closed volume")
        volume = float(tri.volume) / 1000.0
        parts.append({"file": name, "replaces": source["file"], "link": source["link"], "kind": source["kind"],
                      "print_to_robot": source["print_to_robot"], "volume_cm3": round(volume, 2),
                      "mass_g": round(volume * p["density_g_cm3"] * source["fill"], 1), "fill": source["fill"],
                      "triangles": int(len(tri.faces)), "size_mm": np.round(tri.extents, 1).tolist(),
                      "orientation": ORIENTATION, "supports": SUPPORTS})
    record = {"_comment": "Generated by microduck/look/combfeet.py from left_foot.stl and right_foot.stl (python scripts/run_look.py --comb-feet). Lengths in mm, robot frame at the zero pose.",
              "_licence": p["_licence"], "feet": "comb", "comb": COMB, "parts": parts}
    (folder / RECORD).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return record


def record(folder: Path | None = None) -> dict:
    with open((folder or FOLDER) / RECORD, encoding="utf-8") as handle:
        return json.load(handle)


def have(folder: Path | None = None) -> bool:
    folder = folder or FOLDER
    return (folder / RECORD).is_file() and all((folder / part["file"]).is_file() for part in record(folder)["parts"])
