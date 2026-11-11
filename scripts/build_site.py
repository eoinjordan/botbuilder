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

ROOT =Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT))
from microduck import recipe  # noqa: E402  (standard library only)
OPTIONAL_PAGES = ("walkers.html", "flash.html", "control.html")
DATA = {
    "assembly.json": ROOT / "reports" / "assembly.json",
    "sim.json": ROOT / "reports" / "sim.json",
    "joints.json": ROOT / "robot" / "joints.json",
    "model.json": ROOT / "robot" / "model.json",
    "hardware.json": ROOT / "config" / "hardware.json",
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
    # The printable parts, as downloads and for the 3D view.
    with open(ROOT / "stl" / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)
    for name in [entry["file"] for entry in manifest["files"]] + ["manifest.json", "parameters.json"]:
        shutil.copyfile(ROOT / "stl" / name, parts / name)
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"site built: {len(DATA)} data files, {count} pictures, {len(manifest['files'])} STLs, {size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
