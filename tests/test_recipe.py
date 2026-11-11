# SPDX-License-Identifier: MIT
"""The Build yours recipe function: the data is well formed, every
combination gives a complete and consistent recipe, only physical
impossibilities are refused and each says why and offers a possible
neighbour, and site/build.js agrees with the Python function on all of them
(run under Node when it is installed)."""
import copy
import json
import shutil
import subprocess

import pytest

from conftest import ROOT
from microduck import recipe

STATUSES = {"analysed", "assembly_only", "being_analysed", "defined", "needs_part", "not_possible"}
REFUSED = {"needs_part", "not_possible"}
BASIS = {"published", "assumed", "not verified"}
BASES = {"unoq_braccio", "pi_servo", "pi_full_servo", "hub51515", "ev3", "m5_basex_ev3", "pi_buildhat_51515"}
TEXT_SECTIONS = ("wiring", "power", "firmware", "analysis", "assembly")
# The only reasons a selection may be refused for. Each is a physical or electrical fact.
REFUSAL_CODES = {
    "no-servo-outputs", "biped-on-lego-motors", "continuous-drive-not-a-joint", "servo-cannot-spin", "buildhat-needs-pi",
    "connector", "crank-needs-lego-motors", "picam-needs-pi", "pixy-on-hub", "pantilt-needs-pixy", "lego-motor-needs-port",
    "crank-needs-coupling", "biped-needs-deck"}
NEEDS_PART = {"crank-needs-coupling", "biped-needs-deck"}

DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { evaluate, optionState } from "./build.mjs";
const data = JSON.parse(readFileSync(process.argv[2], "utf8"));
const selections = JSON.parse(readFileSync(process.argv[3], "utf8"));
const probes = JSON.parse(readFileSync(process.argv[5], "utf8"));
writeFileSync(process.argv[4], JSON.stringify({
  recipes: selections.map((sel) => evaluate(data, sel)),
  states: probes.map(([sel, dim, option]) => optionState(data, sel, dim, option)),
}));
"""


@pytest.fixture(scope="module")
def data():
    return recipe.bundle(ROOT)


@pytest.fixture(scope="module")
def compat(data):
    return data["compat"]


@pytest.fixture(scope="module")
def selections(compat):
    return list(recipe.combinations(compat))


@pytest.fixture(scope="module")
def recipes(data, selections):
    return [recipe.evaluate(data, sel) for sel in selections]


def options(compat):
    return {dim["id"]: [option["id"] for option in dim["options"]] for dim in compat["dimensions"]}


def rich_bundle(data):
    """The real data plus walker paths in the manifest, a variants summary, a
    program index and validation records, so the comparison with the
    JavaScript covers them."""
    rich = copy.deepcopy(data)
    extra = ["lego/ev3-pixy2/chassis.stl", "lego/ev3-pixy2/fit_coupon.stl", "wheeled/wheel_hub_cross.stl"]
    rich["manifest"]["paths"] = sorted(set(rich["manifest"]["paths"] + extra))
    rich["manifest"]["info"]["lego/ev3-pixy2/chassis.stl"] = {"thumb": "./stl/thumbs/lego/ev3-pixy2/chassis.png", "size": "130 x 116 x 60 mm", "note": "print flat"}
    rich["variants"] = rich["variants"] + [
        {"match": {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"}, "status": "analysed",
         "status_text": "analysed", "lines": ["Mass 900 g by the model.", "Stability: stands on both feet."],
         "files": [], "parts": []},
        {"match": {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_tpu"},
         "status": "defined", "status_text": "defined", "lines": ["Mass 310 g by the model."],
         "files": [{"file": "wheeled/wheel_hub_cross.stl", "qty": 2, "role": "wheel hub", "fit": False}],
         "parts": [{"name": "O-ring 50 x 3 mm", "qty": 2, "note": "from the variants summary"}]},
    ]
    rich["programs"] = rich["programs"] + [
        {"match": {"controller": "ev3", "locomotion": "crank"}, "files": ["programs/ev3/crank/walk.py"],
         "steps": ["Save the file to the brick."], "load_with": {"name": "Robot Creator", "url": data["compat"]["robot_creator"]}}]
    rich["validated"] = rich["validated"] + [
        {"id": "unoq-biped-braccio_shield", "part": "", "date": "2026-12-01", "checked": "stands", "photo": "docs/validated/a.jpg", "mark": True},
        {"id": "unoq-biped-braccio_shield", "part": "fit_SR431.stl", "date": "2026-11-30", "checked": "", "photo": "", "mark": True},
        {"id": "unoq-biped-braccio_shield", "part": "fit_SR311.stl", "date": "2026-11-30", "checked": "too tight", "photo": "", "mark": False},
    ]
    return rich


# --- the data ---------------------------------------------------------------

def test_the_bases_have_sources_and_a_basis_on_every_figure():
    bases = json.loads((ROOT / "config" / "bases.json").read_text(encoding="utf-8"))
    assert set(bases["bases"]) == BASES
    for name, base in bases["bases"].items():
        for key in ("name", "status", "status_reason", "controller", "outline_mm", "mass_g", "mounting", "actuates",
                    "channels", "power", "cameras", "robot_creator", "software", "sources"):
            assert key in base, f"{name}: {key}"
        assert base["sources"] and all(url.startswith("https://") for url in base["sources"])
        for key in ("outline_mm", "mass_g", "mounting", "actuates", "channels", "power"):
            figure = base[key]
            assert figure["basis"] in BASIS, f"{name}.{key}"
            if figure["basis"] == "published":
                assert figure["source"].startswith("https://"), f"{name}.{key}"
            if figure["basis"] == "assumed":
                assert figure.get("note"), f"{name}.{key}"
            if figure["value"] is None:
                assert figure["basis"] == "not verified", f"{name}.{key}"
        assert {"family", "code_targets"} <= set(base["robot_creator"])
    assert bases["bases"]["ev3"]["robot_creator"]["code_targets"] == ["pybricks-ev3", "ev3dev-python"]
    assert bases["bases"]["m5_basex_ev3"]["robot_creator"]["code_targets"] == []


def test_compat_refers_only_to_known_options_and_bases(compat, data):
    known = options(compat)
    assert set(compat["defaults"]) == set(known)

    def check(when):
        for key, allowed in when.items():
            assert key in known, key
            assert allowed and set(allowed) <= set(known[key]), (key, allowed)

    rows = set()
    for row in compat["support"]:
        for key in ("controller", "locomotion", "drive"):
            assert row[key] in known[key], row
        assert row["base"] in data["bases"]["bases"], row
        assert row["status"] in ("report", "defined", "summary") and row["reason"]
        key = (row["controller"], row["locomotion"], row["drive"])
        assert key not in rows, key
        rows.add(key)
    assert {row["controller"] for row in compat["support"]} == set(known["controller"])
    # Every controller has a two-wheeled build.
    assert {row["controller"] for row in compat["support"] if row["locomotion"] == "wheeled"} == set(known["controller"])
    reported = [row for row in compat["support"] if row["status"] == "report"]
    assert [(row["controller"], row["locomotion"], row["drive"]) for row in reported] == [
        ("unoq", "biped", "braccio_shield"), ("pi", "biped", "servo_driver"), ("pi_full", "biped", "servo_driver")]
    for key, names in compat["manifest_map"].items():
        assert set(names) <= set(known[key]), key
    assert set(compat["report_controller"]) <= set(known["controller"])
    for item in compat["why_not"]:
        check(item["when"])
        assert item["reason"] and item["short"] and len(item["short"]) < 70
        assert item["code"] in REFUSAL_CODES and bool(item.get("needs")) == (item["code"] in NEEDS_PART)
    ids = [rule["id"] for rule in compat["rules"]]
    assert len(ids) == len(set(ids))
    rails = {}
    for rule in compat["rules"]:
        check(rule["when"])
        assert set(rule) <= {"id", "when", "set", "add", "without_program", "rails", "loads", "block", "alternatives", "code",
                             "short", "downgrade", "reason"}, rule["id"]
        if "block" in rule:
            assert rule["block"] and rule["alternatives"] and rule["code"] in REFUSAL_CODES, rule["id"]
            assert rule["short"] and len(rule["short"]) < 70, rule["id"]
            assert "add" not in rule and "loads" not in rule, rule["id"]
            for alternative in rule["alternatives"]:
                for key, value in alternative.items():
                    assert value in known[key], rule["id"]
                # Each alternative must leave this rule, or the search could not end.
                assert any(value not in rule["when"].get(key, [value + "?"]) for key, value in alternative.items()), rule["id"]
        for field in ("add", "without_program"):
            for name in rule.get(field, {}):
                assert name in compat["sections"], rule["id"]
        for key, rail in rule.get("rails", {}).items():
            assert rails.setdefault(key, rail) == rail, f"rail {key} defined twice differently"
            assert rail["limit_ma"] is None or rail["limit_ma"] % 10 == 0
        for load in rule.get("loads", []):
            assert load["rail"] in rule["rails"], rule["id"]
            assert load["qty"] > 0 and (load["stall_ma"] is None or (load["stall_ma"] > 0 and load["stall_ma"] % 10 == 0))
    for dim, aliases in compat["summary_aliases"].items():
        assert set(aliases) <= set(known[dim])


def test_status_tags_are_short_and_neutral(compat):
    labels = {key: value["label"] for key, value in compat["statuses"].items()}
    assert labels == {"analysed": "Simulated", "assembly_only": "Assembly checked", "being_analysed": "In analysis",
                      "defined": "Designed", "needs_part": "Needs a part", "not_possible": "Not possible"}
    assert "not_built" not in compat
    line = compat["trademarks"]
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in line
    assert "does not sponsor" in line and "Raspberry Pi is a trademark of Raspberry Pi Ltd" in line


# --- every combination ------------------------------------------------------

def test_the_combinations_are_all_of_them(compat, selections):
    known = options(compat)
    wheeled_only = [dim["id"] for dim in compat["dimensions"] if "only_for" in dim]
    plain = 1
    extra = 1
    for dim, ids in known.items():
        if dim in wheeled_only:
            extra *= len(ids)
        elif dim != "locomotion":
            plain *= len(ids)
    assert len(selections) == plain * (len(known["locomotion"]) - 1) + plain * extra
    assert len({json.dumps(sel, sort_keys=True) for sel in selections}) == len(selections)


def test_every_recipe_has_its_status_first(compat, recipes):
    for rec in recipes:
        assert rec["status"] in STATUSES
        assert rec["status_label"] == compat["statuses"][rec["status"]]["label"]
        assert rec["headline"] and rec["reasons"] and all(rec["reasons"])
        assert rec["trademarks"] == compat["trademarks"]
        assert rec["build"] == recipe.build_id(rec["selection"])
        assert "{" not in json.dumps([rec["reasons"]] + [rec[name] for name in TEXT_SECTIONS]), rec["query"]
        assert rec["validated"] is None, "no mark without a record"


def test_no_possible_recipe_is_empty(recipes):
    for rec in recipes:
        if rec["status"] in REFUSED:
            continue
        where = rec["query"]
        assert rec["base"] in BASES and rec["mechanism"] and rec["sources"], where
        assert rec["print"]["note"] and rec["parts"], where
        for part in rec["parts"]:
            assert part["name"] and part["note"], where
            assert part["qty"] is None or part["qty"] > 0, where
        for name in TEXT_SECTIONS:
            assert rec[name] and all(isinstance(text, str) and text for text in rec[name]), (where, name)
        files = rec["print"]["files"]
        if rec["selection"]["locomotion"] != "wheeled":
            assert files, where
        assert [item["fit"] for item in files] == sorted((item["fit"] for item in files), reverse=True), where
        assert len({item["file"] for item in files}) == len(files), where
        assert rec["nearest"] is None and rec["refusal"] == [], where


def test_no_recipe_contradicts_itself(compat, recipes):
    baseline = recipe.normalise(compat, compat["defaults"])
    servo_drives = {"braccio_shield", "servo_driver"}
    for rec in recipes:
        sel = rec["selection"]
        where = rec["query"]
        if rec["status"] == "analysed":
            assert sel == baseline, where
            assert any("Stands" in text for text in rec["analysis"]), where
        elif rec["status"] == "assembly_only":
            assert sel["locomotion"] == "biped" and sel["lego"] == baseline["lego"], where
            assert not any("Stands for" in text for text in rec["analysis"]), where
        if rec["status"] in REFUSED:
            assert not rec["print"]["files"] and not rec["parts"], where
            assert all(rec[name] == [] for name in TEXT_SECTIONS), where
            continue
        names = " | ".join(part["name"] for part in rec["parts"])
        servos = sum(part["qty"] for part in rec["parts"] if part["name"].startswith(("SR431", "SR311")))
        if sel["locomotion"] == "biped":
            assert sel["drive"] in servo_drives and servos == 6, where
        else:
            assert sel["drive"] not in servo_drives and servos == 0, where
        if sel["drive"] == "tt_hbridge":
            assert "H-bridge driver board" in names, where
            assert any("open loop" in text for text in rec["wiring"]), where
        if sel["locomotion"] == "wheeled" and sel["wheel"] == "printed_tpu":
            assert "TPU filament" in names, where
        if sel["locomotion"] == "wheeled" and sel["wheel"] == "printed_ring":
            assert any("slips on smooth floors" in part["note"] for part in rec["parts"]), where
        if sel["camera"] == "none":
            assert "Pixy2 camera" not in names and "ESP32-CAM" not in names and "XIAO" not in names, where
        firmware = " ".join(rec["firmware"])
        if sel["controller"] == "unoq" and sel["locomotion"] == "biped":
            assert "app_lab/microduck_agent" in firmware, where
        elif sel["controller"] in ("ev3", "hub51515"):
            assert "Robot Creator" in firmware and compat["robot_creator"] in firmware, where
        else:
            assert "Not written" in firmware or "python3-build-hat" in firmware, where


def test_only_physical_impossibilities_are_refused(data, compat, recipes):
    by_code = {}
    for rec in recipes:
        if rec["status"] not in REFUSED:
            continue
        where = rec["query"]
        assert rec["refusal"] and set(rec["refusal"]) <= REFUSAL_CODES, where
        assert (rec["status"] == "needs_part") == (set(rec["refusal"]) <= NEEDS_PART), where
        if rec["status"] == "needs_part":
            assert any(text.startswith("Needs a part: ") for text in rec["reasons"]), where
        assert all(len(text) > 20 for text in rec["reasons"]), where
        near = rec["nearest"]
        assert near["status"] in STATUSES - REFUSED and near["changes"], where
        # The neighbour keeps the controller the reader said they have.
        assert near["selection"]["controller"] == rec["selection"]["controller"], where
        for code in rec["refusal"]:
            by_code[code] = by_code.get(code, 0) + 1
    assert set(by_code) == REFUSAL_CODES
    # With a controller, locomotion and drive that go together, the only refusals left are the Pixy
    # on the 51515 hub, the Pi camera off a Pi, and a head that has nothing to carry or drive it.
    for rec in recipes:
        sel = rec["selection"]
        if rec["status"] in REFUSED and recipe._find_row(compat, sel) is not None:
            assert set(rec["refusal"]) <= {"pixy-on-hub", "picam-needs-pi", "pantilt-needs-pixy", "no-servo-outputs",
                                           "lego-motor-needs-port"}, rec["query"]
            assert sel["camera"] in ("pixy2", "picam2") or sel["head"] != "fixed", rec["query"]
    for rec in recipes[::97]:
        if rec["status"] in REFUSED:
            again = recipe.evaluate(data, rec["nearest"]["selection"])
            assert again["status"] == rec["nearest"]["status"] and again["query"] == rec["nearest"]["query"]


def test_the_owners_designs_and_a_wheeled_build_for_every_controller_resolve(data, compat):
    def run(**selection):
        return recipe.evaluate(data, selection)

    designs = {
        "ev3-pixy2": dict(controller="ev3", locomotion="crank", drive="ev3_motors", camera="pixy2"),
        "pi-zero-2w-51515": dict(controller="pi", locomotion="crank", drive="buildhat_51515", camera="picam2"),
        "servo biped": dict(controller="unoq", locomotion="biped", drive="braccio_shield"),
    }
    for name, selection in designs.items():
        rec = run(**selection)
        assert rec["status"] not in REFUSED, name
        assert rec["print"]["files"] and rec["parts"] and all(rec[key] for key in TEXT_SECTIONS), name
    walker = run(**designs["ev3-pixy2"])
    assert walker["preset"] == "ev3-pixy2" and walker["print"]["files"][0]["file"] == "ev3-pixy2/fit_coupon.stl"
    assert any("LEGO I2C" in text for text in walker["wiring"])
    assert "Pixy2 LEGO cable" in [part["name"] for part in walker["parts"]]
    assert "pi-zero-2w-51515/camera_head.stl" in [item["file"] for item in run(**designs["pi-zero-2w-51515"])["print"]["files"]]
    for controller in options(compat)["controller"]:
        rows = [row for row in compat["support"] if row["controller"] == controller and row["locomotion"] == "wheeled"]
        for row in rows:
            for wheel in options(compat)["wheel"]:
                rec = run(controller=controller, locomotion="wheeled", drive=row["drive"], camera="none", wheel=wheel)
                assert rec["status"] not in REFUSED, (controller, row["drive"], wheel)
    adapter = run(controller="unoq", locomotion="wheeled", drive="tt_hbridge", camera="none", wheel="lego")
    assert any("needs this part" in part["note"] for part in adapter["parts"])
    # Cameras with their own power go on every controller; the Pixy on all but the 51515 hub.
    for controller in options(compat)["controller"]:
        row = [r for r in compat["support"] if r["controller"] == controller][0]
        for camera in ("xiao_eyes", "esp32cam", "esp_eye", "esp32_s3_eye", "pixy2"):
            rec = run(controller=controller, locomotion=row["locomotion"], drive=row["drive"], camera=camera)
            assert (rec["status"] in REFUSED) == (camera == "pixy2" and controller == "hub51515"), (controller, camera)
    assert run(controller="hub51515", locomotion="crank", drive="hub_motors", camera="pixy2")["refusal"] == ["pixy-on-hub"]
    assert run(camera="pixy2", head="pixy_pantilt")["status"] == "defined"
    assert "head_pixy_plate_pixy2.stl" in [item["file"] for item in run(camera="pixy2")["print"]["files"]]
    assert run(controller="ev3", locomotion="crank", drive="ev3_motors", camera="none", lego="off")["status"] not in REFUSED


def test_named_cases(data):
    def run(**selection):
        return recipe.evaluate(data, selection)

    default = data["compat"]["defaults"]["camera"]
    assert run()["status"] == "analysed" and run()["selection"]["camera"] == default
    covered = {(e["match"]["controller"], e["match"]["camera"], e["match"]["head"]): e for e in data["coverage"]["entries"]}
    assert run()["analysis"] == covered[("unoq", default, "fixed")]["lines"]
    for camera in ("esp32cam", "esp_eye", "esp32_s3_eye"):
        rec = run(camera=camera)
        assert rec["status"] == covered[("unoq", camera, "fixed")]["status"]
        cam_files = [item["file"] for item in rec["print"]["files"] if "cam" in item["file"]]
        assert cam_files == [f"fit_cam_{camera}.stl", f"01_torso_unoq_cam_{camera}.stl"]

    for controller, torso in (("pi", "01_torso_pi_zero_2w_cam_esp32cam.stl"), ("pi_full", "01_torso_pi_cam_esp32cam.stl")):
        rec = run(controller=controller, drive="servo_driver", camera="esp32cam")
        assert rec["status"] == "assembly_only"
        assert [item["file"] for item in rec["print"]["files"] if "torso" in item["file"]] == [torso]
        other = run(controller=controller, drive="servo_driver", camera="esp_eye")
        assert other["status"] == "defined" and any("No torso file is in stl/" in text for text in other["reasons"])
        assert not [item for item in other["print"]["files"] if "torso" in item["file"]]

    for head in ("sg90_pan", "m5_360"):
        rec = run(head=head, camera="esp32cam")
        assert rec["status"] == "assembly_only"
        names = [item["file"] for item in rec["print"]["files"]]
        assert [name for name in names if "torso" in name or "head" in name] == [
            "01_torso_unoq_pan_head.stl", "head_pan_platform.stl", "head_tilt_cradle_esp32cam.stl"]
        assert names[:3] == ["fit_horn_drill_blank.stl", "fit_lego_compatible_coupon.stl", "fit_sg90_cradle.stl"]
        assert any("Tilt is set by hand" in text for text in rec["wiring"] + rec["analysis"])
        assert any("not written" in text.lower() for text in rec["firmware"])
        assert run(head=head, camera="esp_eye")["status"] == "defined"
    assert any("turns continuously" in text for text in run(head="m5_360")["wiring"])

    for controller, drive in (("ev3", "ev3_motors"), ("hub51515", "hub_motors")):
        carried = run(controller=controller, drive=drive, camera="none")
        assert carried["status"] == "not_possible" and carried["refusal"] == ["biped-on-lego-motors"] * 2
        assert data["coverage"]["carried"][controller] in carried["reasons"]
        assert carried["nearest"]["selection"]["locomotion"] == "crank"
        walker = run(controller=controller, locomotion="crank", drive=drive, camera="none")
        assert walker["status"] == "being_analysed" and not any("carrying it" in text for text in walker["reasons"])
    servo_on_ev3 = run(controller="ev3", drive="braccio_shield")
    assert "no-servo-outputs" in servo_on_ev3["refusal"]
    assert any("cannot drive hobby servos" in text for text in servo_on_ev3["reasons"])
    assert run(controller="m5core", drive="servo_driver")["status"] == "needs_part"

    empty = run(camera="none")
    assert empty["status"] == "defined"
    assert [item["file"] for item in empty["print"]["files"] if "cam" in item["file"]] == [f"01_torso_unoq_cam_{default}.stl"]
    assert run(lego="off")["status"] == "defined"
    assert run(camera="xiao_eyes")["status"] == "defined"
    assert any("XIAO" in part["name"] for part in run(camera="xiao_eyes")["parts"])

    wheels = run(controller="unoq", locomotion="wheeled", drive="tt_hbridge", wheels="front", support="skid", wheel="tt65")
    assert wheels["status"] == "being_analysed"
    assert "wheels=front" in wheels["query"] and "support=skid" in wheels["query"]
    assert any("at the front" in text for text in wheels["wiring"])

    kit = run()
    assert any("10.00 A" in text and "2.5 times" in text and "or fuse it" in text for text in kit["power"])
    assert any(text.startswith("Mass ") and "g by the model" in text for text in kit["analysis"])


def test_wheel_choices_do_not_change_other_locomotions(data):
    plain = recipe.evaluate(data, {})
    varied = recipe.evaluate(data, {"wheels": "front", "support": "skid", "wheel": "tt65"})
    assert plain == varied and "wheel" not in plain["query"]


def test_unknown_values_fall_back_to_the_defaults(data, compat):
    rec = recipe.evaluate(data, {"controller": "toaster", "nonsense": "1"})
    assert rec["selection"] == recipe.normalise(compat, compat["defaults"])


def test_evaluate_is_pure(data):
    before = json.dumps(data, sort_keys=True)
    one = recipe.evaluate(data, {"controller": "pi", "locomotion": "wheeled", "drive": "m5_360_wheels", "head": "m5_360"})
    two = recipe.evaluate(data, {"controller": "pi", "locomotion": "wheeled", "drive": "m5_360_wheels", "head": "m5_360"})
    assert one == two and json.dumps(data, sort_keys=True) == before


# --- choosing in the form ----------------------------------------------------

def test_choosing_a_lego_controller_leads_with_what_it_can_do(data, compat):
    for controller in ("ev3", "hub51515"):
        state = recipe.option_state(data, {}, "controller", controller)
        assert state["enabled"] and state["selection"]["locomotion"] == "crank", "the crank walker is the default"
        assert recipe.evaluate(data, state["selection"])["status"] not in REFUSED
        here = state["selection"]
        biped = recipe.option_state(data, here, "locomotion", "biped")
        assert biped == {"enabled": False, "selection": None, "short": "Six joints need six position servos; see the crank walker"}
        wheeled = recipe.option_state(data, here, "locomotion", "wheeled")
        assert wheeled["enabled"] and wheeled["selection"]["drive"] == here["drive"]
        assert not recipe.option_state(data, here, "drive", "braccio_shield")["enabled"]
        assert not recipe.option_state(data, here, "camera", "picam2")["enabled"]
        assert recipe.option_state(data, here, "camera", "xiao_eyes")["enabled"]
    assert not recipe.option_state(data, {"controller": "hub51515", "locomotion": "crank", "drive": "hub_motors", "camera": "none"},
                                   "camera", "pixy2")["enabled"]


def test_a_possible_option_brings_the_other_fields_along(data, compat):
    known = options(compat)
    # Choosing the pan-tilt head switches the camera to the Pixy that carries it.
    state = recipe.option_state(data, {}, "head", "pixy_pantilt")
    assert state["enabled"] and state["selection"]["camera"] == "pixy2" and state["selection"]["head"] == "pixy_pantilt"
    state = recipe.option_state(data, {}, "locomotion", "wheeled")
    assert state["enabled"] and state["selection"]["drive"] in ("m5_360_wheels", "tt_hbridge")
    for controller in known["controller"]:
        start = recipe.option_state(data, {}, "controller", controller)["selection"]
        assert start is not None, controller
        for dim in compat["dimensions"]:
            for option in known[dim["id"]]:
                state = recipe.option_state(data, start, dim["id"], option)
                if state["enabled"]:
                    chosen = state["selection"]
                    if "only_for" not in dim or recipe._matches(dim["only_for"], chosen):
                        assert chosen[dim["id"]] == option
                    if dim["id"] != "controller":
                        assert chosen["controller"] == controller
                    assert recipe.evaluate(data, chosen)["status"] not in REFUSED
                else:
                    assert state["short"] and len(state["short"]) < 70


# --- manifest, reports, summary, programs, validation -----------------------

def test_files_link_only_when_the_manifest_names_them(data):
    rich = rich_bundle(data)
    rec = recipe.evaluate(data, {})
    assert rec["print"]["files"] and all(item["link"] == "./stl/" + item["file"] for item in rec["print"]["files"])
    base = {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"}
    assert all(item["link"] is None and item["thumb"] is None for item in recipe.evaluate(data, base)["print"]["files"])
    walker = recipe.evaluate(rich, base)
    by_name = {item["file"]: item for item in walker["print"]["files"]}
    assert by_name["ev3-pixy2/chassis.stl"]["link"] == data["compat"]["repo_blob"] + "stl/lego/ev3-pixy2/chassis.stl"
    assert by_name["ev3-pixy2/chassis.stl"]["size"] == "130 x 116 x 60 mm" and by_name["ev3-pixy2/chassis.stl"]["note"] == "print flat"
    assert by_name["ev3-pixy2/left_leg.stl"]["link"] is None
    bare = copy.deepcopy(data)
    bare["manifest"] = {"present": False, "paths": [], "served": [], "files": [], "info": {}, "camera_default": "none",
                        "controller_default": "unoq"}
    assert recipe.evaluate(bare, {})["print"]["files"] == []


def test_the_real_manifest_is_read_as_it_is(data):
    listed = json.loads((ROOT / "stl" / "manifest.json").read_text(encoding="utf-8"))
    names = [entry["file"] for entry in listed["files"]]
    assert data["manifest"]["present"] and data["manifest"]["served"] == names
    by_name = {entry["file"]: entry for entry in data["manifest"]["files"]}
    home = json.loads((ROOT / "stl" / "parameters.json").read_text(encoding="utf-8"))["controller_default"]
    assert data["manifest"]["controller_default"] == home
    for entry in listed["files"]:
        options_ = entry["options"]
        mine = by_name[entry["file"]]
        assert mine["camera"] == options_.get("camera") and mine["head"] == options_.get("head")
        assert mine["part"] == options_.get("part") and mine["fit"] == bool(options_.get("fit_piece"))
        assert mine["controller"] == options_.get("controller", home if options_.get("part") == "torso" else None)
        assert mine["what"] == entry["what"]
    general = [e["file"] for e in listed["files"] if not {"controller", "head", "camera"} & set(e["options"]) and e["options"].get("part") != "torso"]
    assert len([name for name in general if not name.startswith("fit_")]) == 6           # the six leg parts
    torso_cameras = sorted(e["options"]["camera"] for e in listed["files"]
                           if e["options"].get("part") == "torso" and e["options"].get("controller") == home)
    for camera in torso_cameras:
        files = recipe.evaluate(data, {"camera": camera})["print"]["files"]
        # The legs, the general fit pieces, this camera's torso and this camera's fit piece: nothing
        # of another controller, of the turning head or of a Pixy plate.
        assert sorted(item["file"] for item in files) == sorted(
            general + [f"01_torso_{home}_cam_{camera}.stl", f"fit_cam_{camera}.stl"])
        assert len([item for item in files if not item["fit"]]) == 7
        for item in files:
            assert (ROOT / "stl" / item["file"]).is_file()


def test_the_default_camera_is_one_switch_in_config(tmp_path, data):
    preset = json.loads((ROOT / "config" / "assembly.json").read_text(encoding="utf-8"))["camera"]["preset"]
    assert data["compat"]["defaults"]["camera"] == preset == data["manifest"]["camera_default"]
    assert json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))["defaults"]["camera"] == ""
    for folder in ("config", "reports", "stl"):
        shutil.copytree(ROOT / folder, tmp_path / folder, ignore=shutil.ignore_patterns("*.stl", "*.png"))
    other = "esp_eye" if preset != "esp_eye" else "esp32cam"
    config = json.loads((tmp_path / "config" / "assembly.json").read_text(encoding="utf-8"))
    config["camera"]["preset"] = other
    (tmp_path / "config" / "assembly.json").write_text(json.dumps(config), encoding="utf-8")
    switched = recipe.bundle(tmp_path)
    rec = recipe.evaluate(switched, {})
    assert rec["selection"]["camera"] == other
    # The tag still follows the reports, which were not regenerated in this copy.
    assert rec["status"] == "assembly_only"
    empty = recipe.evaluate(switched, {"camera": "none"})
    assert f"01_torso_unoq_cam_{other}.stl" in [item["file"] for item in empty["print"]["files"]]


def test_simulated_means_what_the_reports_cover(data, recipes):
    report = json.loads((ROOT / "reports" / "assembly.json").read_text(encoding="utf-8"))
    simulated = report["variants"][report["selected"]]["camera"]["preset"]
    entries = data["coverage"]["entries"]
    key = lambda entry: (entry["match"]["controller"], entry["match"]["camera"], entry["match"]["head"])
    assert [key(entry) for entry in entries if entry["status"] == "analysed"] == [("unoq", simulated, "fixed")]
    checked = {key(entry) for entry in entries if entry["status"] == "assembly_only"}
    pan = report["turning_head"]["camera_preset"]
    assert checked == ({("unoq", preset, "fixed") for preset in report["camera_presets"]}
                       | {("pi", "esp32cam", "fixed"), ("pi_full", "esp32cam", "fixed")}
                       | {("unoq", pan, "sg90_pan"), ("unoq", pan, "m5_360")})
    assert set(data["coverage"]["carried"]) == {"hub51515", "ev3"}
    assert [rec["query"] for rec in recipes if rec["status"] == "analysed"] == [
        f"controller=unoq&locomotion=biped&drive=braccio_shield&camera={simulated}&head=fixed&lego=on"]
    got = {(rec["selection"]["controller"], rec["selection"]["camera"], rec["selection"]["head"])
           for rec in recipes if rec["status"] == "assembly_only"}
    assert got == checked
    assert len([rec for rec in recipes if rec["status"] == "assembly_only"]) == len(checked)


def test_status_numbers_programs_and_marks_come_from_their_files(data):
    rich = rich_bundle(data)
    base = {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"}
    plain = recipe.evaluate(data, base)
    assert plain["status"] == "being_analysed" and any("Not written for this build" in text for text in plain["firmware"])
    rec = recipe.evaluate(rich, base)
    assert rec["status"] == "analysed" and "Mass 900 g by the model." in rec["analysis"]
    assert rec["firmware"][:3] == [
        "Program for this build: " + data["compat"]["repo_blob"] + "programs/ev3/crank/walk.py",
        "Save the file to the brick.", "Load it with Robot Creator: " + data["compat"]["robot_creator"]]
    assert not any("Not written" in text for text in rec["firmware"])
    # An addition outside the summary takes the tag back to Designed.
    assert recipe.evaluate(rich, {**base, "head": "lego_motor"})["status"] == "defined"
    tpu = recipe.evaluate(rich, {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_tpu"})
    assert tpu["status"] == "defined" and tpu["parts"][-1]["name"] == "O-ring 50 x 3 mm"
    assert tpu["print"]["files"][0]["link"].endswith("/blob/main/stl/wheeled/wheel_hub_cross.stl")
    marked = recipe.evaluate(rich, {})
    assert marked["validated"] == {"date": "2026-12-01", "checked": "stands", "photo": "docs/validated/a.jpg"}
    marks = {item["file"]: item["validated"] for item in marked["print"]["files"]}
    assert marks["fit_SR431.stl"] == "2026-11-30"
    assert marks["fit_SR311.stl"] == "", "a part that did not fit is recorded without a mark"
    assert recipe.evaluate(rich, {"camera": "esp_eye"})["validated"] == marked["validated"], "the mark is per build"
    assert recipe.evaluate(rich, {"controller": "pi", "drive": "servo_driver"})["validated"] is None


def test_summary_program_and_validation_files_are_read_when_present(tmp_path, compat):
    for folder in ("config", "reports"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    (tmp_path / "config" / "validated.json").write_text('{"records": []}', encoding="utf-8")
    empty = recipe.bundle(tmp_path)
    assert empty["variants"] == [] and empty["programs"] == [] and empty["validated"] == []
    assert empty["manifest"] == {"present": False, "paths": [], "served": [], "files": [], "info": {},
                                 "camera_default": compat["defaults"]["camera"], "controller_default": "unoq"}
    (tmp_path / "reports" / "variants").mkdir()
    (tmp_path / "reports" / "variants" / "summary.json").write_text(json.dumps({"variants": [
        {"base": "ev3", "locomotion": "crank", "status": "analysed in simulation", "mass_g": 912.5,
         "stability_verdict": "stands on both feet", "files": ["lego/ev3-pixy2/chassis.stl"]},
        {"controller": "pi", "locomotion": "wheeled", "drive": "tt", "status": "simulated, tips on braking",
         "mass": {"total_g": 300}, "wheel": "printed_ring", "parts": [{"name": "O-ring 60 x 3 mm", "qty": 2}]},
        {"controller": "pi", "locomotion": "wheeled", "status": "analysed"},
        {"base": "somebody-else", "locomotion": "wheeled", "status": "analysed"},
    ]}), encoding="utf-8")
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "index.json").write_text(json.dumps({"programs": [
        {"controller": "ev3", "build": "crank", "files": ["ev3/crank/walk.py"], "load_with": "robot-creator",
         "steps": ["Open the file in Robot Creator."]},
        {"controller": "ev3", "build": "crank", "files": ["../../etc/passwd"]},
        {"controller": "nobody", "files": ["x.py"]}]}), encoding="utf-8")
    (tmp_path / "config" / "validated.json").write_text(json.dumps({"records": [
        {"id": "ev3-crank-ev3_motors", "date": "2026-12-02", "checked": "walks on carpet"},
        {"id": "ev3-crank-ev3_motors", "part": "lego/ev3-pixy2/chassis.stl", "date": "2026-12-02", "mark": False},
        {"date": "2026-12-02"}]}), encoding="utf-8")
    (tmp_path / "stl").mkdir()
    (tmp_path / "stl" / "manifest.json").write_text(json.dumps({"files": [
        {"file": "fit_SR431.stl", "what": "fit piece for an SR431 servo cradle", "options": {"fit_piece": True},
         "bounding_box_mm": [[0, 0, 0], [48, 36.5, 8.8]], "thumbnail": {"file": "thumbs/fit_SR431.png", "stl_sha256": "0", "bytes": 1}}],
        "thumbnails": {"lego/ev3-pixy2/chassis.stl": {"file": "thumbs/lego/ev3-pixy2/chassis.png", "stl_sha256": "0", "bytes": 1,
                                                       "bounding_box_mm": [[-65, -58, 0], [65, 58, 60]]}}}), encoding="utf-8")
    loaded = recipe.bundle(tmp_path)
    assert loaded["manifest"]["paths"] == ["fit_SR431.stl", "lego/ev3-pixy2/chassis.stl"]
    assert loaded["manifest"]["served"] == ["fit_SR431.stl"]
    assert loaded["manifest"]["files"] == [
        {"file": "fit_SR431.stl", "what": "fit piece for an SR431 servo cradle", "fit": True, "part": None,
         "controller": None, "head": None, "camera": None}]
    assert loaded["manifest"]["info"] == {
        "fit_SR431.stl": {"thumb": "./stl/thumbs/fit_SR431.png", "size": "48 x 36 x 9 mm", "note": ""},
        "lego/ev3-pixy2/chassis.stl": {"thumb": "./stl/thumbs/lego/ev3-pixy2/chassis.png", "size": "130 x 116 x 60 mm", "note": ""}}
    # The entry with no drive is ambiguous on the Pi and the unknown base matches nothing: both are dropped.
    assert [entry["match"] for entry in loaded["variants"]] == [
        {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors"},
        {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_ring"}]
    assert loaded["variants"][0]["status"] == "analysed"
    assert loaded["variants"][0]["lines"] == ["Mass 912.5 g by the model.", "Stability: stands on both feet"]
    # A status this page does not know is shown as written and never promoted.
    assert loaded["variants"][1]["status"] == "being_analysed"
    assert loaded["programs"] == [{"match": {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors"}, "files": ["programs/ev3/crank/walk.py"],
                                   "steps": ["Open the file in Robot Creator."],
                                   "load_with": {"name": "Robot Creator", "url": compat["robot_creator"]}}]
    assert loaded["validated"] == [
        {"id": "ev3-crank-ev3_motors", "part": "", "date": "2026-12-02", "checked": "walks on carpet", "photo": "", "mark": True},
        {"id": "ev3-crank-ev3_motors", "part": "lego/ev3-pixy2/chassis.stl", "date": "2026-12-02", "checked": "", "photo": "", "mark": False}]
    rec = recipe.evaluate(loaded, {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge"})
    assert rec["status"] == "being_analysed" and any("simulated, tips on braking" in text for text in rec["analysis"])
    assert rec["parts"][-1] == {"name": "O-ring 60 x 3 mm", "qty": 2, "note": "from the variants summary"}
    walker = recipe.evaluate(loaded, {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"})
    assert walker["status"] == "analysed" and walker["validated"]["date"] == "2026-12-02"


# --- the JavaScript evaluator -----------------------------------------------

@pytest.mark.parametrize("kind", ["as committed", "with walker files, a summary, programs and marks"])
def test_javascript_agrees_with_python_on_every_combination(kind, data, selections, recipes, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; site/build.js was not run")
    if kind == "as committed":
        expected = recipes
        used = data
    else:
        used = rich_bundle(data)
        expected = [recipe.evaluate(used, sel) for sel in selections]
    known = options(used["compat"])
    probes = []
    for controller in known["controller"]:
        start = recipe.option_state(used, {}, "controller", controller)["selection"]
        for dim, ids in known.items():
            probes.extend([start, dim, option] for option in ids)
    shutil.copyfile(ROOT / "site" / "build.js", tmp_path / "build.mjs")
    (tmp_path / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(used), encoding="utf-8")
    (tmp_path / "selections.json").write_text(json.dumps(selections), encoding="utf-8")
    (tmp_path / "probes.json").write_text(json.dumps(probes), encoding="utf-8")
    subprocess.run([node, "driver.mjs", "data.json", "selections.json", "out.json", "probes.json"], cwd=tmp_path, check=True,
                   capture_output=True, timeout=600)
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert len(got["recipes"]) == len(expected)
    for mine, theirs in zip(expected, got["recipes"]):
        assert mine == theirs, mine["query"]
    assert got["states"] == [recipe.option_state(used, sel, dim, option) for sel, dim, option in probes]
