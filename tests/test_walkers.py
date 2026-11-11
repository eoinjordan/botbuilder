# SPDX-License-Identifier: MIT
"""The two crank walkers: printable files, parts data, assembly and balance,
generated models, documents and controller sketches."""
import ast
import hashlib
import json

import numpy as np
import pytest

from conftest import ROOT
from walkers import assembly, mjcf, model, report

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
    on_disk = {p.relative_to(ROOT / "stl" / "lego").as_posix() for p in (ROOT / "stl" / "lego").rglob("*.stl")}
    assert listed == on_disk
    for f in manifest["files"]:
        data = (ROOT / "stl" / "lego" / f["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"], f["file"]
        assert len(data) == f["bytes"] == 84 + 50 * f["triangles"]
        assert f["watertight"] and f["volume_cm3"] > 0
        assert len(f["design_commit"]) == 40, f["file"]
        assert f["purpose"] and f["print_quantity"] >= 0
    assert manifest["total_bytes"] == sum(f["bytes"] for f in manifest["files"])


def test_each_walker_has_its_full_print_set(manifest):
    for build in BUILDS:
        quantity = {f["file"].split("/")[1]: f["print_quantity"] for f in manifest["files"] if f["file"].startswith(build + "/")}
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
        assert max(v["min_margin_mm"] for v in forward) < min(v["min_margin_mm"] for v in rear)
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
    assert "Nothing here has been printed, assembled or powered" in doc
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group, which does not sponsor or endorse this" in doc
    summary = json.loads((ROOT / "reports" / "variants" / "summary.json").read_text(encoding="utf-8"))
    walkers = [e for e in summary["entries"] if e["locomotion"] == "crank walker"]
    assert [e["build"] for e in walkers] == list(BUILDS)
    for entry in walkers:
        assert entry["status"].startswith("analysed and simulated only")
        assert entry["mass_g"] == assembly_json["builds"][entry["build"]]["mass"]["total_g"]
        assert (ROOT / entry["controller_sketch"]).is_file()


def test_controller_sketches_parse_and_are_marked_not_run():
    ev3 = (ROOT / "walkers" / "controllers" / "ev3_walker.py").read_text(encoding="utf-8")
    hat = (ROOT / "walkers" / "controllers" / "buildhat_walker.py").read_text(encoding="utf-8")
    for source in (ev3, hat):
        ast.parse(source)
        assert "NOT RUN ON HARDWARE" in source
    assert "Motor(Port.B" in ev3 and "Motor(Port.C" in ev3 and "track_target" in ev3
    assert "from pybricks.ev3devices import Motor" in ev3
    assert 'LEFT_PORT = "A"' in hat and 'RIGHT_PORT = "B"' in hat and "from buildhat import Motor" in hat


def test_walker_page(manifest):
    html = (ROOT / "site" / "walkers.html").read_text(encoding="utf-8")
    script = (ROOT / "site" / "walkers.js").read_text(encoding="utf-8")
    css = (ROOT / "site" / "walkers.css").read_text(encoding="utf-8")
    import re
    for name, text in (("walkers.html", html), ("walkers.js", script), ("walkers.css", css)):
        assert not re.search(r'(src|href)="/[^/]', text), name
        assert not re.search(r'fetch\(["`]/', text), name
    assert "analysed and simulated only, never assembled" in html
    assert "LEGO, Mindstorms and Technic are trademarks of the LEGO Group" in html
    assert "which does not sponsor or endorse this" in html and "Raspberry Pi is a trademark of Raspberry Pi Ltd" in html
    assert "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js" in html
    assert re.findall(r"<script[^>]*src=\"([^\"]+)\"", html) == ["./walkers.js"]
    assert set(re.findall(r"https://[a-z0-9.-]+", html + script)) <= {"https://cdn.jsdelivr.net", "https://github.com"}
    assert "./stl/lego/" in script and 'href="./walkers.html"' in (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "<img" not in html or "logo" not in html.lower()
