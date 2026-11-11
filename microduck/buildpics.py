# SPDX-License-Identifier: MIT
"""One picture of the whole robot for each finished build of
config/builds.json, for its card on the landing page.

Every picture is the same three-quarter view, drawn with the software
rasteriser in microduck/render.py from data that already exists:

- the biped from the assembly model (microduck/model.py) at the stand pose,
  with the face, camera and feet of the build's selection;
- a crank walker from the walkers package's model of that build;
- a two-wheeled build from its entry in robot/lego/wheeled/viewer.json:
  the printed files where they are placed, the bought parts as boxes.

reports/builds.json records, for each picture, the checksum of the PNG and
of everything it was drawn from; tests/test_builds.py compares both, so a
changed part or model cannot keep an old picture.

    python -m microduck.buildpics            redraw what is missing or out of date
    python -m microduck.buildpics --all      redraw everything
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from . import recipe, render

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "reports" / "builds.json"
SIZE = (400, 300)
VIEW = render.iso_view(40.0, 24.0)
VIEW_NOTE = "three-quarter view from the front left, 24 degrees above"
COLOURS = 48
MARGIN = 14                                  # white border in pixels
KIND_COLOURS = {"print": (236, 205, 120), "wheel": (236, 205, 120), "tyre": (60, 60, 66), "motor": (150, 156, 164),
                "controller": (70, 120, 170), "battery": (90, 110, 200)}


def _sha(parts: list) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def plan(data: dict, entry: dict, root: Path = ROOT) -> dict:
    """What a build's picture is drawn from: the kind of model, the names
    that select it, and the checksum of every input. Cheap: nothing is
    drawn and no mesh is loaded."""
    sel = recipe.build_selection(data, entry)
    rec = recipe.evaluate(data, sel)
    stls = sorted(item["file"] for item in rec["print"]["files"] if (root / "stl" / item["file"]).is_file())
    inputs = [(root / "stl" / name).read_bytes() for name in stls]
    out = {"selection": sel, "stls": stls}
    if sel["locomotion"] == "biped":
        out.update(kind="biped", source="the assembly model at the stand pose (microduck/model.py)")
        inputs += [(root / "config" / name).read_bytes() for name in ("assembly.json", "hardware.json")]
        report = json.loads((root / "reports" / "assembly.json").read_text(encoding="utf-8"))
        out["stand"] = report["variants"][report["selected"]]["balance"]["stand_pose"]["q_deg"]
        inputs.append(_json_bytes(out["stand"]))
    else:
        summary = recipe.summary_entry(sel, root) or {}
        if sel["locomotion"] == "crank" and summary.get("build"):
            out.update(kind="walker", build=summary["build"],
                       source=f"the walkers model of {summary['build']} (walkers/model.py)")
            inputs += [path.read_bytes() for path in sorted((root / "walkers" / "config").glob("*.json"))]
        elif sel["locomotion"] == "wheeled" and summary.get("id"):
            views = json.loads((root / "robot" / "lego" / "wheeled" / "viewer.json").read_text(encoding="utf-8"))
            view = views.get(summary["id"])
            if view is not None:
                out.update(kind="wheeled", variant=summary["id"], view=view,
                           source=f"robot/lego/wheeled/viewer.json, {summary['id']}")
                inputs.append(_json_bytes(view))
                names = sorted({item["file"] for item in view["stl"] + view["wheels"] if "file" in item})
                inputs += [(root / "stl" / name).read_bytes() for name in names]
        if "kind" not in out:
            # No model of the whole robot: the card shows the part pictures side by side.
            out.update(kind="parts", source="the part pictures of its printed files, side by side")
            inputs += [(root / "stl" / "thumbs" / (name[:-4] + ".png")).read_bytes() for name in stls
                       if (root / "stl" / "thumbs" / (name[:-4] + ".png")).is_file()]
    out["inputs_sha256"] = _sha([VIEW_NOTE, SIZE, COLOURS, out["kind"], _json_bytes(sel)] + inputs)
    return out


def _biped_items(job: dict) -> list:
    from . import model, report
    sel = job["selection"]
    config = model.load_json("assembly.json")
    config = dict(config, face=None if sel["face"] == "none" else sel["face"], camera=dict(config["camera"], preset=sel["camera"]))
    if "feet" in config:
        config["feet"] = sel["feet"]
    robot = model.build_robot(None, None, config)
    return report._items(robot.placed(job["stand"]))


def _walker_items(job: dict) -> list:
    from walkers import assembly, model
    walker = model.build_walker(job["build"])
    return assembly._items(walker)[:-1]          # without the floor slab


def _wheeled_items(job: dict, root: Path) -> list:
    view = job["view"]
    items = []

    def placed(item):
        mesh = trimesh.load_mesh(root / "stl" / item["file"])
        matrix = np.asarray(item["matrix"], float).reshape(4, 4)
        vertices = np.c_[mesh.vertices, np.ones(len(mesh.vertices))] @ matrix.T
        return vertices[:, :3], mesh.faces, KIND_COLOURS[item["kind"]]

    for item in view["stl"]:
        items.append(placed(item))
    for item in view["wheels"]:
        if "file" in item:
            items.append(placed(item))
            continue
        tyre = trimesh.creation.cylinder(radius=item["radius"], height=item["width"], sections=48)
        tyre.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0, [1.0, 0.0, 0.0]))
        tyre.apply_translation(item["centre"])
        items.append((tyre.vertices, tyre.faces, KIND_COLOURS["tyre"]))
    for item in view["boxes"]:
        lo, hi = np.minimum(item["min"], item["max"]), np.maximum(item["min"], item["max"])
        vertices, faces = render.box_mesh(lo, hi)
        items.append((vertices, faces, KIND_COLOURS[item["kind"]]))
    return items


def _frame(image: Image.Image) -> Image.Image:
    """Crop to what was drawn, centre it on a white card of SIZE."""
    pixels = np.asarray(image.convert("RGB"))
    drawn = np.argwhere((pixels < 250).any(axis=2))
    if len(drawn):
        (top, left), (bottom, right) = drawn.min(axis=0), drawn.max(axis=0) + 1
        image = image.crop((left, top, right, bottom))
    room = (SIZE[0] - 2 * MARGIN, SIZE[1] - 2 * MARGIN)
    scale = min(room[0] / image.width, room[1] / image.height)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    card = Image.new("RGB", SIZE, (255, 255, 255))
    card.paste(image, ((SIZE[0] - image.width) // 2, (SIZE[1] - image.height) // 2))
    return card


def _parts_sheet(job: dict, root: Path) -> Image.Image:
    thumbs = [root / "stl" / "thumbs" / (name[:-4] + ".png") for name in job["stls"]]
    thumbs = [path for path in thumbs if path.is_file()][:6]
    card = Image.new("RGB", SIZE, (255, 255, 255))
    columns = 3 if len(thumbs) > 2 else max(1, len(thumbs))
    rows = max(1, -(-len(thumbs) // columns))
    cell = (SIZE[0] // columns, SIZE[1] // rows)
    for index, path in enumerate(thumbs):
        picture = Image.open(path).convert("RGB")
        picture.thumbnail(cell, Image.LANCZOS)
        x = (index % columns) * cell[0] + (cell[0] - picture.width) // 2
        y = (index // columns) * cell[1] + (cell[1] - picture.height) // 2
        card.paste(picture, (x, y))
    return card


def draw(job: dict, root: Path = ROOT) -> Image.Image:
    if job["kind"] == "parts":
        image = _parts_sheet(job, root)
    else:
        items = {"biped": _biped_items, "walker": _walker_items}.get(job["kind"])
        items = items(job) if items else _wheeled_items(job, root)
        image = _frame(render.render(items, view=VIEW, size=(SIZE[0] * 2, SIZE[1] * 2), supersample=2, margin=0.02))
    return image.quantize(colors=COLOURS, dither=0)


def target(entry: dict, root: Path = ROOT) -> Path:
    """The picture's file in the repository. The site build copies
    docs/images to the site's images folder, which is the path the entry
    names."""
    return root / "docs" / entry["picture"]


def update(root: Path = ROOT, redraw_all: bool = False, log=print) -> dict:
    data = recipe.bundle(root)
    old = json.loads(RECORD.read_text(encoding="utf-8")).get("pictures", {}) if RECORD.is_file() else {}
    pictures = {}
    for entry in data["builds"]["list"]:
        job = plan(data, entry, root)
        path = target(entry, root)
        before = old.get(entry["id"], {})
        stale = (redraw_all or not path.is_file() or before.get("inputs_sha256") != job["inputs_sha256"]
                 or before.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest())
        if stale:
            path.parent.mkdir(parents=True, exist_ok=True)
            draw(job, root).save(path, optimize=True)
            log(f"drew {path.relative_to(root).as_posix()} from {job['source']}")
        pictures[entry["id"]] = {"file": path.relative_to(root).as_posix(), "drawn_from": job["source"], "kind": job["kind"],
                                 "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "inputs_sha256": job["inputs_sha256"]}
    record = {"generated_by": "python -m microduck.buildpics",
              "view": f"{SIZE[0]} x {SIZE[1]} px, {VIEW_NOTE}", "pictures": pictures}
    RECORD.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="redraw every picture")
    args = parser.parse_args(argv)
    record = update(redraw_all=args.all)
    total = sum(item["bytes"] for item in record["pictures"].values())
    print(f"{len(record['pictures'])} pictures, {total / 1e3:.0f} kB in docs/images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
