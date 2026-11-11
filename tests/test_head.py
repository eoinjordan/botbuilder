# SPDX-License-Identifier: MIT
"""The optional turning head: pan servo, printed stops, hand-set tilt."""
import pytest
import trimesh

from conftest import ROOT, needs_stls
from microduck import assembly, model


@pytest.fixture(scope="module")
def head(assembly_report):
    return assembly_report["turning_head"]


def test_pan_runs_between_printed_stops(head):
    lo, hi = head["pan_travel_to_the_stops_deg"]
    assert lo == pytest.approx(-hi, abs=0.5)
    assert 60 <= hi <= 90, "the stops must end the travel well short of a turn, so the lead cannot wind up"
    for side in ("negative", "positive"):
        pairs = {(b["moving"], b["fixed"]) for b in head["pan_stopped_by"][side]}
        assert pairs == {("head_platform_print", "torso_print")}, "only the peg and post may end the travel"


def test_tilt_reaches_its_setting_by_hand(head):
    lo, hi = head["tilt_free_deg"]
    assert lo < 0 < head["tilt_set_to_deg"] < hi


def test_head_meets_nothing_and_costs_the_legs_no_travel(head, selected):
    assert head["neutral_interferences"] == []
    for pose in head["at_the_stand_pose"]:
        assert pose["new_interferences"] == []
    limits = selected["joint_limits_deg"]
    for joint, (lo, hi) in head["leg_sweeps_collision_free_deg"].items():
        assert lo <= limits[joint]["min_deg"] - 3 or limits[joint]["min_set_by"] == "collision"
        assert hi >= limits[joint]["max_deg"] + 3


def test_view_is_clear_straight_ahead_and_balance_holds_at_the_stops(head, selected):
    centre = next(p for p in head["at_the_stand_pose"] if p["pan_deg"] == 0)
    assert centre["in_the_cone"] == []
    base = selected["balance"]["stand_pose"]["margin_mm"]
    for pose in head["at_the_stand_pose"]:
        assert pose["stand_margin_mm"] > base - 3.0
    assert 20 < head["head_mass_g"] < 60
    assert 520.0 < head["total_g"] < 575.0


def test_faces_on_the_platform_are_analysed(assembly_report, selected):
    heads = assembly_report["turning_head_with_faces"]
    assert set(heads) == {"eyes_above_esp_eye", "eyes_below_esp_eye", "stack_camera_forward"}
    for name, head in heads.items():
        assert head["neutral_interferences"] == [], name
        lo, hi = head["pan_travel_to_the_stops_deg"]
        assert hi >= 60 and lo <= -60, name
        for pose in head["at_the_stand_pose"]:
            assert pose["new_interferences"] == [], name
            assert pose["stand_margin_mm"] > 30.0, name
        assert head["tilt_free_deg"][0] < 0 < head["tilt_free_deg"][1], name
    stack = assembly_report["stack_camera_forward"]
    assert stack["neutral_interferences"] == [] and stack["display_overlap_with_print_mm3"] < 0.5
    assert stack["cone_blocked_at_neutral"] == [] and stack["cone_blocked_at_stand"] == []
    assert stack["stand_margin_mm"] > 30.0


def test_documents_say_what_the_servo_is():
    text = (ROOT / "docs" / "head.md").read_text(encoding="utf-8")
    for phrase in ("continuous rotation", "not in the URDF", "No firmware for the head exists", "trademarks of the LEGO Group"):
        assert phrase in text, phrase
    hardware = model.load_json("hardware.json")
    assert hardware["head_servo"]["published"]["kit_360_is_continuous_rotation"] is True


def test_six_joint_description_is_untouched(joints):
    assert len(model.JOINTS) == 6 and set(model.JOINTS) == set(joints["joints"])
    assert not set(model.HEAD_JOINTS) & set(model.JOINTS)
    robot = model.build_robot(load_meshes=False)
    assert "head_pan" not in robot.links


@needs_stls
def test_head_parts_are_closed_solids():
    names = list(model.HEAD_FILES.values()) + ["fit_sg90_cradle.stl", "head_pixy_plate_pixy2.stl", "head_pixy_plate_pixy1.stl"]
    names += [f"head_tilt_cradle_{name}.stl" for name in model.CAMERAS]
    for name in sorted(set(names)):
        mesh = trimesh.load_mesh(model.stl_dir() / name)
        assert mesh.is_volume and len(mesh.split()) == 1 and mesh.volume > 0, name


@needs_stls
def test_pan_stop_is_reproducible(head):
    config = model.load_json("assembly.json")
    robot = model.build_robot(assembly=dict(config, head="pan"))
    sweep = assembly.sweep_joint(robot, "head_pan", 1.0, config["interference_threshold_mm3"], set(), {"head_tilt": head["tilt_set_to_deg"]})
    assert sweep["collision_free_deg"] == pytest.approx(head["pan_travel_to_the_stops_deg"], abs=0.3)
