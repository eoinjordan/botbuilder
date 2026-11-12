# SPDX-License-Identifier: MIT
"""The configurator offers the Microduck-look build, with its licence line,
and the six-servo biped's recipe is as it was."""
import json

import pytest

from conftest import ROOT
from microduck import recipe
from microduck.look import model

LINE = "Microduck-look parts: CC BY-NC-SA 4.0, adapted from Pollen Robotics' Microduck; not for commercial use"
SELECTION = {"controller": "unoq", "locomotion": "biped_look", "drive": "braccio_two_shields", "camera": "esp_eye", "feet": "flat"}

pytestmark = pytest.mark.skipif(not model.have_parts(), reason="stl/microduck-look is not there")


def load(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


def test_the_configurator_offers_it(recipe_data):
    rec = recipe.evaluate(recipe_data, SELECTION)
    assert rec["labels"]["locomotion"].startswith("Biped, Microduck look")
    assert rec["status"] == "analysed" and rec["refusal"] == []
    assert any(LINE in text for text in rec["reasons"])
    files = rec["print"]["files"]
    assert len(files) == 28 and all(item["link"] == "./stl/" + item["file"] and item["thumb"] for item in files)
    assert files[0]["fit"] and not files[-1]["fit"]
    names = " ".join(part["name"] for part in rec["parts"])
    assert "M5Stack Servo Kit 180" in names and "PCA9685" in names
    assert any("Not written for fifteen joints" in line for line in rec["firmware"])
    assert any("One supply per shield" in line for line in rec["power"])
    summary = load("reports", "microduck-look", "summary.json")
    entry = summary["entries"][0]
    assert entry["style"] == "microduck" and entry["title"] == "Biped, Microduck look" and entry["licence_line"] == LINE
    assert entry["feet"] == "flat" and [e["feet"] for e in summary["entries"]] == ["flat", "comb"]
    assert summary["source_model"] == "Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl"
    # the plate biped is as it was: none of these files, none of these parts
    assert " ".join(LINE.split()) in " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    plates = recipe.evaluate(recipe_data, {"controller": "unoq", "locomotion": "biped", "drive": "braccio_shield"})
    assert not any(item["file"].startswith("microduck-look/") for item in plates["print"]["files"])
    assert recipe.evaluate(recipe_data, dict(SELECTION, head="sg90_pan"))["refusal"] == ["look-head-has-its-own-servos"]
    assert recipe.evaluate(recipe_data, dict(SELECTION, controller="pi"))["status"] == "not_possible"


def test_the_feet_are_a_choice(recipe_data):
    """Comb or plain feet: each gives the same build with its own two feet,
    its own numbers from the summary and no flash steps of the six-joint agent."""
    flat = recipe.evaluate(recipe_data, SELECTION)
    comb = recipe.evaluate(recipe_data, dict(SELECTION, feet="comb"))
    assert flat["labels"]["feet"] == "Flat feet" and comb["labels"]["feet"] == "Comb feet"
    assert "feet=flat" in flat["query"] and "feet=comb" in comb["query"]
    for rec in (flat, comb):
        assert rec["status"] == "analysed" and rec["refusal"] == [] and rec["flash"] == "look"
        files = [item["file"] for item in rec["print"]["files"]]
        assert len(files) == 28 and all(item["thumb"] and item["link"] for item in rec["print"]["files"])
        assert any(LINE in text for text in rec["reasons"])
    names = lambda rec: {item["file"] for item in rec["print"]["files"]}      # noqa: E731
    assert names(comb) - names(flat) == {"microduck-look/left_foot_comb.stl", "microduck-look/right_foot_comb.stl"}
    assert names(flat) - names(comb) == {"microduck-look/left_foot.stl", "microduck-look/right_foot.stl"}
    assert any(line.startswith("Comb feet:") for line in comb["assembly"]) and not any(line.startswith("Comb feet:") for line in flat["assembly"])
    summary = load("reports", "microduck-look", "summary.json")
    speeds = summary["walking_speed_by_feet"]
    study = load("reports", "microduck-look", "sim.json")
    assert speeds["flat"]["speed_mm_s"] == study["walk"]["speed_mm_s"]
    assert speeds["comb"]["speed_mm_s"] == study["comb_feet"]["walk"]["speed_mm_s"]
    for option, rec in (("flat", flat), ("comb", comb)):
        assert any(f"{speeds[option]['speed_mm_s']} mm/s" in line for line in rec["analysis"]), option
    # the plate biped keeps its own feet files
    plates = recipe.evaluate(recipe_data, {"controller": "unoq", "locomotion": "biped", "drive": "braccio_shield", "feet": "comb"})
    assert any(item["file"] == "left_shin_comb_foot.stl" for item in plates["print"]["files"])
    assert not any(item["file"].startswith("microduck-look/") for item in plates["print"]["files"]) and plates["flash"] == "unoq_braccio"
