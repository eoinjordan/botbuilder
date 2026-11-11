# SPDX-License-Identifier: MIT
"""The Build yours recipe function: the data is well formed, every
combination gives a complete and consistent recipe, impossible ones say why
and offer a possible neighbour, and site/build.js agrees with the Python
function on all of them (run under Node when it is installed)."""
import copy
import json
import shutil
import subprocess

import pytest

from conftest import ROOT
from microduck import recipe

STATUSES = {"analysed", "assembly_only", "being_analysed", "defined", "not_possible"}
BASIS = {"published", "assumed", "not verified"}
BASES = {"unoq_braccio", "pi_servo", "pi_full_servo", "hub51515", "ev3", "m5_basex_ev3", "pi_buildhat_51515"}
TEXT_SECTIONS = ("wiring", "power", "firmware", "analysis", "assembly")

DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import { evaluate } from "./build.mjs";
const data = JSON.parse(readFileSync(process.argv[2], "utf8"));
const selections = JSON.parse(readFileSync(process.argv[3], "utf8"));
writeFileSync(process.argv[4], JSON.stringify(selections.map((sel) => evaluate(data, sel))));
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
    """The real data plus an STL manifest and a variants summary, so the
    comparison with the JavaScript covers linked files and summary entries."""
    rich = copy.deepcopy(data)
    rich["manifest"]["paths"] = sorted(rich["manifest"]["paths"] + [
        "lego/ev3-pixy2/chassis.stl", "lego/ev3-pixy2/fit_coupon.stl", "wheeled/wheel_hub_cross.stl"])
    rich["variants"] = [
        {"match": {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors"}, "status": "analysed",
         "status_text": "analysed", "lines": ["Mass 900 g by the model.", "Stability: stands on both feet."],
         "files": [], "parts": []},
        {"match": {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge"}, "status": "being_analysed",
         "status_text": "in progress", "lines": [], "files": [], "parts": []},
        {"match": {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_tpu"},
         "status": "defined", "status_text": "defined", "lines": ["Mass 310 g by the model."],
         "files": [{"file": "wheeled/wheel_hub_cross.stl", "qty": 2, "role": "wheel hub", "fit": False}],
         "parts": [{"name": "O-ring 50 x 3 mm", "qty": 2, "note": "from the variants summary"}]},
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
        assert base["status"] in ("analysed in simulation", "assembly checked, not simulated", "being analysed",
                                  "defined, not designed", "not possible")
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
        assert "battery" in base["mass_g"].get("note", "").lower() or base["mass_g"]["basis"] == "not verified", name
        assert {"family", "code_targets"} <= set(base["robot_creator"])
    assert bases["bases"]["unoq_braccio"]["status"] == "analysed in simulation"
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
    assert {row["locomotion"] for row in compat["support"]} == set(known["locomotion"])
    reported = [row for row in compat["support"] if row["status"] == "report"]
    assert [(row["controller"], row["locomotion"], row["drive"]) for row in reported] == [
        ("unoq", "biped", "braccio_shield"), ("pi", "biped", "servo_driver"), ("pi_full", "biped", "servo_driver")]
    for key, names in compat["manifest_map"].items():
        assert set(names) <= set(known[key]), key
    assert set(compat["report_controller"]) <= set(known["controller"])
    for item in compat["why_not"]:
        check(item["when"])
        assert item["reason"]
    ids = [rule["id"] for rule in compat["rules"]]
    assert len(ids) == len(set(ids))
    rails = {}
    for rule in compat["rules"]:
        check(rule["when"])
        assert set(rule) <= {"id", "when", "set", "add", "rails", "loads", "block", "nearest", "downgrade", "reason"}, rule["id"]
        if "block" in rule:
            assert rule["block"] and rule["nearest"], rule["id"]
            assert "add" not in rule and "loads" not in rule, rule["id"]
            for key, value in rule["nearest"].items():
                assert value in known[key], rule["id"]
                # The suggested value must leave this rule, or the search could not end.
                assert value not in rule["when"].get(key, []), rule["id"]
        for name in rule.get("add", {}):
            assert name in compat["sections"], rule["id"]
        for key, rail in rule.get("rails", {}).items():
            assert rails.setdefault(key, rail) == rail, f"rail {key} defined twice differently"
            assert rail["limit_ma"] is None or rail["limit_ma"] % 10 == 0
        for load in rule.get("loads", []):
            assert load["rail"] in rule["rails"], rule["id"]
            assert load["qty"] > 0 and load["basis"]
            assert load["stall_ma"] is None or (load["stall_ma"] > 0 and load["stall_ma"] % 10 == 0)
    for dim, aliases in compat["summary_aliases"].items():
        assert set(aliases) <= set(known[dim])


def test_base_status_agrees_with_the_support_table(compat, data):
    wording = {"defined": "defined, not designed", "summary": "being analysed"}
    best = {"analysed": "analysed in simulation", "assembly_only": "assembly checked, not simulated"}
    for name, base in data["bases"]["bases"].items():
        rows = [row for row in compat["support"] if row["base"] == name]
        assert rows, name
        if rows[0]["status"] == "report":
            # The base says the best the reports hold for its controller.
            found = {entry["status"] for entry in data["coverage"]["entries"] if entry["match"]["controller"] == rows[0]["controller"]}
            assert base["status"] == best["analysed" if "analysed" in found else "assembly_only"], name
        else:
            assert base["status"] == wording[rows[0]["status"]], name


def test_trademark_and_not_built_lines(compat):
    line = compat["trademarks"]
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in line
    assert "does not sponsor" in line and "endorse" in line
    assert "Raspberry Pi is a trademark of Raspberry Pi Ltd" in line
    assert "physically built" in compat["not_built"]


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


def test_every_recipe_has_its_status_and_the_not_built_line_first(compat, recipes):
    for rec in recipes:
        assert rec["status"] in STATUSES
        assert rec["status_label"] == compat["statuses"][rec["status"]]["label"]
        assert rec["headline"] and rec["reasons"] and all(rec["reasons"])
        assert rec["not_built"] == compat["not_built"]
        assert rec["trademarks"] == compat["trademarks"]
        assert "{" not in json.dumps([rec["reasons"]] + [rec[name] for name in TEXT_SECTIONS]), rec["query"]


def test_no_possible_recipe_is_empty(recipes):
    for rec in recipes:
        if rec["status"] == "not_possible":
            continue
        where = rec["query"]
        assert rec["base"] in BASES and rec["mechanism"] and rec["sources"], where
        assert rec["print"]["note"], where
        assert rec["parts"], where
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
        if files:
            assert files[0]["fit"], where
        assert rec["nearest"] is None, where


def test_no_recipe_contradicts_itself(compat, recipes):
    baseline = recipe.normalise(compat, compat["defaults"])
    servo_drives = {"braccio_shield", "servo_driver"}
    for rec in recipes:
        sel = rec["selection"]
        where = rec["query"]
        unanalysed = [text for text in rec["analysis"] if text.startswith(("Not analysed", "Not simulated", "Being analysed"))]
        if rec["status"] == "analysed":
            assert sel == baseline, where
            assert not unanalysed, where
            assert any("Stands" in text for text in rec["analysis"]), where
        elif rec["status"] == "assembly_only":
            assert sel["locomotion"] == "biped" and sel["lego"] == baseline["lego"], where
            assert [text[:13] for text in unanalysed] == ["Not simulated"], where
            assert not any("Stands for" in text for text in rec["analysis"]), where
        elif rec["status"] != "not_possible":
            # Never a figure-only analysis under an unanalysed status.
            assert unanalysed, where
        if rec["status"] == "not_possible":
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
            assert "Pixy2 camera" not in names and "ESP32-CAM" not in names and "ESP-EYE" not in names, where
        firmware = " ".join(rec["firmware"])
        if sel["controller"] == "unoq" and sel["locomotion"] == "biped":
            assert "app_lab/microduck_agent" in firmware, where
        elif sel["controller"] in ("ev3", "hub51515"):
            assert "Robot Creator" in firmware and "code target" in firmware, where
        else:
            assert "Not written" in firmware, where


def test_impossible_recipes_give_a_reason_and_a_possible_neighbour(data, compat, recipes):
    count = 0
    for rec in recipes:
        if rec["status"] != "not_possible":
            continue
        count += 1
        where = rec["query"]
        assert all(len(text) > 20 for text in rec["reasons"]), where
        near = rec["nearest"]
        assert near["status"] in STATUSES - {"not_possible"}, where
        assert near["changes"], where
        again = recipe.evaluate(data, near["selection"])
        assert again["status"] == near["status"] and again["query"] == near["query"], where
        # The neighbour keeps the controller the reader said they have.
        assert near["selection"]["controller"] == rec["selection"]["controller"], where
    assert count


def test_named_cases(data):
    def run(**selection):
        return recipe.evaluate(data, selection)

    default = data["compat"]["defaults"]["camera"]
    assert run()["status"] == "analysed" and run()["selection"]["camera"] == default
    covered = {(e["match"]["controller"], e["match"]["camera"], e["match"]["head"]): e for e in data["coverage"]["entries"]}
    assert run()["analysis"] == covered[("unoq", default, "fixed")]["lines"]
    assert not any("overlap the deck" in text or "interference" in text for text in run()["assembly"] + run()["analysis"])
    for camera in ("esp32cam", "esp_eye", "esp32_s3_eye"):
        rec = run(camera=camera)
        assert rec["status"] == covered[("unoq", camera, "fixed")]["status"]
        cam_files = [item["file"] for item in rec["print"]["files"] if "cam" in item["file"]]
        assert cam_files == [f"fit_cam_{camera}.stl", f"01_torso_unoq_cam_{camera}.stl"]

    for controller, torso in (("pi", "01_torso_pi_zero_2w_cam_esp32cam.stl"), ("pi_full", "01_torso_pi_cam_esp32cam.stl")):
        rec = run(controller=controller, drive="servo_driver", camera="esp32cam")
        assert rec["status"] == "assembly_only"
        assert [item["file"] for item in rec["print"]["files"] if "torso" in item["file"]] == [torso]
        assert any(text.startswith("Not simulated") for text in rec["analysis"])
        other = run(controller=controller, drive="servo_driver", camera="esp_eye")
        assert other["status"] == "defined" and any("No torso file is committed" in text for text in other["reasons"])
        assert not [item for item in other["print"]["files"] if "torso" in item["file"]]

    for head in ("sg90_pan", "m5_360"):
        rec = run(head=head, camera="esp32cam")
        assert rec["status"] == "assembly_only"
        names = [item["file"] for item in rec["print"]["files"]]
        assert [name for name in names if "torso" in name or "head" in name] == [
            "01_torso_unoq_pan_head.stl", "head_pan_platform.stl", "head_tilt_cradle_esp32cam.stl"]
        assert names[:3] == ["fit_horn_drill_blank.stl", "fit_lego_compatible_coupon.stl", "fit_sg90_cradle.stl"]
        assert any("Tilt is set by hand" in text for text in rec["analysis"])
        assert any("no joint in the robot description, the simulation or the command format" in text for text in rec["analysis"])
        assert any("not written" in text.lower() for text in rec["firmware"])
        # The pan head was checked with one cradle; another camera's cradle exists as a part only.
        assert run(head=head, camera="esp_eye")["status"] == "defined"
    assert any("turns continuously" in text for text in run(head="m5_360")["wiring"])

    for controller, drive in (("ev3", "ev3_motors"), ("hub51515", "hub_motors")):
        carried = run(controller=controller, drive=drive, camera="none")
        assert carried["status"] == "not_possible"
        assert carried["reasons"][-1] == data["coverage"]["carried"][controller]
        assert "carried block only" in carried["reasons"][-1] and "makes nothing buildable" in carried["reasons"][-1]
        walker = run(controller=controller, locomotion="crank", drive=drive, camera="none")
        assert not any("carried block" in text for text in walker["reasons"] + walker["analysis"])
    pixy = run(camera="pixy2")
    assert pixy["status"] == "not_possible" and "not placed on the biped" in pixy["reasons"][0]
    empty = run(camera="none")
    assert empty["status"] == "defined"
    assert any("left empty" in text for text in empty["reasons"])
    assert [item["file"] for item in empty["print"]["files"] if "cam" in item["file"]] == [f"01_torso_unoq_cam_{default}.stl"]
    assert run(lego="off")["status"] == "defined"
    assert run(head="pixy_pantilt")["status"] == "not_possible"

    servo_on_ev3 = run(controller="ev3", drive="braccio_shield")
    assert servo_on_ev3["status"] == "not_possible"
    assert any("EV3 brick cannot drive hobby servos" in text for text in servo_on_ev3["reasons"])
    assert servo_on_ev3["nearest"]["selection"]["locomotion"] == "crank"

    six_on_four = run(controller="ev3", drive="ev3_motors")
    assert six_on_four["status"] == "not_possible"
    assert any("four output ports" in text and "cranks" in text for text in six_on_four["reasons"])

    walker = run(controller="ev3", locomotion="crank", drive="ev3_motors", lego="on", camera="pixy2")
    assert walker["status"] == "being_analysed"
    assert walker["preset"] == "ev3-pixy2"
    assert walker["print"]["files"][0]["file"] == "ev3-pixy2/fit_coupon.stl"
    assert any("LEGO I2C" in text for text in walker["wiring"])
    assert any(text.startswith("Being analysed") for text in walker["analysis"])

    pixy_on_hub = run(controller="hub51515", locomotion="crank", drive="hub_motors", lego="on", camera="pixy2")
    assert pixy_on_hub["status"] == "not_possible"
    assert "Power Functions 2.0" in pixy_on_hub["reasons"][0]

    pantilt = run(controller="ev3", locomotion="crank", drive="ev3_motors", lego="on", camera="pixy2", head="pixy_pantilt")
    assert any("not verified" in text for text in pantilt["firmware"])

    wheels = run(controller="unoq", locomotion="wheeled", drive="tt_hbridge", wheels="front", support="skid", wheel="tt65")
    assert wheels["status"] == "being_analysed"
    assert "wheels=front" in wheels["query"] and "support=skid" in wheels["query"]
    assert any("at the front" in text for text in wheels["wiring"])
    assert run(controller="unoq", locomotion="wheeled", drive="tt_hbridge", wheel="lego")["status"] == "not_possible"

    kit = run()
    assert any("10.00 A" in text and "2.5 times" in text for text in kit["power"])
    assert any(text.startswith("Mass ") and "g by the model" in text for text in kit["analysis"])


def test_wheel_choices_do_not_change_other_locomotions(data):
    plain = recipe.evaluate(data, {})
    varied = recipe.evaluate(data, {"wheels": "front", "support": "skid", "wheel": "tt65"})
    assert plain == varied
    assert "wheel" not in plain["query"]


def test_unknown_values_fall_back_to_the_defaults(data, compat):
    rec = recipe.evaluate(data, {"controller": "toaster", "nonsense": "1"})
    assert rec["selection"] == recipe.normalise(compat, compat["defaults"])


def test_evaluate_is_pure(data):
    before = json.dumps(data, sort_keys=True)
    one = recipe.evaluate(data, {"controller": "pi", "locomotion": "wheeled", "drive": "m5_360_wheels", "head": "m5_360"})
    two = recipe.evaluate(data, {"controller": "pi", "locomotion": "wheeled", "drive": "m5_360_wheels", "head": "m5_360"})
    assert one == two
    assert json.dumps(data, sort_keys=True) == before


# --- manifest and variants summary ------------------------------------------

def test_files_link_only_when_the_manifest_names_them(data):
    rich = rich_bundle(data)
    rec = recipe.evaluate(data, {})
    # The committed biped parts are served by the site and linked there.
    assert rec["print"]["files"] and all(item["link"] == "./stl/" + item["file"] for item in rec["print"]["files"])
    base = {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"}
    assert all(item["link"] is None for item in recipe.evaluate(data, base)["print"]["files"])
    walker = recipe.evaluate(rich, base)
    links = {item["file"]: item["link"] for item in walker["print"]["files"]}
    # A path the manifest names outside its files list is linked in the repository, not on the site.
    assert links["ev3-pixy2/chassis.stl"] == data["compat"]["repo_blob"] + "stl/lego/ev3-pixy2/chassis.stl"
    assert links["ev3-pixy2/left_leg.stl"] is None
    bare = copy.deepcopy(data)
    bare["manifest"] = {"present": False, "paths": [], "served": [], "files": [], "info": {}, "camera_default": "none",
                        "controller_default": "unoq"}
    assert recipe.evaluate(bare, {})["print"]["files"] == []
    assert "no STL manifest" in recipe.evaluate(bare, base)["print"]["note"]


def test_the_real_manifest_is_read_as_it_is(data):
    listed = json.loads((ROOT / "stl" / "manifest.json").read_text(encoding="utf-8"))
    names = [entry["file"] for entry in listed["files"]]
    assert data["manifest"]["present"] and data["manifest"]["served"] == names
    assert data["manifest"]["paths"] == sorted(names)
    by_name = {entry["file"]: entry for entry in data["manifest"]["files"]}
    home = json.loads((ROOT / "stl" / "parameters.json").read_text(encoding="utf-8"))["controller_default"]
    assert data["manifest"]["controller_default"] == home
    for entry in listed["files"]:
        options = entry["options"]
        assert set(options) <= {"part", "fit_piece", "controller", "head", "camera"}, entry["file"]
        mine = by_name[entry["file"]]
        assert mine["camera"] == options.get("camera") and mine["head"] == options.get("head")
        assert mine["part"] == options.get("part") and mine["fit"] == bool(options.get("fit_piece"))
        # A torso without a controller option is the default controller's.
        assert mine["controller"] == options.get("controller", home if options.get("part") == "torso" else None)
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
    used = set()
    for sel in recipe.combinations(data["compat"]):
        used.update(item["file"] for item in recipe.evaluate(data, sel)["print"]["files"] if item["link"])
    # The hub torso and the Pixy plates are parts in the manifest that no recipe lists.
    assert set(names) - used == {"01_torso_hub51515_cam_esp32cam.stl", "head_pixy_plate_pixy1.stl", "head_pixy_plate_pixy2.stl"}


def test_the_default_camera_is_one_switch_in_config(tmp_path, data):
    preset = json.loads((ROOT / "config" / "assembly.json").read_text(encoding="utf-8"))["camera"]["preset"]
    assert data["compat"]["defaults"]["camera"] == preset == data["manifest"]["camera_default"]
    assert json.loads((ROOT / "config" / "compat.json").read_text(encoding="utf-8"))["defaults"]["camera"] == ""
    for folder in ("config", "reports", "stl"):
        shutil.copytree(ROOT / folder, tmp_path / folder, ignore=shutil.ignore_patterns("*.stl"))
    other = "esp_eye" if preset != "esp_eye" else "esp32cam"
    config = json.loads((tmp_path / "config" / "assembly.json").read_text(encoding="utf-8"))
    config["camera"]["preset"] = other
    (tmp_path / "config" / "assembly.json").write_text(json.dumps(config), encoding="utf-8")
    switched = recipe.bundle(tmp_path)
    rec = recipe.evaluate(switched, {})
    assert rec["selection"]["camera"] == other
    # The verdict still follows the reports, which were not regenerated in this copy.
    assert rec["status"] == "assembly_only"
    empty = recipe.evaluate(switched, {"camera": "none"})
    assert f"01_torso_unoq_cam_{other}.stl" in [item["file"] for item in empty["print"]["files"]]


def test_analysed_means_what_the_reports_cover(data, recipes):
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


def test_status_and_numbers_for_walkers_come_from_the_summary(data):
    rich = rich_bundle(data)
    base = {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors", "camera": "none"}
    assert recipe.evaluate(data, base)["status"] == "being_analysed"
    rec = recipe.evaluate(rich, base)
    assert rec["status"] == "analysed"
    assert "Mass 900 g by the model." in rec["analysis"]
    # An addition outside the summary takes the verdict away again.
    assert recipe.evaluate(rich, {**base, "head": "lego_motor"})["status"] == "defined"
    tpu = recipe.evaluate(rich, {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_tpu"})
    assert tpu["status"] == "defined"
    assert tpu["print"]["files"][0]["link"].endswith("/blob/main/stl/wheeled/wheel_hub_cross.stl")
    assert tpu["parts"][-1]["name"] == "O-ring 50 x 3 mm"
    ring = recipe.evaluate(rich, {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge"})
    assert ring["status"] == "being_analysed"
    assert any("in progress" in text for text in ring["analysis"])


def test_summary_and_manifest_files_are_read_when_present(tmp_path, compat):
    for folder in ("config", "reports"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    assert recipe.bundle(tmp_path)["variants"] == []
    assert recipe.bundle(tmp_path)["manifest"] == {"present": False, "paths": [], "served": [], "files": [], "info": {},
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
    (tmp_path / "stl").mkdir()
    (tmp_path / "stl" / "manifest.json").write_text(json.dumps({"files": [
        {"file": "fit_SR431.stl", "what": "fit piece for an SR431 servo cradle", "options": {"fit_piece": True}}],
        "walkers": [{"path": "stl/lego/ev3-pixy2/chassis.stl", "sha256": "0"}]}), encoding="utf-8")
    loaded = recipe.bundle(tmp_path)
    assert loaded["manifest"]["paths"] == ["fit_SR431.stl", "lego/ev3-pixy2/chassis.stl"]
    assert loaded["manifest"]["served"] == ["fit_SR431.stl"]
    assert loaded["manifest"]["files"] == [
        {"file": "fit_SR431.stl", "what": "fit piece for an SR431 servo cradle", "fit": True, "part": None,
         "controller": None, "head": None, "camera": None}]
    # The entry with no drive is ambiguous on the Pi and the unknown base matches nothing: both are dropped.
    assert [entry["match"] for entry in loaded["variants"]] == [
        {"controller": "ev3", "locomotion": "crank", "drive": "ev3_motors"},
        {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge", "wheel": "printed_ring"}]
    assert loaded["variants"][0]["status"] == "analysed"
    assert loaded["variants"][0]["lines"] == ["Mass 912.5 g by the model.", "Stability: stands on both feet"]
    # A status this page does not know is shown as written and never promoted.
    assert loaded["variants"][1]["status"] == "being_analysed"
    rec = recipe.evaluate(loaded, {"controller": "pi", "locomotion": "wheeled", "drive": "tt_hbridge"})
    assert rec["status"] == "being_analysed"
    assert any("simulated, tips on braking" in text for text in rec["analysis"])
    assert rec["parts"][-1] == {"name": "O-ring 60 x 3 mm", "qty": 2, "note": "from the variants summary"}
    for sel in recipe.combinations(compat):
        out = recipe.evaluate(loaded, sel)
        if out["status"] == "analysed" and out["selection"]["controller"] != "unoq":
            assert out["selection"]["controller"] == "ev3" and out["selection"]["locomotion"] == "crank"


# --- the JavaScript evaluator -----------------------------------------------

@pytest.mark.parametrize("kind", ["as committed", "with a manifest and a summary"])
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
    shutil.copyfile(ROOT / "site" / "build.js", tmp_path / "build.mjs")
    (tmp_path / "driver.mjs").write_text(DRIVER, encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(used), encoding="utf-8")
    (tmp_path / "selections.json").write_text(json.dumps(selections), encoding="utf-8")
    subprocess.run([node, "driver.mjs", "data.json", "selections.json", "out.json"], cwd=tmp_path, check=True,
                   capture_output=True, timeout=300)
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert len(got) == len(expected)
    for mine, theirs in zip(expected, got):
        assert mine == theirs, mine["query"]
    # Unknown and missing values are normalised the same way.
    assert {rec["status"] for rec in got} == {rec["status"] for rec in expected}
