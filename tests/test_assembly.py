# SPDX-License-Identifier: MIT
"""Invariants of the assembly report, and that the model still reproduces it."""
import numpy as np
import pytest

from conftest import ROOT, needs_stls
from microduck import assembly, model
from microduck.model import JOINTS


def test_report_shape(assembly_report):
    assert assembly_report["selected"] in ("rail", "flat")
    assert set(assembly_report["variants"]) == {"rail", "flat"}
    assert "never printed" in assembly_report["status"]
    assert assembly_report["findings"]
    assert assembly_report["assumptions"]["dimensions"], "assumed dimensions must be listed"
    for source in assembly_report["sources"].values():
        assert source.startswith("https://")


def test_every_picture_exists(assembly_report):
    for path in assembly_report["images"].values():
        assert (ROOT / "docs" / path).is_file(), path


def test_joint_limits_are_inside_servo_travel_and_free_range(selected):
    for joint in JOINTS:
        limit = selected["joint_limits_deg"][joint]
        free = selected["sweeps"][joint]["collision_free_deg"]
        assert -90.0 <= limit["min_deg"] < 0.0 < limit["max_deg"] <= 90.0
        assert free[0] <= limit["min_deg"] and limit["max_deg"] <= free[1]
        assert limit["min_set_by"] in ("collision", "servo travel")


def test_left_and_right_sweeps_mirror(selected):
    for name in ("hip_roll", "hip_pitch", "knee"):
        left = selected["sweeps"][f"left_{name}"]["collision_free_deg"]
        right = selected["sweeps"][f"right_{name}"]["collision_free_deg"]
        if name == "hip_roll":      # roll about +x mirrors with a sign change
            assert left == pytest.approx([-right[1], -right[0]], abs=0.5)
        else:
            assert left == pytest.approx(right, abs=0.5)


def test_mass_adds_up(selected):
    mass = selected["mass"]
    assert sum(mass["by_kind_g"].values()) == pytest.approx(mass["total_g"], abs=0.2)
    assert sum(link["mass_g"] for link in mass["links"].values()) == pytest.approx(mass["total_g"], abs=0.5)
    assert mass["by_kind_g"]["servo"] == pytest.approx(4 * 62.0 + 2 * 27.0)
    assert mass["total_g"] < mass["total_if_printed_solid_g"]
    assert abs(mass["com_neutral_mm"][1]) < 0.5, "centre of mass should be on the mid plane"


def test_cradles(selected):
    assert len(selected["cradles"]) == 6
    for cradle in selected["cradles"]:
        assert cradle["rail_clearance_each_side_mm"] == pytest.approx(0.5, abs=0.02)
        assert cradle["seat_support_fraction"] == pytest.approx(1.0, abs=0.01)
        assert cradle["tie_slots_open"] == cradle["tie_slots_expected"] == 8
        assert len(cradle["ties"]) == 4
        assert sum(tie["clear"] for tie in cradle["ties"]) >= 2, "two ties must cross the case clear of the shaft"
        assert cradle["body_interference_mm3"] < 0.5


def test_horns(selected):
    assert len(selected["horns"]) == 6
    for horn in selected["horns"]:
        assert horn["hole_on_shaft_axis"]
        assert horn["horn_within_blank"]


def test_balance_findings_are_consistent(selected):
    balance = selected["balance"]
    stand = balance["stand_pose"]
    assert stand["inside"] and stand["margin_mm"] > 0
    assert stand["q_deg"]["left_hip_pitch"] == -stand["q_deg"]["left_knee"], "soles level at the stand pose"
    for joint in JOINTS:
        limit = selected["joint_limits_deg"][joint]
        assert limit["min_deg"] <= stand["q_deg"][joint] <= limit["max_deg"]
    assert balance["stand_pose_interferences"] == []
    neutral = balance["neutral_two_feet"]
    assert neutral["inside"] == (neutral["margin_mm"] > 0)
    for side in ("left", "right"):
        one = balance[f"one_foot_{side}"]
        assert one["at_stand_pose"]["inside"] == (one["at_stand_pose"]["margin_mm"] > 0)
        assert one["balances_within_30_deg"] in (True, False)


def test_nothing_interferes_at_the_neutral_pose(assembly_report, selected):
    assert selected["neutral_interferences"] == []
    assert assembly_report["variants"]["flat"]["neutral_interferences"] == []
    seat = selected["roll_seat"]
    assert seat["case_overlap_with_deck_mm3"] == 0 and seat["upper_ear_overlap_with_deck_mm3"] == 0
    assert seat["case_end_below_deck_mm"] == pytest.approx(0.5, abs=0.02)
    assert seat["upper_ear_gap_to_deck_mm"] >= 0.5
    assert seat["deck_width_at_the_cut_mm"] >= 90.0


def test_model_constants_match_the_generator():
    made = model.design_parameters()
    assert made["roll_seat_fix"] is True
    assert made["roll_cradle_z"] == model.TORSO_CRADLE_Z
    assert tuple(made["tie_slot_fractions"]) == model.SLOT_X_FRACTIONS


def test_findings_name_every_neutral_interference(assembly_report, selected):
    interference_findings = [f for f in assembly_report["findings"] if f["level"] == "interference"]
    assert len(interference_findings) == len(selected["neutral_interferences"])


def test_model_without_stls_matches_the_report(selected):
    """The joint chain needs only the servo data, so this runs anywhere."""
    robot = model.build_robot(load_meshes=False)
    frames = robot.fk()
    for name, link in robot.links.items():
        if link.joint:
            assert frames[name][:3, 3] == pytest.approx(selected["dimensions"]["joint_origins_mm"][link.joint], abs=0.01)
    assert [link.joint for link in robot.links.values() if link.joint] == JOINTS


def test_servo_shape_uses_published_dimensions():
    hardware = model.load_json("hardware.json")
    for name in ("SR431", "SR311"):
        shape = model.servo_shape(name, hardware)
        pub = hardware["servos"][name]["published"]
        assert (shape.length, shape.width, shape.height) == (pub["length_mm"], pub["width_mm"], pub["height_mm"])
        box = np.asarray(shape.case.bounding_box()).reshape(2, 3)
        assert box[1] - box[0] == pytest.approx([pub["length_mm"], pub["width_mm"], pub["height_mm"]])
        assert shape.mass_g == pub["mass_g"]


def test_hardware_config_marks_every_assumption():
    hardware = model.load_json("hardware.json")
    for group in ("servos",):
        for spec in hardware[group].values():
            assert spec["source"].startswith("https://")
            for entry in spec["assumed"].values():
                assert entry["why"]
    for name in ("board", "shield", "print", "driver", "head_servo", "pixy"):
        for entry in hardware[name]["assumed"].values():
            assert entry["why"]
    for name in ("head_servo", "pixy"):
        assert hardware[name]["source"].startswith("https://")
    for name, spec in hardware["controllers"].items():
        if name.startswith("_"):
            continue
        assert spec["source"].startswith("https://")
        for entry in spec["assumed"].values():
            assert entry["why"]


def test_fk_rotates_about_the_named_axis():
    robot = model.build_robot(load_meshes=False)
    base = robot.fk()
    rolled = robot.fk({"left_hip_roll": 30.0})
    assert rolled["left_hip"][:3, 3] == pytest.approx(base["left_hip"][:3, 3])
    assert rolled["left_hip"][:3, 0] == pytest.approx([1, 0, 0])
    # +30 degrees about +x carries a point below the hip towards +y (left)
    below = rolled["left_hip"] @ [0, 0, -100, 1]
    assert below[1] > base["left_hip"][1, 3] + 40
    pitched = robot.fk({"left_hip_pitch": 30.0})
    foot = pitched["left_thigh"] @ [0, 0, -100, 1]
    assert foot[0] < base["left_thigh"][0, 3] - 40, "positive hip pitch carries the foot backward"


@needs_stls
def test_neutral_interference_is_reproducible(robot_with_meshes, selected):
    found = assembly.interferences(robot_with_meshes.placed(), robot_with_meshes.assumptions["interference_threshold_mm3"])
    assert [(f["a"], f["b"]) for f in found] == [(f["a"], f["b"]) for f in selected["neutral_interferences"]]
    for now, then in zip(found, selected["neutral_interferences"]):
        assert now["volume_mm3"] == pytest.approx(then["volume_mm3"], rel=1e-3)


@needs_stls
def test_mass_and_balance_are_reproducible(robot_with_meshes, selected):
    total, com = assembly.centre_of_mass(robot_with_meshes)
    assert total == pytest.approx(selected["mass"]["total_g"], abs=0.1)
    assert com == pytest.approx(selected["mass"]["com_neutral_mm"], abs=0.05)
    stand = selected["balance"]["stand_pose"]
    again = assembly.support(robot_with_meshes, stand["q_deg"], ("left", "right"))
    assert again["margin_mm"] == pytest.approx(stand["margin_mm"], abs=0.05)


@needs_stls
def test_one_sweep_is_reproducible(robot_with_meshes, selected):
    cfg = robot_with_meshes.assumptions
    ignore = {frozenset((f["a"], f["b"])) for f in selected["neutral_interferences"]}
    sweep = assembly.sweep_joint(robot_with_meshes, "left_knee", cfg["sweep_step_deg"], cfg["interference_threshold_mm3"], ignore)
    assert sweep["collision_free_deg"] == pytest.approx(selected["sweeps"]["left_knee"]["collision_free_deg"], abs=0.3)
