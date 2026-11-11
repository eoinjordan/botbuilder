# SPDX-License-Identifier: MIT
"""Copy the printable STLs from the design directory into stl/lego/ and write
stl/lego/manifest.json in the shape of the repository's stl/manifest.json:
files[] with file (relative to stl/), what and options{...}.

    python -m walkers.manifest --design-dir /path/to/3d-print-designs/microduck-lego
    python -m walkers.manifest --merge      also put these entries into stl/manifest.json

Without --design-dir the manifest is rebuilt from the STLs already in
stl/lego/ and the recorded design commits are kept.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parents[1]
STL = ROOT / "stl" / "lego"
TOP = ROOT / "stl" / "manifest.json"
CONFIG = Path(__file__).resolve().parent / "config"
PREFIX = "lego/"
CONTROLLER = {"ev3-pixy2": "ev3", "pi-zero-2w-51515": "pi", "hub-51515": "hub51515"}
CAMERA = {"ev3-pixy2": "pixy2", "pi-zero-2w-51515": "picam2"}


def _commit(design: Path, rel: str) -> str:
    done = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel], cwd=design, capture_output=True, text=True)
    return done.stdout.strip()


def options(folder: str, name: str) -> dict:
    """The option fields the recipe code selects files by, with the
    configurator's ids (config/compat.json)."""
    stem = name[:-4]
    out = {}
    if stem.startswith("fit_"):
        out["fit_piece"] = True
    if folder != "wheeled":
        out["controller"] = CONTROLLER[folder]
        part = {"crank_print_4": "crank", "gear_16t_print_6": "gear", "camera_head_pantilt": "head",
                "camera_head": "head", "fit_coupon": "fit_coupon"}.get(stem, stem)
        out["part"] = part
        if part in ("left_leg", "right_leg", "crank", "gear"):
            out["locomotion"] = "crank"
        if part == "head":
            out["head"] = "pixy_pantilt" if stem.endswith("pantilt") else "fixed"
            if folder in CAMERA:
                out["camera"] = CAMERA[folder]
        return out
    out["locomotion"] = "wheeled"
    kind = stem.split("_")[1] if stem.startswith("fit_") else stem.split("_")[0]
    out["part"] = {"post": "support_post", "tip": "support_tip", "idler": "idler", "wheel": "wheel", "hub": "wheel_hub",
                   "tyre": "tyre", "tt": "motor_cradle", "servo": "motor_cradle", "driver": "driver_plate",
                   "bore": "wheel_bore"}[kind]
    if stem.startswith(("wheel_solid", "wheel_band")):
        out["wheel"] = "printed_ring"
    if stem.startswith(("hub_tpu", "tyre_tpu")):
        out["wheel"] = "printed_tpu"
    if stem == "tip_skid":
        out["support"] = "skid"
    if stem.startswith("tip_ball"):
        out["support"] = "roller"
    if "_tt" in stem or stem.startswith(("tt_", "driver_")):
        out["drive"] = "tt_hbridge"
    if "_horn" in stem or "servo" in stem:
        out["drive"] = "m5_360_wheels"
    for size in ("d43", "d56", "d65"):
        if stem.endswith(size):
            out["wheel_class"] = size
    return out


def entry(folder: str, name: str, info: dict, commit: str) -> dict:
    path = STL / folder / name
    mesh = trimesh.load_mesh(path)
    lo, hi = mesh.bounds
    return {
        "file": f"{PREFIX}{folder}/{name}",
        "what": info["purpose"],
        "options": options(folder, name),
        "print_quantity": info["quantity"],
        "material": info.get("material", "PLA or PETG"),
        "triangles": int(len(mesh.faces)),
        "volume_mm3": round(float(mesh.volume), 1),
        "bounding_box_mm": [[round(float(v), 2) for v in lo], [round(float(v), 2) for v in hi]],
        "watertight": bool(mesh.is_volume),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "design_commit": commit,
        **({"note": info["note"]} if "note" in info else {}),
    }


def merge(manifest: dict) -> bool:
    """Put these entries into stl/manifest.json beside the biped's, replacing
    any earlier lego/ entries. Returns False if that file does not exist."""
    if not TOP.is_file():
        return False
    with open(TOP, encoding="utf-8") as handle:
        top = json.load(handle)
    top["files"] = [f for f in top["files"] if not f["file"].startswith(PREFIX)] + manifest["files"]
    top["total_bytes"] = sum(f["bytes"] for f in top["files"])
    TOP.write_text(json.dumps(top, indent=1) + "\n", encoding="utf-8", newline="\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--design-dir", type=Path)
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()
    with open(CONFIG / "parts.json", encoding="utf-8") as handle:
        parts = json.load(handle)
    old = {}
    if (STL / "manifest.json").is_file():
        with open(STL / "manifest.json", encoding="utf-8") as handle:
            old = {e["file"].removeprefix(PREFIX): e["design_commit"] for e in json.load(handle)["files"]}
    files = []
    for folder, group in parts["folders"].items():
        (STL / folder).mkdir(parents=True, exist_ok=True)
        for name, info in group["files"].items():
            rel = f"{folder}/{name}"
            if args.design_dir:
                shutil.copyfile(args.design_dir / folder / name, STL / folder / name)
                commit = _commit(args.design_dir, rel)
            else:
                commit = old.get(rel, "")
            files.append(entry(folder, name, info, commit))
    total = sum(f["bytes"] for f in files)
    manifest = {
        "_comment": "Generated by python -m walkers.manifest. Lengths in mm. Print at 100 percent scale. File paths are relative to stl/.",
        "generated_by": "walkers/manifest.py",
        "design": {"repository": "3d-print-designs, directory microduck-lego (the owner's design directory)",
                   "generator": "microduck-lego/build.py"},
        "folders": {PREFIX + folder: group["what"] for folder, group in parts["folders"].items()},
        "total_bytes": total,
        "files": files,
    }
    (STL / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(files)} STLs, {total / 1e6:.2f} MB")
    if args.merge:
        print("merged into stl/manifest.json" if merge(manifest) else "no stl/manifest.json to merge into")
    return 0


if __name__ == "__main__":
    sys.exit(main())
