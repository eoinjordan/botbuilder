# SPDX-License-Identifier: MIT
"""Assemble the static site in site/ for GitHub Pages.

Copies the generated reports, the viewer model and the pictures next to the
hand-written index.html, style.css and app.js. Standard library only, so the
Pages workflow needs no installs.

    python scripts/build_site.py [--with-meshes]

--with-meshes also copies the printable STLs from build/stl into
site/data/meshes for a local preview with the real part shapes. Do not
publish that directory until the licence of the source meshes is settled
(see NOTICE); it is ignored by git and the Pages workflow never passes the flag.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = {
    "assembly.json": ROOT / "reports" / "assembly.json",
    "sim.json": ROOT / "reports" / "sim.json",
    "joints.json": ROOT / "robot" / "joints.json",
    "model.json": ROOT / "robot" / "model.json",
    "hardware.json": ROOT / "config" / "hardware.json",
    # walkers.html
    "lego-assembly.json": ROOT / "reports" / "lego" / "assembly.json",
    "lego-sim.json": ROOT / "reports" / "lego" / "sim.json",
    "lego-manifest.json": ROOT / "stl" / "lego" / "manifest.json",
    "lego-model-ev3-pixy2.json": ROOT / "robot" / "lego" / "ev3-pixy2.json",
    "lego-model-pi-zero-2w-51515.json": ROOT / "robot" / "lego" / "pi-zero-2w-51515.json",
    "variants-summary.json": ROOT / "reports" / "variants" / "summary.json",
    "wheeled-analysis.json": ROOT / "reports" / "wheeled" / "analysis.json",
    "wheeled-sim.json": ROOT / "reports" / "wheeled" / "sim.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-meshes", action="store_true")
    args = parser.parse_args()

    data = SITE / "data"
    images = SITE / "images"
    for folder in (data, images):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
    for name, source in DATA.items():
        # Minified copies: the site only reads them.
        with open(source, encoding="utf-8") as handle:
            content = json.load(handle)
        if name == "model.json":
            content["meshes_published"] = bool(args.with_meshes)
        (data / name).write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8", newline="\n")
    count = 0
    for picture in sorted((ROOT / "docs" / "images").iterdir()):
        if picture.suffix in (".png", ".gif"):
            shutil.copyfile(picture, images / picture.name)
            count += 1
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    # The walkers' printable parts are published; walkers.html links them.
    for stl in sorted((ROOT / "stl" / "lego").rglob("*.stl")):
        target = SITE / "stl" / "lego" / stl.relative_to(ROOT / "stl" / "lego")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stl, target)
    if args.with_meshes:
        source = ROOT / "build" / "stl"
        if not source.is_dir():
            print("no build/stl: run scripts/fetch_stls.py first", file=sys.stderr)
            return 1
        (data / "meshes").mkdir()
        for stl in sorted(source.glob("*.stl")):
            shutil.copyfile(stl, data / "meshes" / stl.name)
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"site built: {len(DATA)} data files, {count} pictures, {size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
