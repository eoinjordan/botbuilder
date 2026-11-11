# SPDX-License-Identifier: MIT
"""Pictures of the bought components: every choice in the configurator and
every bought part of a recipe has a picture with a recorded origin and
licence, every credited picture exists, the drawings are current, and the
credits page says what the data file says."""
import hashlib
import json
import re
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from conftest import ROOT
from microduck import componentpics, recipe

# Licences a photograph may carry, as Wikimedia Commons names them.
OPEN = re.compile(r"^(CC0( 1\.0)?|Public domain|CC BY(-SA)? [1-4]\.[05]( [a-z]{2})?)$")
# Parts of a recipe that are printed, not bought: they have no picture (not_bought in the data file).
PRINTED = ("Printed ", "TPU ", "Drag skid")
DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { componentFor, optionComponent, evaluate, buildSelection } from "./build.mjs";
import { recipePdf } from "./export.mjs";
const data = JSON.parse(readFileSync("data.json", "utf8"));
const names = JSON.parse(readFileSync("names.json", "utf8"));
const options = [];
for (const dim of data.compat.dimensions) for (const option of dim.options) {
  const about = optionComponent(data, dim.id, option.id);
  options.push([dim.id, option.id, about ? about.id : null]);
}
const recipe = evaluate(data, buildSelection(data, data.builds.list[data.builds.list.length - 1]));
const parts = recipe.parts.map((part) => componentFor(data, part.name));
const images = {};
for (const about of parts) if (about) images[about.picture] = new Uint8Array(readFileSync(process.argv[2] + "/" + about.picture.slice(2)));
const meta = { url: "https://example.org/?build=x", date: "2026-11-11", selection: [], titles: [],
  parts: parts.map((about) => (about ? about.picture : null)),
  credits: [...new Set(parts.filter(Boolean).map((about) => about.credit_line).filter(Boolean))],
  creditsUrl: "https://example.org/credits.html" };
writeFileSync("with.pdf", recipePdf(recipe, images, meta));
writeFileSync("without.pdf", recipePdf(recipe, {}, { url: meta.url, date: meta.date, selection: [], titles: [] }));
writeFileSync("out.json", JSON.stringify({ parts: names.map((name) => { const about = componentFor(data, name); return about ? about.id : null; }),
  options, credits: meta.credits }));
"""


@pytest.fixture(scope="module")
def data(recipe_data):
    return recipe_data


@pytest.fixture(scope="module")
def written():
    return json.loads((ROOT / "config" / "component_images.json").read_text(encoding="utf-8"))


def on_disk(picture: str):
    """The repository file behind a picture's address on the site."""
    assert picture.startswith("./"), picture
    folder, _, rest = picture[2:].partition("/")
    return {"components": ROOT / "docs" / "components", "images": ROOT / "docs" / "images", "stl": ROOT / "stl"}[folder] / rest


def test_every_choice_has_a_picture(data):
    by_id = {entry["id"]: entry for entry in data["components"]["list"]}
    assert len(by_id) == len(data["components"]["list"]), "component ids are unique"
    for dim in data["compat"]["dimensions"]:
        for option in dim["options"]:
            component = data["components"]["options"].get(dim["id"], {}).get(option["id"])
            assert component in by_id, f"{dim['id']}={option['id']} has no picture entry"
            assert by_id[component]["picture"] and on_disk(by_id[component]["picture"]).is_file(), f"{dim['id']}={option['id']}"
    # Nothing in the map that is not a choice.
    known = {dim["id"]: {option["id"] for option in dim["options"]} for dim in data["compat"]["dimensions"]}
    assert {key: set(value) for key, value in data["components"]["options"].items()} == known


def test_every_bought_part_of_every_recipe_has_a_picture(data, all_recipes):
    names = {part["name"] for rec in all_recipes for part in rec["parts"]}
    assert len(names) > 80
    for name in sorted(names):
        about = recipe.component_for(data, name)
        if name.startswith(PRINTED):
            assert about is None, f"{name}: a printed part takes no component picture"
            continue
        assert about is not None, f"{name}: no component matches"
        assert about["picture"] and on_disk(about["picture"]).is_file(), name
        assert about["kind"] in ("photo", "drawing"), f"{name}: a bought part shows a photograph or a drawing"
    # The finished builds, by name: nothing in their parts lists is left without a picture.
    for entry in data["builds"]["list"]:
        rec = recipe.evaluate(data, recipe.build_selection(data, entry))
        assert all(recipe.component_for(data, part["name"]) for part in rec["parts"]), entry["id"]
    # A few that depend on the order of the list.
    expect = {"Switch in the servo supply, within reach": "switch", "Pixy2 with the pan-tilt kit and the EV3 cable": "pixy_pantilt",
              "Pixy2 LEGO cable": "pixy2", "Raspberry Pi Camera Module 2 with a Zero-series ribbon": "picam2",
              "CSI ribbon to suit the Pi": "ribbon", "Servo horn with centre screw (from the kit)": "servo_horn",
              "Horn screws for the printed blanks": "screws", "8 V supply for the Build HAT, or a 7.2 to 8.5 V battery": "supply",
              "16-channel I2C PWM servo driver board (PCA9685 type)": "pca9685", "LEGO wheel with tyre, on a Technic cross axle": "lego_wheel",
              "Technic half bush": "technic_bush", "Stock 65 mm TT wheel with rubber tyre": "tt_wheel"}
    for name, component in expect.items():
        assert recipe.component_for(data, name)["id"] == component, name


def test_every_picture_has_an_origin_and_a_licence(written):
    kinds = {"photo": 0, "drawing": 0, "render": 0}
    for entry in written["components"]:
        kinds[entry["kind"]] += 1
        assert entry["name"] and entry["origin"], entry["id"]
        assert all(pattern == pattern.lower() and pattern for pattern in entry["match"]), entry["id"]
        if entry["kind"] == "render":
            assert sum(key in entry for key in ("stl", "manifest", "build", "wheeled_model")) == 1, entry["id"]
            continue
        path = ROOT / "docs" / "components" / entry["file"]
        assert path.is_file(), f"{entry['id']}: {entry['file']} is credited but not there"
        assert path.stat().st_size <= 30_000, f"{entry['id']}: {path.stat().st_size} bytes"
        with Image.open(path) as image:
            assert image.size == (320, 240), entry["id"]
            assert image.mode == "P" or path.suffix == ".jpg", "an 8-bit PNG is what the PDF can hold"
        if entry["kind"] == "drawing":
            assert "python -m microduck.componentpics" in entry["origin"], entry["id"]
            continue
        # A photograph: who made it, under which licence, and where it is.
        assert entry["author"].strip() and entry["licence"].strip(), entry["id"]
        assert entry["origin"] in ("Wikimedia Commons", "own photograph"), entry["id"]
        if entry["origin"] == "Wikimedia Commons":
            assert OPEN.match(entry["licence"]), f"{entry['id']}: {entry['licence']}"
            assert entry["title"].startswith("File:")
            assert entry["source_url"].startswith("https://commons.wikimedia.org/wiki/File:"), entry["id"]
            if entry["licence"].startswith("CC"):
                assert re.match(r"https?://creativecommons\.org/", entry["licence_url"]), entry["id"]
            assert "cropped" in entry["changes"] or "resized" in entry["changes"], "what was changed is stated"
            assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), f"{entry['id']}: not the file that was fetched"
    assert kinds["photo"] >= 10 and kinds["drawing"] >= 10
    folder = {path.name for path in (ROOT / "docs" / "components").iterdir()} - {"README.md"}
    assert folder == {entry["file"] for entry in written["components"] if "file" in entry}, "no picture without an entry"


def test_the_drawings_are_current(written):
    record = json.loads((ROOT / "reports" / "component_images.json").read_text(encoding="utf-8"))["pictures"]
    dims = componentpics.Dimensions(ROOT)
    made = [entry for entry in written["components"] if componentpics.generated(entry)]
    assert set(record) == {entry["id"] for entry in made}
    for entry in made:
        about = record[entry["id"]]
        path = ROOT / about["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == about["sha256"], entry["id"]
        assert componentpics.inputs_sha(entry, dims) == about["inputs_sha256"], (
            f"{entry['id']}: older than its dimensions; run python -m microduck.componentpics")
        if entry["kind"] == "drawing" and not entry.get("blank"):
            assert entry["id"] in componentpics.DRAWINGS
            source = about["dimensions_from"].split(" ")[0]
            assert (ROOT / source).is_file() and source.split("/")[-1] in entry["origin"], entry["id"]


def test_the_credits_page_says_what_the_data_says(written):
    page = (ROOT / "site" / "credits.html").read_text(encoding="utf-8")
    assert page == componentpics.credits_html(ROOT), "run python -m microduck.componentpics --credits"
    assert "<h1>Picture credits</h1>" in page and page.isascii()
    for entry in written["components"]:
        if entry["kind"] == "render":
            continue
        assert f'src="./components/{entry["file"]}"' in page, entry["id"]
        if entry["kind"] == "photo":
            assert componentpics._text(entry["author"]) in page and componentpics._text(entry["source_url"]) in page, entry["id"]
            assert f">{entry['licence']}</a>" in page or f"<td>{entry['licence']}</td>" in page, entry["id"]
        else:
            assert "Drawing, not a photograph" in page
    for name in sorted(path.name for path in (ROOT / "site").glob("*.html")):
        html = (ROOT / "site" / name).read_text(encoding="utf-8")
        assert '<a href="./credits.html">Picture credits</a>' in html.split("<footer>")[1], name
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "config/component_images.json" in notice and "site/credits.html" in notice
    readme = (ROOT / "docs" / "components" / "README.md").read_text(encoding="utf-8")
    assert "own photograph" in readme and "config/component_images.json" in readme


def test_the_site_serves_the_pictures_and_shows_them():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    shipped = json.loads((ROOT / "site" / "data" / "recipe.json").read_text(encoding="utf-8"))["components"]
    for entry in shipped["list"]:
        assert (ROOT / "site" / entry["picture"][2:]).read_bytes() == on_disk(entry["picture"]).read_bytes(), entry["id"]
    script = (ROOT / "site" / "build.js").read_text(encoding="utf-8")
    # Served from the site, never hot-linked; lazy; named by the component.
    assert "https://upload.wikimedia.org" not in script and "commons.wikimedia.org" not in script
    assert 'chosen.loading = "lazy"' in script and "picture.alt = about.name" in script and "shown.chosen.alt = about.name" in script
    # The native select stays; the pictures are buttons that set it.
    assert 'select.dispatchEvent(new Event("change", { bubbles: true }));' in script and 'card.setAttribute("aria-pressed"' in script
    for entry in shipped["list"]:
        assert f'"{entry["id"]}"' not in script, "no component is written into the page"


def test_javascript_matches_parts_as_python_does_and_the_pdf_carries_the_credits(data, all_recipes, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; site/build.js was not run")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    names = sorted({part["name"] for rec in all_recipes for part in rec["parts"]})
    shutil.copyfile(ROOT / "site" / "build.js", tmp_path / "build.mjs")
    shutil.copyfile(ROOT / "site" / "export.js", tmp_path / "export.mjs")
    (tmp_path / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "names.json").write_text(json.dumps(names), encoding="utf-8")
    subprocess.run([node, "driver.mjs", str(ROOT / "site")], cwd=tmp_path, check=True, capture_output=True, timeout=120)
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    mine = [recipe.component_for(data, name) for name in names]
    assert got["parts"] == [about["id"] if about else None for about in mine]
    assert got["options"] == [[dim["id"], option["id"], data["components"]["options"][dim["id"]][option["id"]]]
                              for dim in data["compat"]["dimensions"] for option in dim["options"]]
    pdf, plain = (tmp_path / "with.pdf").read_bytes(), (tmp_path / "without.pdf").read_bytes()
    assert pdf.count(b"/Subtype /Image") > plain.count(b"/Subtype /Image") == 0
    assert b"(Picture credits) Tj" in pdf and b"(Picture credits) Tj" not in plain
    assert b"credits.html" in pdf and got["credits"]
    # The credits are on the last page, after the recipe's own link.
    assert pdf.rindex(b"(Picture credits) Tj") > pdf.rindex(b"(This recipe) Tj")
    for line in got["credits"]:
        assert ("photograph by" in line and "Wikimedia Commons" in line) or "not a photograph" in line, line
