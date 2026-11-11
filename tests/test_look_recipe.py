# SPDX-License-Identifier: MIT
"""The configurator offers the Microduck-look build, with its licence line,
and the six-servo biped's recipe is as it was."""
import json

import pytest

from conftest import ROOT
from microduck import recipe
from microduck.look import model

LINE = "Microduck-look parts: CC BY-NC-SA 4.0, adapted from Pollen Robotics' Microduck; not for commercial use"
SELECTION = {"controller": "unoq", "locomotion": "biped_look", "drive": "braccio_two_shields", "camera": "esp_eye"}

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
    entry = load("reports", "microduck-look", "summary.json")["entries"][0]
    assert entry["style"] == "microduck" and entry["title"] == "Biped, Microduck look" and entry["licence_line"] == LINE
    # the plate biped is as it was: none of these files, none of these parts
    assert " ".join(LINE.split()) in " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    plates = recipe.evaluate(recipe_data, {"controller": "unoq", "locomotion": "biped", "drive": "braccio_shield"})
    assert not any(item["file"].startswith("microduck-look/") for item in plates["print"]["files"])
    assert recipe.evaluate(recipe_data, dict(SELECTION, head="sg90_pan"))["refusal"] == ["look-head-has-its-own-servos"]
    assert recipe.evaluate(recipe_data, dict(SELECTION, controller="pi"))["status"] == "not_possible"
