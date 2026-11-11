# SPDX-License-Identifier: MIT
"""A small picture of every printable part, for the recipes.

Each STL under stl/ (recursively) gets stl/thumbs/<same path>.png: one
three-quarter view on a white background, drawn with the software
rasteriser in microduck/render.py, so no GPU or display is needed. The
manifest records each picture next to its part together with the checksum
of the STL it was drawn from; a test compares that with the file, so a
changed part cannot keep an old picture.

    python -m microduck.thumbs            redraw what is missing or out of date
    python -m microduck.thumbs --all      redraw everything

The pictures are 8-bit palette PNGs without interlacing or transparency.
site/export.js relies on that to put them into a PDF without decoding them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

from . import render

ROOT = Path(__file__).resolve().parents[1]
STL = ROOT / "stl"
SIZE = (320, 240)
COLOUR = (236, 205, 120)                 # the print colour of the assembly pictures
VIEW = render.iso_view(40.0, 28.0)
VIEW_NOTE = "three-quarter view from the front left, 28 degrees above, in the part's own print frame"
COLOURS = 32


def draw(stl: Path):
    mesh = trimesh.load_mesh(stl)
    image = render.render([(mesh.vertices, mesh.faces, COLOUR)], view=VIEW, size=SIZE, margin=0.08)
    return image.quantize(colors=COLOURS, dither=0)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update(folder: Path = STL, redraw_all: bool = False, log=print) -> dict:
    """Draw the pictures that are missing or stale and record them in the
    manifest. Returns the manifest."""
    path = folder / "manifest.json"
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    listed = {entry["file"]: entry for entry in manifest.get("files", [])}
    old_extra = manifest.get("thumbnails", {})
    extra = {}
    keep = set()
    for stl in sorted(folder.rglob("*.stl")):
        name = stl.relative_to(folder).as_posix()
        target = folder / "thumbs" / (name[:-4] + ".png")
        digest = checksum(stl)
        record = listed[name].get("thumbnail") if name in listed else old_extra.get(name)
        if redraw_all or not target.is_file() or not record or record.get("stl_sha256") != digest:
            target.parent.mkdir(parents=True, exist_ok=True)
            draw(stl).save(target, optimize=True)
            log(f"drew {target.relative_to(folder).as_posix()}")
        record = {"file": target.relative_to(folder).as_posix(), "stl_sha256": digest, "bytes": target.stat().st_size}
        keep.add(target)
        if name in listed:
            listed[name]["thumbnail"] = record
        else:
            # A part another script put under stl/ without listing it in files: still pictured.
            bounds = np.round(trimesh.load_mesh(stl).bounds, 2).tolist()
            extra[name] = dict(record, bounding_box_mm=bounds)
    for stale in sorted((folder / "thumbs").rglob("*.png")) if (folder / "thumbs").is_dir() else []:
        if stale not in keep:
            stale.unlink()
            log(f"removed {stale.relative_to(folder).as_posix()}")
    manifest["thumbnail_view"] = f"{SIZE[0]} x {SIZE[1]} px, {VIEW_NOTE}"
    manifest["thumbnails"] = extra
    path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="redraw every picture")
    args = parser.parse_args(argv)
    manifest = update(redraw_all=args.all)
    pictures = [entry["thumbnail"] for entry in manifest["files"]] + list(manifest["thumbnails"].values())
    print(f"{len(pictures)} pictures, {sum(p['bytes'] for p in pictures) / 1e3:.0f} kB in stl/thumbs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
