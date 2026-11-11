# SPDX-License-Identifier: MIT
"""The table behind the controller's leg clearance rule, and its validation.

build() makes robot/clearance.json from the generated robot (robot/model.json,
robot/joints.json) and the sole design (stl/parameters.json): for each leg a
few boxes that enclose the thigh plate, the knee servo, the shin plate and the
pieces of the sole, each grown by half the margin, so the table errs towards
refusing.
protocol.legs_clear() and DuckControl.hpp test those boxes against each other.

validate() compares the rule with the exact mesh test of microduck/assembly.py
over sampled poses. A false accept (rule says clear, meshes overlap) is a
fault; a false reject only costs range.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import protocol
from .protocol import JOINTS, ROOT

MARGIN_MM = 4.0             # kept between the boxes of the two legs
SOLE_ZONE_EXTRA_MM = 3.0    # studs and fillets above the sole's nominal height
TARGET = ROOT / "robot" / "clearance.json"


def _load(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _entry(lo, hi) -> list:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    centre = 0.5 * (lo + hi)
    half = [round(float(v) + 0.005, 2) for v in 0.5 * (hi - lo) + 0.5 * MARGIN_MM]
    radius = math.ceil(math.sqrt(sum(v * v for v in half)) * 100.0 + 1.0) / 100.0
    return [round(float(v), 2) for v in centre] + half + [radius]


def _bbox_entry(boxes: list) -> list:
    return _entry(np.min([b["min"] for b in boxes], axis=0), np.max([b["max"] for b in boxes], axis=0))


def _shin_boxes(boxes: list, side: str, feet: str, design: dict) -> dict:
    """Boxes for a shin: the plate above the sole as one bounding box, and
    the sole. A comb sole is taken piece by piece from the part generator's
    parameters (bridge, rail, each finger, and the fillet at each finger's
    root), as high as the generated sole; any other sole is one bounding box."""
    bottom = min(b["min"][2] for b in boxes)
    zone = bottom + (design["comb"]["rail_h"] if feet == "comb" else 5.0) + SOLE_ZONE_EXTRA_MM
    sole = [b for b in boxes if b["max"][2] <= zone]
    out = {"column": _bbox_entry([b for b in boxes if b["max"][2] > zone])}
    if feet != "comb":
        out["sole"] = _bbox_entry(sole)
        return out
    comb = design["comb"]
    top = max(b["max"][2] for b in sole)
    # part frame to link frame: u is towards the other leg from the shin plate
    offset = 2.0

    def piece(x, u):
        ys = sorted(((-u[0] - offset) if side == "left" else (u[0] + offset), (-u[1] - offset) if side == "left" else (u[1] + offset)))
        return _entry([x[0], ys[0], bottom], [x[1], ys[1], top])

    out["bridge"] = piece(comb["bridge_x"], comb["bridge_u"])
    out["rail"] = piece(comb["rail_x"], comb["rail_u"])
    for i, finger in enumerate(comb["fingers"][side]):
        out[f"finger_{i}"] = piece(finger, [comb["rail_u"][1], comb["tip_u"]])
        out[f"finger_{i}_root"] = piece([finger[0] - comb["fillet"], finger[1] + comb["fillet"]],
                                        [comb["rail_u"][1], comb["rail_u"][1] + comb["fillet"]])
    return out


def build(root=ROOT) -> dict:
    model = _load(root / "robot" / "model.json")
    joints = _load(root / "robot" / "joints.json")
    design = _load(root / "stl" / "parameters.json")["feet"]
    feet = _load(root / "config" / "assembly.json").get("feet", design.get("default", "comb"))
    links = {link["name"]: link for link in model["links"]}
    legs = {}
    for side in ("left", "right"):
        thigh = [s for s in links[f"{side}_thigh"]["shapes"] if s["type"] == "box"]
        shin = [s for s in links[f"{side}_shin"]["shapes"] if s["type"] == "box"]
        groups = _shin_boxes(shin, side, feet, design)
        legs[side] = {
            "origins_mm": [[round(1000.0 * v, 3) for v in joints["joints"][f"{side}_{j}"]["origin_m"]] for j in ("hip_roll", "hip_pitch", "knee")],
            "thigh_names": ["plate", "knee servo"],
            "thigh": [_bbox_entry([s for s in thigh if s["kind"] != "servo"]), _bbox_entry([s for s in thigh if s["kind"] == "servo"])],
            "shin_names": sorted(groups),
            "shin": [groups[name] for name in sorted(groups)],
        }
    return {"generated_by": "scripts/generate_description.py", "feet": feet, "margin_mm": MARGIN_MM,
            "box": "centre x y z, half size x y z (grown by half the margin), bounding radius; mm in the link frame",
            "pairs": "left shin against right shin, each shin against the other thigh",
            "legs": legs}


def write(path=None) -> dict:
    table = build()
    (path or TARGET).write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
    return table


# --- validation against the meshes -------------------------------------------

LEG_SOLIDS = ("thigh_print", "knee_servo", "shin_print")


class MeshLegs:
    """Exact test of one leg against the other on the printed meshes and the
    knee servos."""

    def __init__(self):
        from . import assembly, model
        self.assembly, self.model = assembly, model
        self.robot = model.build_robot()
        self.threshold = self.robot.assumptions["interference_threshold_mm3"]
        self.parts = {side: [(link, solid) for link, solid in self.robot.solids()
                             if solid.name in {f"{side}_{n}" for n in LEG_SOLIDS}] for side in ("left", "right")}

    def overlap_mm3(self, q_deg) -> float:
        frames = self.robot.fk(dict(zip(JOINTS, q_deg)))
        placed = {side: [(self.model.apply(s.manifold, frames[link])) for link, s in items] for side, items in self.parts.items()}
        boxes = {side: [self.assembly._bbox(m) for m in ms] for side, ms in placed.items()}
        worst = 0.0
        for a, ba in zip(placed["left"], boxes["left"]):
            for b, bb in zip(placed["right"], boxes["right"]):
                if self.assembly._disjoint(ba, bb):
                    continue
                worst = max(worst, (a ^ b).volume())
        return worst

    def collide(self, q_deg) -> bool:
        return self.overlap_mm3(q_deg) > self.threshold


def sample_poses(cal: protocol.Calibration, seed: int, uniform: int, near_stand: int, one_joint: int) -> dict:
    """Poses inside the soft limits: uniform over them, within 25 degrees of
    the stand pose, and one joint at a time moved from the stand pose."""
    rng = np.random.default_rng(seed)
    lo = np.array([j.min_deg for j in cal.joints])
    hi = np.array([j.max_deg for j in cal.joints])
    stand = np.array(cal.stand_deg)
    out = {"uniform over the limits": rng.uniform(lo, hi, (uniform, 6)),
           "within 25 degrees of the stand pose": np.clip(stand + rng.uniform(-25.0, 25.0, (near_stand, 6)), lo, hi)}
    rows = []
    for i in range(6):
        for value in np.linspace(lo[i], hi[i], one_joint):
            q = stand.copy()
            q[i] = value
            rows.append(q)
    out["one joint moved from the stand pose"] = np.array(rows)
    return out


def validate(seed: int = 1, uniform: int = 3000, near_stand: int = 3000, one_joint: int = 120, progress=None) -> dict:
    cal = protocol.load_calibration()
    meshes = MeshLegs()
    result = {"seed": seed, "margin_mm": cal.clearance["margin_mm"], "mesh_overlap_threshold_mm3": meshes.threshold, "sets": {}}
    totals = {"poses": 0, "false_accepts": 0, "false_rejects": 0, "mesh_free": 0, "mesh_colliding": 0}
    for name, poses in sample_poses(cal, seed, uniform, near_stand, one_joint).items():
        counts = {"poses": len(poses), "mesh_colliding": 0, "rule_refuses": 0, "false_accepts": 0, "false_rejects": 0}
        worst = 0.0
        for k, q in enumerate(poses):
            q = [round(float(v), 1) for v in q]
            hit = meshes.collide(q)
            ok = protocol.legs_clear(cal.clearance, q)
            counts["mesh_colliding"] += hit
            counts["rule_refuses"] += not ok
            if hit and ok:
                counts["false_accepts"] += 1
                worst = max(worst, meshes.overlap_mm3(q))
            counts["false_rejects"] += (not hit) and (not ok)
            if progress and k % 500 == 0:
                progress(name, k)
        free = counts["poses"] - counts["mesh_colliding"]
        counts["false_accept_rate_of_colliding_poses"] = round(counts["false_accepts"] / max(counts["mesh_colliding"], 1), 4)
        counts["false_reject_rate_of_free_poses"] = round(counts["false_rejects"] / max(free, 1), 4)
        counts["worst_accepted_overlap_mm3"] = round(worst, 1)
        result["sets"][name] = counts
        totals["poses"] += counts["poses"]
        totals["false_accepts"] += counts["false_accepts"]
        totals["false_rejects"] += counts["false_rejects"]
        totals["mesh_free"] += free
        totals["mesh_colliding"] += counts["mesh_colliding"]
    totals["false_reject_rate_of_free_poses"] = round(totals["false_rejects"] / max(totals["mesh_free"], 1), 4)
    result["total"] = totals
    return result
