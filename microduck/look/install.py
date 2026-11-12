# SPDX-License-Identifier: MIT
"""Bring the Microduck-look parts into stl/microduck-look, make the comb feet
from the feet, list all of them in stl/manifest.json beside the other builds,
and write the entries the configurator reads
(reports/microduck-look/summary.json), one for each choice of feet.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import trimesh

from .. import thumbs
from . import combfeet
from .model import FOLDER, JOINTS, ROOT, parameters, part_list

PREFIX = "microduck-look/"
TOP = ROOT / "stl" / "manifest.json"
OWN = FOLDER / "manifest.json"
SUMMARY = ROOT / "reports" / "microduck-look" / "summary.json"
BUILD = ROOT / "config" / "microduck-look" / "build.json"
SOURCE_MODEL = "Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl"
FEET_OPTION = {"flat": "web", "comb": "comb"}      # the configurator's feet choice and the feet it means here
COMB_LICENCE = """Comb feet

  left_foot_comb.stl and right_foot_comb.stl are the two feet above with
  part of the web cut away and fingers added that cross the centre line
  between the fingers of the other foot. They are made from left_foot.stl
  and right_foot.stl by microduck/look/combfeet.py (MIT); their dimensions
  are in comb_feet.json. They are adapted from the same model, the Microduck
  by Pollen Robotics, and carry the same licence and credit as the other
  files in this directory.
"""
LICENCE_LINE = "Microduck-look parts: CC BY-NC-SA 4.0, adapted from Pollen Robotics' Microduck; not for commercial use"
WHAT = {
    "body_left": "body shell, left half", "body_right": "body shell, right half",
    "trunk_frame": "trunk frame: deck, two hip yaw cradles, spine, back plate for the two board stacks, neck uprights",
    "hip_yaw": "hip yaw link: disc on the yaw horn, cradle of the hip roll servo",
    "hip_roll": "hip roll link: plate on the roll horn, arm to the hip pitch horn",
    "thigh": "thigh: the cover with the cradles of the hip pitch and knee servos",
    "shin": "shin: plate on the knee horn, cradle of the ankle servo",
    "foot": "foot with the sole, the web towards the centre line and the cheek on the ankle horn",
    "foot_comb": "comb foot: the foot with fingers that cross the centre line between the other foot's fingers",
    "neck": "neck: sleeve for the neck pitch and head pitch servos",
    "head_pitch_yoke": "yoke from the head pitch horn to the head yaw servo",
    "head_yaw_carrier": "carrier of the head yaw servo, with the head roll horn plate and pivot",
    "head_base": "head, lower shell with the cradles of the head roll and beak servos",
    "head_top": "head, upper shell", "head_face": "face plate with the eye ring and the camera seat",
    "beak_jaw": "lower beak with its pad", "beak_top": "upper beak plate",
}
FIT = {"fit_SR431": "fit piece: SR431 cradle", "fit_SR311": "fit piece: SR311 cradle", "fit_M5_180": "fit piece: cradle of the small 180 degree servo",
       "fit_horn_SR431": "fit piece: horn plate, SR431", "fit_horn_SR311": "fit piece: horn plate, SR311",
       "fit_horn_M5_180": "fit piece: horn plate, small servo"}


def _what(stem: str) -> str:
    if stem in FIT:
        return FIT[stem]
    if stem.startswith("fit_eye_"):
        return "fit piece: seat of the camera board behind the eye" if "display" not in stem else "fit piece: seat of the round display"
    side = stem.split("_")[0] if stem.split("_")[0] in ("left", "right") else ""
    key = stem[len(side) + 1:] if side else stem
    return (side + " " if side else "") + WHAT[key]


def _commit(design: Path):
    def git(*args):
        done = subprocess.run(["git", "-C", str(design), *args], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else None
    return git("rev-parse", "HEAD"), git("status", "--porcelain", "--", ".")


def entries(folder: Path, commit: str) -> list:
    comb = combfeet.record(folder)["parts"] if combfeet.have(folder) else []
    out = []
    for part in parameters(folder)["parts"] + comb:
        path = folder / part["file"]
        mesh = trimesh.load_mesh(path)
        stem = part["file"][:-4]
        fit = stem.startswith("fit_")
        options = {"style": "microduck", "locomotion": "biped_look"}
        options.update({"fit_piece": True} if fit else {"part": stem})
        if stem.endswith(("_foot", "_foot_comb")):
            options["feet"] = "comb" if stem.endswith("_comb") else "flat"
        out.append({
            "file": PREFIX + part["file"], "what": _what(stem), "options": options, "print_quantity": 1,
            "material": "PLA; " + part["orientation"] + "; supports: " + part["supports"],
            "triangles": int(len(mesh.faces)), "volume_mm3": round(float(mesh.volume), 1),
            "bounding_box_mm": np.round(mesh.bounds, 2).tolist(), "watertight": bool(mesh.is_volume),
            "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "design_commit": commit, "licence": "CC-BY-NC-SA-4.0",
        })
        if "replaces" in part:
            out[-1]["made_from"] = PREFIX + part["replaces"]
            out[-1]["generated_by"] = "microduck/look/combfeet.py"
    return out


def merge(files: list) -> bool:
    """Put these entries into stl/manifest.json beside the others, replacing earlier microduck-look/ entries."""
    if not TOP.is_file():
        return False
    with open(TOP, encoding="utf-8") as handle:
        top = json.load(handle)
    top["files"] = [f for f in top["files"] if not f["file"].startswith(PREFIX)] + files
    top["total_bytes"] = sum(f["bytes"] for f in top["files"])
    TOP.write_text(json.dumps(top, indent=1) + "\n", encoding="utf-8", newline="\n")
    return True


def remerge() -> bool:
    """For scripts/fetch_stls.py, which rewrites stl/manifest.json: list these parts again."""
    if not OWN.is_file():
        return False
    with open(OWN, encoding="utf-8") as handle:
        return merge(json.load(handle)["files"])


def fetch(design: Path) -> int:
    source = design / "stl"
    if not (design / "parameters.json").is_file() or not source.is_dir():
        print(f"no parameters.json and stl directory under {design}")
        return 1
    commit, dirty = _commit(design)
    FOLDER.mkdir(parents=True, exist_ok=True)
    for old in FOLDER.glob("*.stl"):
        old.unlink()
    names = sorted(p.name for p in source.glob("*.stl"))
    for name in names:
        shutil.copyfile(source / name, FOLDER / name)
    shutil.copyfile(design / "parameters.json", FOLDER / "parameters.json")
    licence = (design / "LICENSE").read_text(encoding="utf-8")
    (FOLDER / "LICENSE").write_text(licence.rstrip("\n") + "\n\n" + COMB_LICENCE, encoding="utf-8", newline="\n")
    combfeet.build(FOLDER)
    own = _list({"repository": "eoinjordan/3d-print-designs", "directory": "microduck-look", "generator": "build.py", "commit": commit,
                 "uncommitted_changes": None if dirty is None else bool(dirty)})
    print(f"copied {len(names)} STLs and made the comb feet ({own['total_bytes'] / 1e6:.2f} MB) in {FOLDER}")
    return 0


def _list(design: dict) -> dict:
    """Write this folder's manifest, list its parts in stl/manifest.json and draw the missing part pictures."""
    files = entries(FOLDER, design["commit"] or "")
    own = {"_comment": "Generated by scripts/run_look.py --fetch. Lengths in mm. File paths are relative to stl/.",
           "licence": "CC-BY-NC-SA-4.0", "source_model": SOURCE_MODEL,
           "credit": "Adapted from the Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl",
           "design": design,
           "generator_parameters_sha256": hashlib.sha256((FOLDER / "parameters.json").read_bytes()).hexdigest(),
           "total_bytes": sum(f["bytes"] for f in files), "files": files}
    OWN.write_text(json.dumps(own, indent=1) + "\n", encoding="utf-8", newline="\n")
    merge(files)
    thumbs.update(log=lambda line: None)
    return own


def comb_feet() -> int:
    """Make the comb feet again from the feet that are here, and list them."""
    with open(OWN, encoding="utf-8") as handle:
        design = json.load(handle)["design"]
    licence = (FOLDER / "LICENSE").read_text(encoding="utf-8")
    if COMB_LICENCE not in licence:
        (FOLDER / "LICENSE").write_text(licence.rstrip("\n") + "\n\n" + COMB_LICENCE, encoding="utf-8", newline="\n")
    made = combfeet.build(FOLDER)
    _list(design)
    print("made " + ", ".join(part["file"] for part in made["parts"]))
    return 0


# ---------------------------------------------------------------- what the configurator reads
SOURCES = {
    "m5_servo_kit_180": "https://docs.m5stack.com/en/accessory/servo_kit_180",
    "m5_servo_kit_360": "https://docs.m5stack.com/en/accessory/servo_kit_360",
    "bala_c": "https://docs.m5stack.com/en/app/balac",
    "pca9685": "https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf",
    "pca9685_board": "https://www.adafruit.com/product/815",
    "uno_q": "https://docs.arduino.cc/resources/datasheets/ABX00162-datasheet.pdf",
    "braccio_library": "https://github.com/arduino-libraries/Braccio",
    "braccio_kit": "https://store-usa.arduino.cc/products/tinkerkit-braccio-robot",
    "xl330_m288": "https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/",
    "xl330_m077": "https://emanual.robotis.com/docs/en/dxl/x/xl330-m077/",
    "u2d2": "https://emanual.robotis.com/docs/en/parts/interface/u2d2/",
    "microduck": "https://github.com/pollen-robotics/microduck",
    "microduck_rl": "https://github.com/pollen-robotics/microduck_rl",
    "radxa_zero_3": "https://docs.radxa.com/en/zero/zero3",
}
PARTS = [
    {"name": "SR431 servo (TinkerKit Braccio kit)", "qty": 8, "note": "hip roll, hip pitch, knee and ankle of each leg; from two kits"},
    {"name": "SR311 servo (TinkerKit Braccio kit)", "qty": 4, "note": "hip yaw of each leg, neck pitch, head pitch; from two kits"},
    {"name": "Arduino UNO Q with a Braccio shield", "qty": 2, "note": "one per leg: six outputs each; on the back plate, one above the other"},
    {"name": "Braccio kit supply, regulated 5 V 4 A", "qty": 2, "note": "one per shield; below the stall demand of six servos: see Power"},
    {"name": "M5Stack Servo Kit 180 (two 9 g position servos per kit)", "qty": 2,
     "note": "to order: head yaw, head roll and beak need three position servos. The Servo Kit 360 and the BALA-C's servos turn continuously and cannot hold a joint"},
    {"name": "16-channel I2C servo driver board (PCA9685)", "qty": 1,
     "note": "to order unless one of your driver boards is this type: the three small servos; on the first UNO Q's Qwiic connector, 3.3 V logic"},
    {"name": "Servo horn with centre screw (from the kits)", "qty": 15, "note": "also the drilling jig for the printed horn plates"},
    {"name": "Horn screws for the printed plates", "qty": 30, "note": "two opposed per horn; size to suit your horns: measure"},
    {"name": "Small cable tie", "qty": 19, "note": "one round each servo cradle in its groove, four for the two board stacks"},
    {"name": "M3 x 10 screw", "qty": 5, "note": "four through the body halves into the frame posts, one through the back of the head; they cut their own thread in the 2.8 mm holes"},
    {"name": "M3 x 16 screw", "qty": 3, "note": "pivots opposite a horn: neck (right upright), head roll (front of the carrier), beak (right cheek)"},
    {"name": "Switch in each servo supply, within reach", "qty": 2, "note": "a software stop does not cut power"},
]


def _entry(option: str, rep: dict, sim: dict | None, p: dict) -> dict:
    """The summary entry of one choice of feet. rep and sim are that choice's part of the two reports."""
    comb = option == "comb"
    feet = rep["one_foot"]
    margins = [feet[s]["margin_mm"] for s in feet if feet[s].get("found")]
    rolls = sorted({abs(feet[s]["roll_deg"]) for s in feet if feet[s].get("found")})
    how = "with no roll of the hips" if rolls == [0.0] else f"with both hips rolled {rolls[-1]} degrees"
    verdict = (f"on two feet the centre of mass is {rep['stand_pose']['margin_mm']} mm inside the soles; on one foot "
               + (f"{min(margins)} mm inside the sole {how}" if len(margins) == 2 else "no pose was found"))
    whole = _load_report("assembly.json")
    notes = [f"Scale {whole['scale']} of the original: {whole['dimensions']['height_stand_mm']} mm tall at the stand pose.",
             "Fifteen servos: twelve Braccio servos on the leg joints, neck pitch and head pitch; three small position servos for head yaw, head roll and the beak.",
             f"Largest holding torque against half of stall: {max(row['required_over_hold_limit'] for row in whole['torque'].values())} "
             f"({max(whole['torque'], key=lambda j: whole['torque'][j]['required_over_hold_limit'])}).",
             "No firmware for fifteen joints exists yet: the control core in this repository drives six.",
             "Print the fit pieces first.", LICENCE_LINE + "."]
    if comb:
        notes.insert(1, "Comb feet: the fingers of each foot cross the centre line between the other foot's. With both feet down the hips "
                        f"can turn (yaw) {rep['joint_ranges']['left_hip_yaw']['max_deg']} degrees before the fingers meet; lift a foot to turn further.")
    if sim:
        walk = sim["walk"]
        if not all(side.get("held") for side in sim["one_foot"].values()):
            notes.insert(3, "The one-foot pose is a static one. With no ankle roll the model does not move into it slowly: "
                            "it rests on the edges of both soles. The gait rocks from foot to foot.")
        notes.insert(3, f"Simulation: stands; the walking attempt {'steps' if walk['truly_steps'] else 'does not truly step'}: "
                        f"{walk['speed_mm_s']} mm/s, {walk['stepping']['steps']} of {walk['stepping']['steps_commanded']} steps with a sole off the floor.")
    files = [{"file": PREFIX + part["file"], "qty": 1, "role": _what(part["file"][:-4]), "fit": part["file"].startswith("fit_")}
             for part in part_list(feet=FEET_OPTION[option])]
    return {
        "id": "unoq-biped_look-braccio_two_shields" + ("-comb" if comb else ""), "controller": "unoq", "locomotion": "biped_look",
        "drive": "braccio_two_shields", "feet": option,
        "style": "microduck", "build": "microduck-look", "title": "Biped, Microduck look" + (", comb feet" if comb else ""),
        "status": "analysed in simulation" if sim else "defined",
        "mass_g": round(rep["mass"]["total_kg"] * 1000.0, 1),
        "size_mm": [whole["dimensions"]["length_mm"], whole["dimensions"]["width_mm"], whole["dimensions"]["height_stand_mm"]],
        "stability_verdict": verdict, "stability_margin_mm": min(margins) if margins else None,
        "drive_summary": "eight SR431 and four SR311 on two Braccio shields, three 9 g position servos on an I2C servo driver",
        "speed_mm_s": sim["walk"]["speed_mm_s"] if sim else None, "notes": notes, "files": files, "parts": PARTS,
        "licence": "CC-BY-NC-SA-4.0", "licence_line": LICENCE_LINE, "source_model": SOURCE_MODEL,
    }


def _load_report(name: str):
    path = ROOT / "reports" / "microduck-look" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def feet_compared(sim: dict | None) -> dict | None:
    """Walking speed in the simulation with each choice of feet, and which is the faster."""
    if not sim or "comb_feet" not in sim:
        return None
    rows = {"flat": sim["walk"], "comb": sim["comb_feet"]["walk"]}
    out = {option: {"speed_mm_s": walk["speed_mm_s"], "truly_steps": walk["truly_steps"], "fell": walk["fell"],
                    "steps": walk["stepping"]["steps"], "steps_commanded": walk["stepping"]["steps_commanded"],
                    "step_length_mm": walk["stepping"]["step_length_mm"], "median_clearance_mm": walk["stepping"]["median_clearance_mm"],
                    "single_support_fraction": walk["stepping"]["single_support_fraction"],
                    "heading_change_deg": walk["heading_change_deg"], "max_tilt_deg": walk["max_tilt_deg"],
                    "poses_with_mesh_overlap": walk["mesh_overlaps"]["poses_with_overlap"], "gait": walk["params"]}
           for option, walk in rows.items()}
    usable = {option: row["speed_mm_s"] for option, row in out.items() if row["truly_steps"] and not row["poses_with_mesh_overlap"]}
    out["faster"] = max(usable, key=usable.get) if usable else None
    out["note"] = ("30 s of the open-loop gait found for each set of feet by the same search (seed, generations and population in "
                   "reports/microduck-look/sim.json), floor friction 0.6. 'flat' is the feet as generated, with the web. Simulation only.")
    return out


def summary() -> dict:
    """Entries in the shape of reports/variants/summary.json, from this build's reports: one for each choice of feet."""
    rep = _load_report("assembly.json")
    sim = _load_report("sim.json")
    p = parameters()
    listed = [_entry("flat", rep, sim, p)]
    if "comb_feet" in rep:
        listed.append(_entry("comb", rep["comb_feet"], (sim or {}).get("comb_feet"), p))
    out = {"_comment": "The Microduck-look build as entries in the shape of reports/variants/summary.json, one for each choice of feet ('flat' is the feet as generated). Generated by scripts/run_look.py; do not edit.",
           "source_model": SOURCE_MODEL, "licence": "CC-BY-NC-SA-4.0",
           "walking_speed_by_feet": feet_compared(sim),
           "entries": listed}
    SUMMARY.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    stall = {kind: spec["stall_a"] for kind, spec in p["servo_types"].items()}
    count = rep["servo_count"]
    with open(ROOT / "robot" / "microduck-look" / "joints.json", encoding="utf-8") as handle:
        table = json.load(handle)
    build = {
        "_comment": "Hardware of the Microduck-look build: what drives each joint, the signal map and the supply. Generated by scripts/run_look.py from the reports; the sources are the makers' pages.",
        "licence_line": LICENCE_LINE, "sources": SOURCES, "scale": rep["scale"],
        "servos": {kind: {"count": count[kind], "stall_torque_nm": p["servo_types"][kind]["torque"], "mass_g": p["servo_types"][kind]["mass"],
                          "stall_current_a": stall[kind]} for kind in count},
        "signals": {j: {"servo": table["joints"][j]["servo"], "driven_by": table["joints"][j]["driven_by"], "output": table["joints"][j]["output"],
                        "pin": table["joints"][j]["pin"]} for j in JOINTS},
        "signal_notes": [
            "Baseline: two UNO Q boards, each under one Braccio shield. The shield's six outputs are the UNO Q pins 11, 10, 9, 6, 5 and 3, the only six PWM pins of the header, so one board cannot drive twelve servos through two shields.",
            "The two boards have to act as one controller: one link between them (UART on D0 and D1, 3.3 V, crossed, common ground) or both as targets of one host. The control core in this repository handles six joints on one board; fifteen joints on two boards is not written.",
            "The three small servos are on a 16-channel PCA9685 driver on the first board's I2C (Qwiic connector, 3.3 V logic; the PCA9685 takes 2.3 to 5.5 V logic). Its servo rail is fed with 5 V from the first shield's supply.",
            "Alternative: one UNO Q and one PCA9685 for all fifteen servos, with the shields used only to distribute 5 V. It saves a board and the link, and needs the twelve Braccio leads on the driver's headers."],
        "supply": {
            "stall_demand_a": round(sum(count[k] * stall[k] for k in count), 2),
            "per_board_stall_a": {"board 1": round(sum(stall[table["joints"][j]["servo"]] for j in JOINTS if table["joints"][j]["driven_by"] in ("board 1", "driver")), 2),
                                  "board 2": round(sum(stall[table["joints"][j]["servo"]] for j in JOINTS if table["joints"][j]["driven_by"] == "board 2"), 2)},
            "kit_supplies_a": 8.0,
            "note": "Stall currents of the Braccio servos are assumed (2.0 A and 1.0 A, config/hardware.json); the small servo's 0.75 A is M5Stack's figure."},
        "parts": PARTS,
    }
    if sim:
        build["supply"]["simulated_peak_a"] = sim["walk"].get("estimated_supply_current_a")
    BUILD.parent.mkdir(parents=True, exist_ok=True)
    BUILD.write_text(json.dumps(build, indent=1) + "\n", encoding="utf-8", newline="\n")
    return out
