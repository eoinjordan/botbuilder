# SPDX-License-Identifier: MIT
"""Assemble the static site in site/ for GitHub Pages.

Copies the generated reports, the viewer model and the pictures next to the
hand-written pages, style sheets and scripts. Standard library only, so the
Pages workflow needs no installs.

    python scripts/build_site.py

The printable STLs in stl/ are copied to site/stl with their manifest, as
downloads and for the 3D view.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT))
from microduck import recipe  # noqa: E402  (standard library only)
OPTIONAL_PAGES = ("wheeled.html", "walkers.html", "flash.html", "control.html")
DATA = {
    "assembly.json": ROOT / "reports" / "assembly.json",
    "sim.json": ROOT / "reports" / "sim.json",
    "joints.json": ROOT / "robot" / "joints.json",
    "model.json": ROOT / "robot" / "model.json",
    "hardware.json": ROOT / "config" / "hardware.json",
    # biped.html and control.html: the motion study and the leg clearance table
    "motion.json": ROOT / "reports" / "motion.json",
    "gait_params.json": ROOT / "trajectories" / "gait_params.json",
    "clearance.json": ROOT / "robot" / "clearance.json",
    # walkers.html
    "lego-assembly.json": ROOT / "reports" / "lego" / "assembly.json",
    "lego-sim.json": ROOT / "reports" / "lego" / "sim.json",
    "lego-manifest.json": ROOT / "stl" / "lego" / "manifest.json",
    "lego-model-ev3-pixy2.json": ROOT / "robot" / "lego" / "ev3-pixy2.json",
    "lego-model-pi-zero-2w-51515.json": ROOT / "robot" / "lego" / "pi-zero-2w-51515.json",
    "lego-model-hub-51515.json": ROOT / "robot" / "lego" / "hub-51515.json",
    "variants-summary.json": ROOT / "reports" / "variants" / "summary.json",
    "wheeled-analysis.json": ROOT / "reports" / "wheeled" / "analysis.json",
    "wheeled-sim.json": ROOT / "reports" / "wheeled" / "sim.json",
    "wheeled-viewer.json": ROOT / "robot" / "lego" / "wheeled" / "viewer.json",
    "programs-index.json": ROOT / "programs" / "index.json",
    # biped.html: the Microduck-look biped
    "look-summary.json": ROOT / "reports" / "microduck-look" / "summary.json",
    # tour.js, on every page
    "tour.json": ROOT / "config" / "tour.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()

    data = SITE / "data"
    images = SITE / "images"
    parts = SITE / "stl"
    for folder in (data, images, parts):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
    for name, source in DATA.items():
        # Minified copies: the site only reads them.
        with open(source, encoding="utf-8") as handle:
            content = json.load(handle)
        if name == "model.json":
            content["meshes_published"] = True
        (data / name).write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8", newline="\n")
    # Control page: the motion manifest and the trajectories it names.
    from microduck import motions  # standard library only
    motions.export(data)
    # Build yours: compatibility data, bases, report facts, STL manifest and variants summary in one file.
    (data / "recipe.json").write_text(json.dumps(recipe.bundle(ROOT), separators=(",", ":")), encoding="utf-8", newline="\n")
    # Pages other branches add. nav.js shows a link only for a page listed here.
    pages = [name for name in OPTIONAL_PAGES if (SITE / name).is_file()]
    (data / "pages.json").write_text(json.dumps(pages), encoding="utf-8", newline="\n")
    count = 0
    for picture in sorted((ROOT / "docs" / "images").iterdir()):
        if picture.suffix in (".png", ".gif"):
            shutil.copyfile(picture, images / picture.name)
            count += 1
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    # The printable parts, as downloads and for the 3D views: every file the manifest lists,
    # in its folder, and the part pictures the recipes show.
    with open(ROOT / "stl" / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for name in [entry["file"] for entry in manifest["files"]] + ["manifest.json", "parameters.json"]:
        (parts / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "stl" / name, parts / name)
    if (ROOT / "stl" / "thumbs").is_dir():
        shutil.copytree(ROOT / "stl" / "thumbs", parts / "thumbs")
    # The Microduck-look parts carry their own terms: their licence, credit and pictures go with them.
    look = ROOT / "stl" / "microduck-look"
    if (look / "LICENSE").is_file():
        (parts / "microduck-look").mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE", "parameters.json", "comb_feet.json"):
            if (look / name).is_file():
                shutil.copyfile(look / name, parts / "microduck-look" / name)
        if (look / "images").is_dir():
            shutil.copytree(look / "images", parts / "microduck-look" / "images")
    # Pictures of the bought components: photographs and drawings, credited on credits.html.
    if (SITE / "components").exists():
        shutil.rmtree(SITE / "components")
    (SITE / "components").mkdir()
    for picture in sorted((ROOT / "docs" / "components").glob("*.png")) + sorted((ROOT / "docs" / "components").glob("*.jpg")):
        shutil.copyfile(picture, SITE / "components" / picture.name)
    # Photos the owner attached to his checks, at the path the records name.
    if (SITE / "docs").exists():
        shutil.rmtree(SITE / "docs")
    if (ROOT / "docs" / "validated").is_dir():
        shutil.copytree(ROOT / "docs" / "validated", SITE / "docs" / "validated")
    # The programs, each at a stable plain address: programs/<controller>/<build>/<file>.py.
    if (SITE / "programs").exists():
        shutil.rmtree(SITE / "programs")
    for program in sorted((ROOT / "programs").rglob("*.py")):
        target = SITE / "programs" / program.relative_to(ROOT / "programs")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(program, target)
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"site built: {len(DATA)} data files, {count} pictures, {len(manifest['files'])} STLs, {size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
