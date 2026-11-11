# SPDX-License-Identifier: MIT
"""The default head: round display as the eyes, camera above or below."""
import json

import pytest

from conftest import ROOT, needs_stls
from microduck import model


@pytest.fixture(scope="module")
def faces(assembly_report):
    return assembly_report["faces"]


def test_default_face_is_the_one_analysed(assembly_report, selected):
    assert model.FACE == "eyes_above" and model.CAMERA == "esp_eye"
    assert assembly_report["face_default"] == "eyes_above_esp_eye"
    default = assembly_report["faces"]["eyes_above_esp_eye"]
    assert default["total_g"] == pytest.approx(selected["mass"]["total_g"], abs=0.2)
    assert default["stand_margin_mm"] == pytest.approx(selected["balance"]["stand_pose"]["margin_mm"], abs=0.05)
    kinds = selected["mass"]["by_kind_g"]
    assert kinds["display"] == 15.0 and kinds["battery"] == 8.5 and kinds["camera"] == 8.0


def test_display_and_camera_fit_and_nothing_interferes(faces):
    assert set(faces) == {"eyes_above_esp_eye", "eyes_below_esp_eye", "eyes_above_esp32cam", "eyes_below_esp32cam"}
    for name, face in faces.items():
        assert face["neutral_interferences"] == [], name
        assert face["display_overlap_with_print_mm3"] < 0.5, name
        assert face["camera_overlap_with_print_mm3"] < 0.5, name
        assert face["camera_clearance_each_side_mm"] == pytest.approx(0.5, abs=0.02), name
        assert face["cone_blocked_at_neutral"] == [] and face["cone_blocked_at_stand"] == [], name
        assert face["stand_margin_mm"] > 35.0, name


def test_camera_above_sees_past_the_legs_for_longer(faces):
    for camera in ("esp_eye", "esp32cam"):
        assert faces[f"eyes_above_{camera}"]["lens_mm"][2] > faces[f"eyes_below_{camera}"]["lens_mm"][2] + 40
    above, below = faces["eyes_above_esp_eye"], faces["eyes_below_esp_eye"]
    # Connector up keeps the ESP-EYE head as low as the ESP32-CAM head.
    assert above["highest_point_above_deck_mm"] < faces["eyes_above_esp32cam"]["highest_point_above_deck_mm"] + 2.0
    # Thigh angle (negative is forward) at which a leg enters the clear cone.
    assert above["hip_pitch_in_cone_from_stand_deg"][1] < below["hip_pitch_in_cone_from_stand_deg"][1]
    assert above["lens_mm"][0] > 34.29 and above["display_centre_mm"][0] > 34.29


def test_assumptions_about_the_display_are_marked():
    hardware = model.load_json("hardware.json")
    for name in ("round_display", "battery"):
        assert hardware[name]["source"].startswith("https://")
        for entry in hardware[name]["assumed"].values():
            assert entry["why"]
    assert {"glass_diameter_mm", "rim_thickness_mm", "mass_g"} <= set(hardware["round_display"]["assumed"])


def test_manifest_tags_every_torso_and_cradle():
    with open(model.stl_dir() / "manifest.json", encoding="utf-8") as handle:
        manifest = json.load(handle)
    torsos = [e for e in manifest["files"] if e["options"].get("part") == "torso"]
    assert len(torsos) == 15
    for entry in torsos:
        assert {"controller", "head", "face", "camera"} <= set(entry["options"]), entry["file"]
    default = [e for e in torsos if e["options"] == {"part": "torso", "controller": "unoq", "head": "fixed", "face": "eyes_above",
                                                      "display": "round_display", "camera": "esp_eye"}]
    assert [e["file"] for e in default] == [model.PART_FILES["torso"]]
    cradles = [e for e in manifest["files"] if e["options"].get("part") == "head_cradle"]
    assert len(cradles) == 8 and all({"head", "face", "camera"} <= set(e["options"]) for e in cradles)
    assert manifest["face_default"] == "eyes_above" and manifest["controller_default"] == "unoq"
    keys = [json.dumps(e["options"], sort_keys=True) for e in torsos + cradles]
    assert len(keys) == len(set(keys)), "no two torsos or cradles may carry the same options"


def test_documents_say_which_way_things_face():
    text = (ROOT / "docs" / "camera.md").read_text(encoding="utf-8")
    for phrase in ("out of the back", "two microcontrollers", "GC9A01", "No firmware"):
        assert phrase in text, phrase


@needs_stls
def test_generator_record_matches_the_model(robot_with_meshes):
    made = model.design_parameters()["faces"]["eyes_above_esp_eye"]
    assert made["torso"] == model.PART_FILES["torso"]
    names = {solid.name for _, solid in robot_with_meshes.solids()}
    assert {"round_display", "battery", "camera_board"} <= names
