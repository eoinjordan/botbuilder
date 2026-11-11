# SPDX-License-Identifier: MIT
"""The camera board and its mount at the front edge of the deck."""
import json

import numpy as np
import pytest

from conftest import ROOT, needs_stls
from microduck import model


def test_every_camera_preset_has_a_source_and_marks_its_assumptions():
    hardware = model.load_json("hardware.json")
    assert set(hardware["cameras"]) == set(model.CAMERAS)
    for name in model.CAMERAS:
        spec = hardware["cameras"][name]
        assert spec["source"].startswith("https://")
        for entry in spec["assumed"].values():
            assert entry["why"]
        for entry in spec.get("third_party", {}).values():
            assert entry["source"].startswith("https://")
        shape = model.camera_spec(name, hardware)
        assert 15 < shape["width"] < shape["length"] < 70
        assert 0 < shape["lens_v"] < shape["length"]
    assert model.CAMERA in model.CAMERAS
    assert model.PART_FILES["torso"] == f"01_torso_unoq_cam_{model.CAMERA}.stl"


def test_published_camera_figures_are_used_as_published():
    hardware = model.load_json("hardware.json")
    cam = model.camera_spec("esp32cam", hardware)
    assert (cam["width"], cam["length"], cam["mass_g"]) == (27.0, 40.5, 10.0)
    s3 = model.camera_spec("esp32_s3_eye", hardware)
    assert (s3["width"], s3["length"]) == (30.0, 60.0)
    # Espressif publishes no outline or mass for the ESP-EYE: both stay assumed.
    assert {"length_mm", "width_mm", "mass_g"} <= set(hardware["cameras"]["esp_eye"]["assumed"])


def test_camera_looks_the_way_the_toes_point(selected):
    cam = selected["camera"]
    assert cam["looks_the_way_the_toes_point"]
    assert cam["looks_along"][0] > 0.9 and cam["looks_along"][1] == 0
    assert cam["toes_ahead_of_shin_mm"] > cam["heel_behind_shin_mm"]
    # Ahead of the controller board, which ends at x = +34.29.
    assert cam["lens_mm"][0] > 34.29


def test_camera_fits_its_mount_and_clears_the_stack(selected):
    cam = selected["camera"]
    assert cam["clearance_each_side_mm"] == pytest.approx(0.5, abs=0.02)
    assert cam["play_towards_the_lips_mm"] == pytest.approx(0.3, abs=0.03)
    assert cam["play_towards_the_ledges_mm"] <= 0.02
    assert 0.5 < cam["play_upwards_to_the_catch_mm"] < 2.0
    assert cam["seated_on_the_corner_seats"]
    assert cam["board_overlap_with_mount_mm3"] < 0.5
    for name in ("unoq", "braccio_shield", "stack_envelope"):
        assert cam["gaps"][name]["to_mount_mm"] >= 0.5, name
        assert cam["gaps"][name]["to_camera_board_mm"] >= 0.5, name


def test_view_cone_is_clear_where_the_report_says(selected):
    cam = selected["camera"]
    assert cam["cone_half_angle_deg"] >= 39.3      # 66.5 degrees horizontal on a 4:3 sensor reaches this at the corner
    assert cam["cone_blocked_at_neutral"] == [] and cam["cone_blocked_at_stand"] == []
    stand = selected["balance"]["stand_pose"]["q_deg"]
    for joint, sweep in cam["cone_sweeps"].items():
        span = sweep["from_stand"]["angles_in_cone_deg"]
        if span:
            assert not span[0] <= stand[joint] <= span[1], joint


def test_no_interference_involves_the_camera_or_the_controller(selected):
    names = {n for f in selected["neutral_interferences"] for n in (f["a"], f["b"])}
    assert not names & {"camera_board", "unoq", "braccio_shield"}
    assert selected["neutral_interferences"] == []


def test_camera_mass_is_in_the_total(selected):
    mass = selected["mass"]
    assert mass["by_kind_g"]["camera"] == selected["camera"]["mass_g"]


@needs_stls
def test_model_and_generator_agree_on_where_the_camera_is(robot_with_meshes):
    with open(model.stl_dir() / "parameters.json", encoding="utf-8") as handle:
        generated = json.load(handle)
    assert generated["camera_default"] == model.CAMERA
    made = generated["cameras"][model.CAMERA]
    pose, spec = robot_with_meshes.camera["pose"], robot_with_meshes.camera["spec"]
    assert np.allclose(pose["origin"], made["board_origin"], atol=1e-3)
    assert np.allclose(pose["lens"], made["lens"], atol=1e-3)
    assert np.allclose(pose["forward"], made["forward"], atol=1e-5)
    assert (spec["width"], spec["length"], spec["thickness"], spec["mass_g"]) == (
        made["width"], made["length"], made["thickness"], made["mass_g"])
    assert robot_with_meshes.camera["cone_half_angle_deg"] == made["cone_half_angle_deg"]
    hardware = model.load_json("hardware.json")
    for name in model.CAMERAS:
        other = model.camera_spec(name, hardware)
        assert (other["width"], other["length"]) == (generated["cameras"][name]["width"], generated["cameras"][name]["length"]), name
