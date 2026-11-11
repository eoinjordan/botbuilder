# SPDX-License-Identifier: MIT
"""The two crank walkers: printable files, parts data, assembly and balance,
generated models, documents and controller sketches."""
import ast
import hashlib
import json

import numpy as np
import pytest

from conftest import ROOT
from walkers import assembly, mjcf, model, programs, report

BUILDS = model.BUILDS


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "stl" / "lego" / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assembly_json():
    return json.loads((ROOT / "reports" / "lego" / "assembly.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sim_json():
    return json.loads((ROOT / "reports" / "lego" / "sim.json").read_text(encoding="utf-8"))


def test_manifest_matches_the_committed_stls(manifest):
    listed = {f["file"] for f in manifest["files"]}
    on_disk = {p.relative_to(ROOT / "stl").as_posix() for p in (ROOT / "stl" / "lego").rglob("*.stl")}
    assert listed == on_disk
    known = {"controller", "locomotion", "drive", "wheel", "support", "camera", "head", "part", "fit_piece", "wheel_class"}
    for f in manifest["files"]:
        data = (ROOT / "stl" / f["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"], f["file"]
        assert len(data) == f["bytes"] == 84 + 50 * f["triangles"]
        assert f["watertight"] and f["volume_mm3"] > 0
        assert len(f["design_commit"]) == 40, f["file"]
        assert f["what"] and f["print_quantity"] >= 0
        assert f["options"] and set(f["options"]) <= known and "part" in f["options"], f["file"]
        assert f["options"].get("fit_piece", False) == f["file"].rsplit("/", 1)[-1].startswith("fit_")
    assert manifest["total_bytes"] == sum(f["bytes"] for f in manifest["files"])
    by_file = {f["file"]: f["options"] for f in manifest["files"]}
    assert by_file["lego/ev3-pixy2/chassis.stl"] == {"controller": "ev3", "part": "chassis"}
    assert by_file["lego/hub-51515/left_leg.stl"] == {"controller": "hub51515", "part": "left_leg", "locomotion": "crank"}
    assert by_file["lego/ev3-pixy2/camera_head_pantilt.stl"]["head"] == "pixy_pantilt"
    assert by_file["lego/wheeled/tip_ball_16p5.stl"]["support"] == "roller"
    assert by_file["lego/wheeled/wheel_solid_tt_d65.stl"] == {"locomotion": "wheeled", "part": "wheel", "wheel": "printed_ring",
                                                               "drive": "tt_hbridge", "wheel_class": "d65"}


def test_each_walker_has_its_full_print_set(manifest):
    for build in BUILDS:
        quantity = {f["file"].split("/")[2]: f["print_quantity"] for f in manifest["files"] if f["file"].startswith(f"lego/{build}/")}
        assert quantity["chassis.stl"] == quantity["left_leg.stl"] == quantity["right_leg.stl"] == quantity["camera_head.stl"] == 1
        assert quantity["crank_print_4.stl"] == 4 and quantity["gear_16t_print_6.stl"] == 6 and quantity["fit_coupon.stl"] == 1


def test_component_facts_carry_a_source_or_a_reason():
    comp = model.load_json("components.json")
    count = 0
    for key, part in comp.items():
        if key.startswith("_"):
            continue
        for item, v in part.items():
            if not isinstance(v, dict) or "class" not in v:
                continue
            count += 1
            assert v["class"] in ("maker", "third-party", "assumed"), (key, item)
            if v["class"] == "assumed":
                assert v.get("why"), (key, item)
            else:
                assert v["source"].startswith("https://"), (key, item)
    assert count > 40
    assert comp["ev3_large_motor"]["stall_torque_nm"]["value"] == 0.40
    assert comp["angular_motor"]["stall_torque_nm"]["value"] == 0.18


def test_kinematics_legs_translate_on_a_circle_half_a_turn_apart():
    for phase in range(0, 360, 30):
        left, right = model.leg_shift("left", phase), model.leg_shift("right", phase)
        assert np.allclose(left, -right)
        assert np.isclose(np.hypot(left[0], left[2]), model.CRANK_R)
    # Phase increasing: the foot on the floor moves backward, so the robot goes forward.
    assert model.stance(90) == ("left",) and model.stance(270) == ("right",)
    assert model.leg_shift("left", 100)[0] < model.leg_shift("left", 80)[0]
    assert set(model.stance(0)) == {"left", "right"}
    assert model.STRIDE == 48.0


def test_crank_tips_stay_on_the_leg_pivots():
    walker = model.build_walker("ev3-pixy2")
    for side, sign in (("left", 1), ("right", -1)):
        for phase in (0, 45, 130, 250):
            for label, x in (("rear", -16.0), ("front", 16.0)):
                crank = walker.item(f"{side} {label} crank")
                tip = (crank.pose(phase) @ [model.CRANK_R, 0.0, 3.9, 1.0])[:3]
                hole = (walker.item(f"{side} leg").pose(phase) @ [x, sign * 3.9, model.LEG_DROP, 1.0])[:3]
                assert np.allclose(tip[[0, 2]], hole[[0, 2]], atol=1e-9), (side, label, phase)


def test_mass_and_balance_agree_with_the_report(assembly_json):
    for build in BUILDS:
        walker = model.build_walker(build)
        rep = assembly_json["builds"][build]
        assert walker.mass_g() == pytest.approx(rep["mass"]["total_g"], abs=0.1)
        assert np.allclose(walker.com(90.0), rep["centre_of_mass_mm"], atol=0.1)
        st = assembly.stability(walker)
        assert st["min_margin_mm"] == pytest.approx(rep["stability"]["min_margin_mm"], abs=0.1)
        assert st["stable_at_every_phase"]
    assert assembly_json["builds"]["ev3-pixy2"]["mass"]["total_g"] == pytest.approx(811.5, abs=5)
    assert assembly_json["builds"]["pi-zero-2w-51515"]["mass"]["total_g"] == pytest.approx(377.9, abs=5)


def test_balance_headlines(assembly_json):
    for build in BUILDS:
        rep = assembly_json["builds"][build]
        # The sideways reach of the finger tips sets the margin.
        assert rep["stability"]["min_margin_mm"] == pytest.approx(10.2, abs=0.5)
        assert rep["com_window"]["y_range_mm_at_com_x"] == [-10.5, 10.5]
        assert 3.0 < rep["stability"]["tilt_to_tip_deg"] < 7.0
        forward = [v for k, v in rep["variants"].items() if "forward" in k]
        rear = [v for k, v in rep["variants"].items() if "rear" in k]
        assert max(v["min_margin_mm"] for v in forward) <= min(v["min_margin_mm"] for v in rear)
    place = assembly_json["builds"]["ev3-pixy2"]["placement"]
    assert place["x_range_balanced_mm"][0] < -40 and place["x_range_balanced_mm"][1] > 50
    assert place["x_range_at_full_margin_mm"][0] <= -10 and place["x_range_at_full_margin_mm"][1] >= 10


def test_no_interference_reported_and_a_live_spot_check(assembly_json):
    for build in BUILDS:
        inter = assembly_json["builds"][build]["interference"]
        assert inter["rest"] == [] and inter["cycle"] == []
        assert inter["phases_checked"] == 72
        assert {"left motor", "right motor", "chassis", "head"} <= set(inter["fixed_parts"])
    walker = model.build_walker("ev3-pixy2")
    fixed = {n: walker.item(n).placed() for n in ("chassis", "left motor", "EV3 brick", "left idler axle bush")}
    for phase in (0, 90, 200):
        leg, other = walker.item("left leg").placed(phase), walker.item("right leg").placed(phase)
        crank = walker.item("left rear crank").placed(phase)
        assert (leg ^ other).volume() < 1e-3
        for name, solid in fixed.items():
            assert (leg ^ solid).volume() < 1e-3, (name, phase)
            assert (crank ^ solid).volume() < 1e-3, (name, phase)
    # The check can fail: a leg moved 10 mm inward runs into its cranks.
    inward = model.apply(walker.item("left leg").solid, model.trans(0.0, model.LEG_Y - 10.0, -model.LEG_DROP))
    assert (inward ^ walker.item("left rear crank").placed(0.0)).volume() > 10.0


def test_gear_is_module_one_on_the_axle_spacing(assembly_json):
    g = assembly.gear_mesh("ev3-pixy2", model.load_json("components.json"))
    assert g["teeth"] == 16 and g["module_mm"] == 1.0
    assert g["centre_distance_error_mm"] == 0.0
    assert 0.2 < g["backlash_per_mesh_mm"] < 0.6
    assert g["overlap_through_one_tooth_mm3"] == 0.0
    assert g["tip_to_root_clearance_mm"] == pytest.approx(0.4, abs=0.01)
    assert {k: v for k, v in assembly_json["gear_mesh"].items() if k != "picture"} == g


def test_generated_models_are_current():
    for build in BUILDS:
        xml, meta = mjcf.generate(build)
        assert xml == (ROOT / "robot" / "lego" / f"{build}.xml").read_text(encoding="utf-8"), build
        assert meta == json.loads((ROOT / "robot" / "lego" / f"{build}.json").read_text(encoding="utf-8")), build
        assert xml.count("<connect ") == 2 and xml.count('<joint name="left_gear_train"') == 1


def test_documents_are_current_and_say_their_status(assembly_json, sim_json, manifest):
    comp = model.load_json("components.json")
    doc = (ROOT / "docs" / "lego-walkers.md").read_text(encoding="utf-8")
    assert doc == report.document(assembly_json, sim_json, comp, manifest)
    # The detail the pages no longer carry stays here.
    assert "Nothing here has been printed, assembled or powered" in doc
    assert "## Unverified" in doc and "| assumed |" in doc
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not sponsor or endorse this" in doc
    summary = json.loads((ROOT / "reports" / "variants" / "summary.json").read_text(encoding="utf-8"))
    assert summary == report.summary(assembly_json, sim_json)
    walkers = [e for e in summary["entries"] if e["locomotion"] == "crank"]
    assert [e["build"] for e in walkers] == list(BUILDS)
    assert [(e["controller"], e["drive"]) for e in walkers] == [("ev3", "ev3_motors"), ("pi", "buildhat_51515"), ("hub51515", "hub_motors")]
    listed = {f["file"] for f in manifest["files"]}
    for entry in walkers:
        assert entry["status"] == "analysed in simulation"
        assert entry["mass_g"] == assembly_json["builds"][entry["build"]]["mass"]["total_g"]
        assert entry["stability_verdict"] and entry["notes"] and entry["turns"] is False
        assert {f["file"] for f in entry["files"]} <= listed and len(entry["files"]) == 7
        assert entry["files"][0]["fit"] and sum(f["qty"] for f in entry["files"]) == 15
        assert any("half bush" in p["name"].lower() for p in entry["parts"])
        assert entry["programs"], entry["build"]
        for program in entry["programs"]:
            assert (ROOT / program["file"]).is_file()


def test_programs_compile_and_the_index_is_current():
    index = programs.index()                      # compiles every file
    assert index == json.loads((ROOT / "programs" / "index.json").read_text(encoding="utf-8"))
    files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "programs").rglob("*.py")}
    assert files == {p["file"] for p in index["programs"]}
    lego = [p for p in index["programs"] if p["controller"] in ("ev3", "hub51515")]
    assert len(lego) == 8
    for controller in ("ev3", "hub51515"):
        for locomotion in ("crank", "wheeled"):
            assert len([p for p in lego if (p["controller"], p["locomotion"]) == (controller, locomotion)]) == 2
    targets = {"ev3": {"pybricks-ev3", "ev3dev-python"}, "hub51515": {"pybricks-python", "lego-stock-python"}}
    for p in lego:
        source = (ROOT / p["file"]).read_text(encoding="utf-8")
        ast.parse(source)
        assert p["language"] in targets[p["controller"]]
        assert p["load_with"]["name"] == "Mindstorms Robot Creator" and p["load_with"]["code_target"] == p["language"]
        flat = " ".join(source.replace("#", " ").split())
        assert p["load_with"]["url"] in source and f"code target: {p['language']}" in flat
        assert p["load_with"]["sends_to_the_brick"] is (p["language"] == "pybricks-python")
        assert "customCode" in source and "Ports:" in source
    ev3 = (ROOT / "programs" / "ev3" / "crank-walker" / "walker_pybricks.py").read_text(encoding="utf-8")
    assert "Motor(Port.B" in ev3 and "Motor(Port.C" in ev3 and "track_target" in ev3 and "reset_angle(180)" in ev3
    hub = (ROOT / "programs" / "hub51515" / "crank-walker" / "walker_pybricks.py").read_text(encoding="utf-8")
    assert "Motor(Port.A" in hub and "Motor(Port.B" in hub and "run_target" in hub
    stock = (ROOT / "programs" / "hub51515" / "crank-walker" / "walker_lego_python.py").read_text(encoding="utf-8")
    assert "from mindstorms import MSHub, Motor" in stock
    # Only the stock calls that could be confirmed are used.
    for call in (".run_to_position(", "left_button", "light_matrix", "set_degrees_counted"):
        assert call not in stock.split('hub = MSHub()')[1]


PAGES = ("walkers.html", "wheeled.html", "walkers.js", "wheeled.js", "lego-common.js", "walkers.css")
REMOVED_TONE = ("never assembled", "never built", "not run on hardware", "unverified", "assumed", "analysed and simulated only",
                "not validated", "not been fit-tested")


def test_walker_and_wheeled_pages():
    import re
    text = {name: (ROOT / "site" / name).read_text(encoding="utf-8") for name in PAGES}
    for name, body in text.items():
        assert not re.search(r'(src|href)="/[^/]', body), name
        assert not re.search(r'fetch\(["`]/', body), name
        for phrase in REMOVED_TONE:
            assert phrase not in body.lower(), (name, phrase)
    for page, script in (("walkers.html", "./walkers.js"), ("wheeled.html", "./wheeled.js")):
        html = text[page]
        assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in html
        assert "which does not sponsor, authorise or endorse this" in html and "Raspberry Pi is a trademark of Raspberry Pi Ltd" in html
        assert "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js" in html
        assert re.findall(r"<script[^>]*src=\"([^\"]+)\"", html) == ["./nav.js", script, "./tour.js"]
        assert '<nav id="site-nav"' in html and 'href="./wheeled.html"' in html and 'href="./walkers.html"' in html
        assert "Bot<b>builder</b>" in html and "fit" in html.lower()
    everything = "".join(text.values())
    assert set(re.findall(r"https://[a-z0-9.-]+", everything)) <= {"https://cdn.jsdelivr.net", "https://github.com", "https://eoinjordan.github.io"}
    assert "https://eoinjordan.github.io/mindstorms-robot-creator/" in text["walkers.html"]
    assert "half bush" in text["walkers.html"] and "cannot turn" in text["walkers.html"] and "Point the motors backward" in text["walkers.html"]
    assert "ramped start" in text["wheeled.html"] and "A bare printed wheel slips" in text["wheeled.html"]
    assert 'href="./walkers.html"' in (ROOT / "site" / "index.html").read_text(encoding="utf-8"), "the shared navigation"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Crank walkers and two-wheeled builds")[1].split("\n## ")[0]
    for phrase in REMOVED_TONE:
        assert phrase not in section.lower(), phrase