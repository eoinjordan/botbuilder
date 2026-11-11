# SPDX-License-Identifier: MIT
"""Other controllers on the biped's deck: fit as a block and static balance."""
import pytest
import trimesh

from conftest import needs_stls
from microduck import assembly, model


@pytest.fixture(scope="module")
def controllers(assembly_report):
    return assembly_report["controllers"]


def test_every_controller_in_the_configuration_is_reported(controllers):
    hardware = model.load_json("hardware.json")
    assert set(controllers) == {k for k in hardware["controllers"] if not k.startswith("_")}
    assert {k for k, c in controllers.items() if c["has_its_own_torso"]} == set(model.CONTROLLER_TORSOS)
    assert controllers["ev3"]["has_its_own_torso"] is False


def test_blocks_clear_the_print_and_the_camera(controllers):
    for name, c in controllers.items():
        assert c["overlap_with_print_mm3"] < 0.5, name
        assert c["overlap_with_camera_board_mm3"] == 0, name
        assert c["gap_to_camera_board_mm"] >= 5.0, name
        assert c["neutral_interferences"] == [], name


def test_mass_and_balance_follow_the_controller(controllers, selected):
    for name, c in controllers.items():
        assert 460.0 < c["total_g"] - c["mass_g"] < 495.0, name      # the robot without a controller, camera-only head
        assert c["stands_statically"] and c["stand_margin_mm"] > 30.0, name
        assert c["neutral_margin_mm"] < 5.0, "with the legs straight no variant has a real margin"
        assert c["hip_pitch_torque_fraction"] < 0.5, name
    order = sorted(controllers.values(), key=lambda c: c["mass_g"])
    swings = [c["stand_thigh_swing_deg"] for c in order]
    assert swings == sorted(swings), "a heavier controller needs the thighs further back"
    assert order[-1]["controller"] == "ev3"


def test_published_outlines_are_used(controllers):
    hardware = model.load_json("hardware.json")
    assert hardware["controllers"]["pi_zero_2w"]["published"]["hole_pattern_mm"] == [58.0, 23.0]
    assert hardware["controllers"]["hub51515"]["published"]["mass_without_battery_g"] == 63.0
    lo, hi = controllers["hub51515"]["block_mm"]
    assert [round(hi[i] - lo[i], 1) for i in range(3)] == [56.0, 88.0, 32.0]
    assert "mass_g" in hardware["controllers"]["ev3"]["assumed"]


@needs_stls
def test_controller_torsos_are_closed_solids_with_the_generator_record():
    made = model.design_parameters()
    assert made["controller_default"] == "unoq"
    for name in model.CONTROLLER_TORSOS:
        file = made["controllers"][name]["torso"]
        mesh = trimesh.load_mesh(model.stl_dir() / file)
        assert mesh.is_volume and len(mesh.split()) == 1, file


@needs_stls
def test_summary_is_reproducible(controllers, selected):
    config = model.load_json("assembly.json")
    robot = model.build_robot(assembly=dict(config, controller="hub51515"))
    again = assembly.controller_summary(robot, selected["joint_limits_deg"])
    assert again["stand_margin_mm"] == pytest.approx(controllers["hub51515"]["stand_margin_mm"], abs=0.05)
    assert again["total_g"] == pytest.approx(controllers["hub51515"]["total_g"], abs=0.1)
