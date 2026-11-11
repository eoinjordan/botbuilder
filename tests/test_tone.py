# SPDX-License-Identifier: MIT
"""How the site and the recipes speak. The owner prints and checks each
build himself, so pages and recipes do not carry validation caveats, and
they do not claim the opposite either: nothing says a build was printed,
assembled or tested unless config/validated.json records it. Safety
instructions, "print the fit pieces first", "measure" on parts that will not
fit otherwise, and "Not written" for software that does not exist all stay.
The detail lives in docs/status.md."""
import json
import re

import pytest

from conftest import ROOT
from microduck import recipe

SITE = ROOT / "site"
PAGES = sorted(path.name for path in SITE.glob("*.html"))
# Validation caveats that are not repeated on pages or in recipes.
CAVEATS = ("never been assembled", "verified in simulation only", "not run on hardware", "physically built", "never built",
           "never printed", "none has been printed", "not validated", "unverified", "not verified", "not fit-tested", "untested",
           "(published)", "(assumed)", "not a tested build", "not a build recipe")
# Claims that only the owner's own record may make.
CLAIMS = re.compile(r"printed and checked|tested on hardware|runs on hardware|has been (printed|assembled|built and)|"
                    r"was (printed|assembled|tested)|works on the (robot|bench)|validated", re.I)


@pytest.fixture(scope="module")
def data():
    return recipe.bundle(ROOT)


@pytest.fixture(scope="module")
def recipes(data):
    return [recipe.evaluate(data, sel) for sel in recipe.combinations(data["compat"])]


def words(rec) -> str:
    kept = {key: value for key, value in rec.items() if key not in ("selection", "query", "nearest", "build", "validated")}
    return json.dumps(kept).replace('"validated": ""', "")


@pytest.mark.parametrize("name", PAGES)
def test_pages_carry_no_validation_caveats_and_no_claims(name):
    html = " ".join((SITE / name).read_text(encoding="utf-8").split())
    low = html.lower()
    for phrase in CAVEATS:
        assert phrase not in low, f"{name}: {phrase}"
    if name != "admin.html":                      # the admin page is where a check is recorded
        assert not CLAIMS.search(re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)), name
    assert 'class="status"' not in html, f"{name}: no status box"
    assert html.count("docs/status.md") == 1 and "Status and assumptions" in html, f"{name}: one link to the detail"


def test_recipes_carry_no_validation_caveats_and_no_claims(recipes):
    seen = set()
    for rec in recipes:
        text = words(rec)
        if text in seen:
            continue
        seen.add(text)
        low = text.lower()
        for phrase in CAVEATS + ("assumed", "published"):
            assert phrase not in low, f"{rec['query']}: {phrase}"
        assert not CLAIMS.search(text), rec["query"]
        assert "not_built" not in rec


def test_no_mark_without_a_record_and_a_mark_with_one(data, recipes):
    assert json.loads((ROOT / "config" / "validated.json").read_text(encoding="utf-8")) == {"records": []}
    assert all(rec["validated"] is None and all(item["validated"] == "" for item in rec["print"]["files"]) for rec in recipes)
    marked = dict(data, validated=[{"id": "unoq-biped-braccio_shield", "part": "", "date": "2026-12-01", "checked": "stands",
                                    "photo": "", "mark": True}])
    assert recipe.evaluate(marked, {})["validated"]["date"] == "2026-12-01"
    script = (SITE / "build.js").read_text(encoding="utf-8")
    # The words appear in the page only behind the record.
    assert script.count("Printed and checked on") == 2
    assert "if (recipe.validated) {" in script and "if (item.validated)" in script
    export = (SITE / "export.js").read_text(encoding="utf-8")
    assert "if (recipe.validated) {" in export and "item.validated ? `Printed and checked on" in export


def test_safety_instructions_and_working_instructions_stay(recipes):
    by_query = {rec["query"]: rec for rec in recipes}
    biped = by_query["controller=unoq&locomotion=biped&drive=braccio_shield&camera=esp32cam&head=fixed&lego=on"]
    power = " ".join(biped["power"])
    assert "Disconnect servo power before the first flash" in power
    assert "size the supply and wiring for the stall figure, or fuse it" in power
    assert "Do not run servos or motors from the board's 5 V pin" in power
    assert any("a software stop does not cut power" in part["note"] for part in biped["parts"])
    assert any("calibrate before motion" in text for text in biped["wiring"])
    assert any("Support the robot and calibrate one joint at a time before any motion" in text for text in biped["firmware"])
    assert biped["assembly"][0].startswith("Print the fit pieces first")
    assert biped["print"]["files"][0]["fit"]
    # "measure" where a part will not fit otherwise, and "Not written" for software that does not exist.
    assert any("measure" in part["note"].lower() for part in biped["parts"])
    pan = by_query["controller=unoq&locomotion=biped&drive=braccio_shield&camera=esp32cam&head=m5_360&lego=on"]
    assert any("Measure the bracket's hole pattern" in part["note"] for part in pan["parts"])
    assert any("Measure the adapter's hole pattern" in text for text in pan["wiring"])
    assert any(text.startswith("Head: not written") for text in pan["firmware"])
    pixy = by_query["controller=unoq&locomotion=biped&drive=braccio_shield&camera=pixy2&head=pixy_pantilt&lego=on"]
    assert any("measure your base" in text for text in pixy["wiring"])
    xiao = by_query["controller=unoq&locomotion=biped&drive=braccio_shield&camera=xiao_eyes&head=fixed&lego=on"]
    assert any("measure the space behind the display" in part["note"] for part in xiao["parts"])
    pi = by_query["controller=pi_full&locomotion=wheeled&drive=tt_hbridge&camera=none&head=fixed&lego=on&wheels=back&support=roller&wheel=printed_ring"]
    assert pi["firmware"] == ["Not written."]

    control = " ".join((SITE / "control.html").read_text(encoding="utf-8").split())
    for phrase in ("Enable (dead-man)", "Stop does not cut servo power. Keep a hand on the supply switch.",
                   "A hand is on the servo supply switch. A software stop does not cut power.", "sends the stop sequence"):
        assert phrase in control, phrase
    assert "jump" in control.lower() and "gear" in (control + (SITE / "control.js").read_text(encoding="utf-8")).lower()
    flash = " ".join((SITE / "flash.html").read_text(encoding="utf-8").split())
    assert "Disconnect servo power before the first flash" in flash and "sends nothing anywhere" in flash
    biped_page = " ".join((SITE / "biped.html").read_text(encoding="utf-8").split())
    assert "Print the three fit pieces" in biped_page and "Calibrate one joint at a time, robot held off the bench" in biped_page
    assert "a hand on the switch" in biped_page


def test_the_detail_moved_to_one_document():
    status = (ROOT / "docs" / "status.md").read_text(encoding="utf-8")
    assert "never been" in " ".join(status.split()) and "## Unverified" in status
    assert "Physical fit of anything: no part has been printed against a servo" in " ".join(status.split())
    assert "config/validated.json" in status
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count("(docs/status.md)") == 1
    assert "## Unverified" not in readme and "verified in simulation only" not in readme
