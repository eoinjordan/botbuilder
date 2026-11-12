# SPDX-License-Identifier: MIT
"""The finished builds on the landing page (config/builds.json): each is a
complete build tagged Simulated, with files, part pictures, a program where
one is written, figures for its card and a current picture of the whole
robot; Python and JavaScript resolve each to the same recipe."""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from conftest import ROOT
from microduck import buildpics, recipe

DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { buildSelection, evaluate } from "./build.mjs";
const data = JSON.parse(readFileSync("data.json", "utf8"));
writeFileSync("out.json", JSON.stringify(data.builds.list.map((entry) => {
  const selection = buildSelection(data, entry);
  return { selection, recipe: evaluate(data, selection) };
})));
"""


@pytest.fixture(scope="module")
def data(recipe_data):
    return recipe_data


@pytest.fixture(scope="module")
def written():
    return json.loads((ROOT / "config" / "builds.json").read_text(encoding="utf-8"))


def problems(data: dict, entry: dict, root=ROOT) -> list:
    """Why a finished build is not complete; empty when it is."""
    out = []
    rec = recipe.evaluate(data, recipe.build_selection(data, entry))
    if rec["status"] != "analysed" or rec["status_label"] != "Simulated":
        out.append(f"tagged {rec['status_label']}, not Simulated")
    files = rec["print"]["files"]
    if not files:
        out.append("no files to print")
    for item in files:
        if not item["link"] or not item["link"].startswith("./stl/") or not (root / "stl" / item["file"]).is_file():
            out.append(f"{item['file']} is not served")
        if not item["thumb"] or not (root / item["thumb"][2:]).is_file():
            out.append(f"{item['file']} has no picture")
    if not rec["parts"] or not rec["wiring"] or not rec["power"] or not rec["assembly"] or not rec["analysis"]:
        out.append("an empty section")
    has_program = any(all(rec["selection"][key] == value for key, value in program["match"].items()) for program in data["programs"])
    if has_program and not any(line.startswith("Program, ") for line in rec["firmware"]):
        out.append("its program is not in the recipe")
    if not rec["firmware"]:
        out.append("nothing under firmware")
    return out


def test_the_file_names_four_to_six_builds_in_order(data, written):
    listed = data["builds"]["list"]
    assert 4 <= len(listed) <= 6
    assert [item["id"] for item in listed] == [item["id"] for item in sorted(written["builds"], key=lambda item: item["order"])]
    assert len({item["id"] for item in listed}) == len(listed) and data["builds"]["default"] == listed[0]["id"]
    known = {dim["id"]: [option["id"] for option in dim["options"]] for dim in data["compat"]["dimensions"]}
    for item in listed:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", item["id"]), item["id"]
        assert item["name"] and len(item["name"]) <= 32 and 20 <= len(item["description"]) <= 110 and "\n" not in item["description"]
        assert re.fullmatch(r"images/build-[a-z0-9-]+\.png", item["picture"])
        for key, value in item["selection"].items():
            assert value in known[key], f"{item['id']}: {key}={value}"
        assert {"controller", "locomotion", "drive"} <= set(item["selection"])
    # The range: the two bipeds, the crank walkers and a two-wheeled build, on more than one controller.
    assert {item["selection"]["locomotion"] for item in listed} == {"biped", "biped_look", "crank", "wheeled"}
    assert len({item["selection"]["controller"] for item in listed}) >= 4
    wheeled = [item for item in listed if item["selection"]["locomotion"] == "wheeled"]
    assert all(item["selection"]["wheels"] == "back" for item in wheeled)


def test_the_biped_follows_the_default_camera(data, written):
    """The biped's camera is not written in the build: it is the one switch
    in config/assembly.json, so changing that switch changes the card too."""
    design = json.loads((ROOT / "config" / "assembly.json").read_text(encoding="utf-8"))
    for item in written["builds"]:
        if item["selection"]["locomotion"] != "biped":
            continue
        assert "camera" not in item["selection"]
        entry = next(e for e in data["builds"]["list"] if e["id"] == item["id"])
        assert recipe.build_selection(data, entry)["camera"] == design["camera"]["preset"] == data["compat"]["defaults"]["camera"]


def test_every_build_is_simulated_and_complete(data):
    for entry in data["builds"]["list"]:
        assert problems(data, entry) == [], entry["id"]
        rec = recipe.evaluate(data, recipe.build_selection(data, entry))
        assert rec["refusal"] == [] and rec["nearest"] is None
        for key, value in entry["selection"].items():
            assert rec["selection"][key] == value, "the fields the build names are kept"


def test_a_build_that_is_no_longer_simulated_is_reported(data):
    """The check above fails for a lesser tag instead of showing it."""
    lesser = copy.deepcopy(data)
    lesser["variants"] = []
    lesser["coverage"]["entries"] = []
    for entry in lesser["builds"]["list"]:
        assert any("not Simulated" in text for text in problems(lesser, entry)), entry["id"]
    unpictured = copy.deepcopy(data)
    for about in unpictured["manifest"]["info"].values():
        about["thumb"] = None
    assert all(any("no picture" in text for text in problems(unpictured, entry)) for entry in unpictured["builds"]["list"])


def test_every_build_has_figures_from_the_reports(data, sim_report, selected):
    summary = json.loads((ROOT / "reports" / "variants" / "summary.json").read_text(encoding="utf-8"))["entries"]
    for entry in data["builds"]["list"]:
        figures = entry["figures"]
        assert set(figures) == {"mass_g", "speed_mm_s"}, entry["id"]
        assert 100 < figures["mass_g"] < 2000 and 5 < figures["speed_mm_s"] < 2000
        sel = recipe.build_selection(data, entry)
        if sel["locomotion"] == "biped_look":
            look = json.loads((ROOT / "reports" / "microduck-look" / "summary.json").read_text(encoding="utf-8"))
            mine = recipe.summary_entry(sel, ROOT)
            assert mine in look["entries"] and mine["feet"] == sel["feet"] and mine["status"] == "analysed in simulation"
            assert figures == {"mass_g": mine["mass_g"], "speed_mm_s": look["walking_speed_by_feet"][sel["feet"]]["speed_mm_s"]}
            assert f"Mass {mine['mass_g']:g} g by the model." in recipe.evaluate(data, sel)["analysis"]
            continue
        if sel["locomotion"] == "biped":
            study = json.loads((ROOT / "reports" / "motion.json").read_text(encoding="utf-8"))
            walk = study["presets"][sel["feet"]]["walk"]["nominal"]["speed_mm_s"]
            assert figures == {"mass_g": selected["mass"]["total_g"], "speed_mm_s": walk}
            assert f"walks at {walk:g} mm/s" in sim_report["verdict"]["gait"], "the figure the verdict quotes"
        else:
            mine = recipe.summary_entry(sel, ROOT)
            assert mine in summary and mine["status"] == "analysed in simulation" and figures["mass_g"] == mine["mass_g"]
            assert f"Mass {mine['mass_g']:g} g by the model." in recipe.evaluate(data, sel)["analysis"]


def test_every_build_has_a_current_picture(data):
    record = json.loads((ROOT / "reports" / "builds.json").read_text(encoding="utf-8"))
    assert set(record["pictures"]) == {entry["id"] for entry in data["builds"]["list"]}
    for entry in data["builds"]["list"]:
        about = record["pictures"][entry["id"]]
        path = ROOT / about["file"]
        assert path == buildpics.target(entry) and path.is_file(), entry["id"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == about["sha256"] and len(content) == about["bytes"]
        job = buildpics.plan(data, entry)
        assert job["inputs_sha256"] == about["inputs_sha256"], (
            f"{entry['id']}: the picture is older than what it is drawn from; run python -m microduck.buildpics")
        assert about["kind"] == job["kind"] and about["drawn_from"] == job["source"]
        with Image.open(path) as image:
            assert image.size == buildpics.SIZE and image.mode == "P"
            assert len(image.getcolors()) > 4, "not a blank card"
        assert len(content) < 20_000, "card pictures stay small"


def test_the_look_card_is_on_the_feet_that_walk_faster(data, written):
    """The Microduck-look card names its feet, and names the set that the
    simulation walks faster on; its recipe gives the source model and the
    terms of its parts."""
    look = json.loads((ROOT / "reports" / "microduck-look" / "summary.json").read_text(encoding="utf-8"))
    card = next(item for item in written["builds"] if item["selection"]["locomotion"] == "biped_look")
    speeds = look["walking_speed_by_feet"]
    assert card["selection"]["feet"] == speeds["faster"]
    assert speeds[speeds["faster"]]["truly_steps"] and not speeds[speeds["faster"]]["poses_with_mesh_overlap"]
    entry = next(e for e in data["builds"]["list"] if e["id"] == card["id"])
    rec = recipe.evaluate(data, recipe.build_selection(data, entry))
    assert rec["flash"] == "look" and rec["base"] == "unoq_braccio"
    assert any("Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl" in text and "CC BY-NC-SA 4.0" in text
               for text in rec["reasons"])
    names = [item["file"] for item in rec["print"]["files"]]
    comb = card["selection"]["feet"] == "comb"
    assert ("microduck-look/left_foot_comb.stl" in names) == comb and ("microduck-look/left_foot.stl" in names) != comb
    job = buildpics.plan(data, entry)
    assert job["kind"] == "look" and job["feet"] == ("comb" if comb else "web")


def test_the_site_gets_the_builds_and_their_pictures():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True, capture_output=True)
    shipped = json.loads((ROOT / "site" / "data" / "recipe.json").read_text(encoding="utf-8"))
    assert shipped["builds"] == recipe.bundle(ROOT)["builds"]
    for entry in shipped["builds"]["list"]:
        assert (ROOT / "site" / entry["picture"]).read_bytes() == buildpics.target(entry).read_bytes()
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "site" / "build.js").read_text(encoding="utf-8")
    # No build is written into the page: names, ids and pictures come from the data.
    for entry in shipped["builds"]["list"]:
        for text in (entry["name"], entry["picture"], f'"{entry["id"]}"'):
            assert text not in html and text not in script, text
    assert "data.builds.list" in script and "build=${card.id}" in script and "linked.build" in script
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "'config/**'" in pages and "'docs/images/**'" in pages


def test_javascript_resolves_the_builds_as_python_does(data, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; site/build.js was not run")
    shutil.copyfile(ROOT / "site" / "build.js", tmp_path / "build.mjs")
    (tmp_path / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    subprocess.run([node, "driver.mjs"], cwd=tmp_path, check=True, capture_output=True, timeout=120)
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert len(got) == len(data["builds"]["list"])
    for entry, theirs in zip(data["builds"]["list"], got):
        selection = recipe.build_selection(data, entry)
        assert theirs["selection"] == selection, entry["id"]
        assert theirs["recipe"] == recipe.evaluate(data, selection), entry["id"]
        assert theirs["recipe"]["status_label"] == "Simulated"
