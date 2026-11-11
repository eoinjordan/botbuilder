# SPDX-License-Identifier: MIT
"""Pin holes and studs compatible with LEGO Technic and System elements."""
import numpy as np
import pytest
import trimesh

from conftest import ROOT, needs_stls
from microduck import assembly, model


def test_every_hole_is_open_walled_and_a_beam_long(selected):
    lego = selected["lego_compatible"]
    assert len(lego["holes"]) == 23 and len(lego["studs"]) == 40
    for hole in lego["holes"]:
        assert hole["open_for_a_nominal_pin"], hole
        assert hole["wall_fill_fraction"] > 0.99, hole
        assert hole["length_mm"] == pytest.approx(lego["nominal_mm"]["beam"], abs=0.01)
        assert hole["from_nearest_joint_axis_mm"] >= 20.0, hole
        assert hole["gap_to_it_mm"] >= 2.0, hole
    for stud in lego["studs"]:
        assert stud["present"] and stud["points_up_at_neutral"], stud
        assert stud["gap_to_it_mm"] >= 2.0, stud
    assert lego["features_in_the_camera_cone_at_neutral"] == 0


def test_nominal_dimensions_and_allowances(selected):
    lego = selected["lego_compatible"]
    assert lego["nominal_mm"] == {"pitch": 8.0, "pin_hole": 4.8, "pin_counterbore": [6.2, 0.8], "beam": 7.8, "stud": [4.8, 1.7]}
    assert 0 < lego["print_allowance_mm"]["hole_extra"] <= 0.4
    assert 0 <= lego["print_allowance_mm"]["stud_under"] <= 0.2


def test_features_did_not_cost_any_joint_range(selected):
    sweeps = selected["sweeps"]
    assert sweeps["left_hip_roll"]["collision_free_deg"] == [-55.0, 180.0]
    assert sweeps["left_hip_pitch"]["collision_free_deg"] == [-180.0, 180.0]
    assert sweeps["left_knee"]["collision_free_deg"] == pytest.approx([-137.25, 115.25], abs=0.5)
    assert selected["neutral_interferences"] == []


def test_decoration_budget_is_consistent(selected):
    rows = {row["where"]: row for row in selected["decoration_budget"]}
    assert len(rows) == 6
    base = selected["balance"]["stand_pose"]["margin_mm"]
    for row in rows.values():
        assert row["margin_with_50_g_mm"] < base
        assert row["margin_with_200_g_mm"] < row["margin_with_100_g_mm"] < row["margin_with_50_g_mm"]
        limit = row["mass_that_uses_up_the_margin_g"]
        assert limit is None or limit > 200
    rear = rows["on the rear pin holes of the deck"]["mass_that_uses_up_the_margin_g"]
    assert rear is not None and 300 < rear < 500


def test_trademark_notice_is_where_the_feature_is_described():
    text = (ROOT / "docs" / "assembly.md").read_text(encoding="utf-8")
    assert "compatible with LEGO Technic and System elements" in text
    assert "trademarks of the LEGO Group, which does not sponsor or endorse this" in text.replace("\n", " ")


@needs_stls
def test_coupon_is_one_solid_with_six_holes_and_six_studs():
    mesh = trimesh.load_mesh(model.stl_dir() / model.FIT_FILES["lego_compatible_coupon"])
    assert mesh.is_volume and len(mesh.split()) == 1
    size = mesh.bounds[1] - mesh.bounds[0]
    assert size == pytest.approx([96.0, 8.0, 9.5], abs=0.2)
    bar = 96.0 * 8.0 * 7.8
    assert 0.6 * bar < mesh.volume < bar


@needs_stls
def test_checks_are_reproducible(robot_with_meshes, selected):
    now = assembly.lego_checks(robot_with_meshes, model.design_parameters())
    assert now["counts"] == selected["lego_compatible"]["counts"]
    assert all(h["open_for_a_nominal_pin"] for h in now["holes"])
    spec = model.design_parameters()["lego_compatible"]
    for hole in spec["holes"]:
        assert np.linalg.norm(np.subtract(hole["end"], hole["start"])) == pytest.approx(spec["beam"], abs=0.01)
