# SPDX-License-Identifier: MIT
"""The Microduck-look build: its parts and their terms, the assembly test,
the model, the simulation report and the recipe that offers it."""
import json

import pytest
import trimesh

from conftest import ROOT
from microduck.look import analyse, describe, install, model, sim

FOLDER = ROOT / "stl" / "microduck-look"
LINE = "Microduck-look parts: CC BY-NC-SA 4.0, adapted from Pollen Robotics' Microduck; not for commercial use"
CREDIT = "Adapted from the Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl"

pytestmark = pytest.mark.skipif(not model.have_parts(), reason="stl/microduck-look is not there")


def load(*parts):
    return json.loads(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def robot():
    return model.Robot()


@pytest.fixture(scope="module")
def report():
    return load("reports", "microduck-look", "assembly.json")


def test_parts_are_listed_and_carry_their_own_terms():
    listed = [f for f in load("stl", "manifest.json")["files"] if f["file"].startswith("microduck-look/")]
    on_disk = {"microduck-look/" + p.name for p in FOLDER.glob("*.stl")}
    assert {f["file"] for f in listed} == on_disk and len(on_disk) == 28
    for f in listed:
        assert f["options"]["style"] == "microduck" and f["options"]["locomotion"] == "biped_look", f["file"]
        assert f["licence"] == "CC-BY-NC-SA-4.0" and f["watertight"] and len(f["design_commit"]) == 40, f["file"]
        assert f["thumbnail"]["file"].startswith("thumbs/microduck-look/")
    licence = (FOLDER / "LICENSE").read_text(encoding="utf-8")
    assert "Attribution-NonCommercial-ShareAlike 4.0 International" in licence and "CC-BY-NC-SA-4.0" in licence
    assert " ".join(CREDIT.split()) in " ".join(licence.split()) and "What was changed" in licence
    notice = " ".join((ROOT / "NOTICE").read_text(encoding="utf-8").split())
    assert CREDIT in notice and "CC BY-NC-SA 4.0" in notice and "not under the MIT licence" in notice
    assert "CC BY-NC-SA 4.0" in model.parameters()["_licence"]
    assert install.LICENCE_LINE == LINE


def test_the_source_meshes_are_not_here():
    for path in FOLDER.rglob("*"):
        assert not (path.name[:2].isdigit() and path.name[2:3] == "_"), path.name
    assert sum(p.stat().st_size for p in FOLDER.rglob("*") if p.is_file()) < 2_400_000


def test_every_part_is_one_closed_solid():
    for part in model.parameters()["parts"]:
        mesh = trimesh.load_mesh(FOLDER / part["file"])
        assert mesh.is_volume, part["file"]
        assert len(model.from_trimesh(mesh).decompose()) == 1, part["file"]
        assert abs(mesh.bounds[0][2]) < 1e-3, f"{part['file']} rests on the bed"


def test_fifteen_joints_with_the_originals_names_and_ranges(robot):
    assert list(robot.joints) == model.JOINTS and len(model.JOINTS) == 15
    assert robot.joints["left_hip_yaw"].original_range == (-25, 30) and robot.joints["right_hip_yaw"].original_range == (-30, 25)
    assert robot.joints["head_yaw"].original_range == (-170, 170) and robot.joints["left_knee"].original_range == (-90, 90)
    kinds = [robot.joints[j].servo for j in model.JOINTS]
    assert (kinds.count("SR431"), kinds.count("SR311"), kinds.count("M5_180")) == (8, 4, 3), "two Braccio kits and three small servos"
    for joint in ("hip_roll", "hip_pitch", "knee", "ankle"):
        assert robot.joints[f"left_{joint}"].servo == "SR431"


def test_nothing_overlaps_at_the_zero_and_stand_poses(robot, report):
    assert analyse.interferences(robot) == [] == report["interferences"]["zero_pose"]
    assert analyse.interferences(robot, report["stand_pose"]["q_deg"]) == [] == report["interferences"]["stand_pose"]


def test_it_balances_on_two_feet_and_on_each_foot(robot, report):
    stand = report["stand_pose"]["q_deg"]
    two = analyse.support(robot, analyse.in_stance_frame(robot, stand, "left"))
    assert two["margin_mm"] == report["stand_pose"]["margin_mm"] > 15.0
    assert abs(two["mass_kg"] - report["mass"]["total_kg"]) < 1e-3
    for side in ("left", "right"):
        foot = report["one_foot"][side]
        assert foot["found"] and foot["margin_mm"] >= analyse.ONE_FOOT_MARGIN and foot["interferences"] == []
        assert abs(foot["roll_deg"]) <= 22.0, "inside the original's hip roll range"
        again = analyse.support(robot, analyse.in_stance_frame(robot, foot["q_deg"], side), (side,))
        assert again["margin_mm"] == foot["margin_mm"]


def test_holding_torques_and_ranges(report):
    for joint, row in report["torque"].items():
        assert row["required_over_stall"] < 0.6, joint
        if joint != "neck_pitch":
            assert row["required_over_hold_limit"] <= 1.0, joint
    ranges = report["joint_ranges"]
    for joint in ("left_hip_pitch", "left_knee", "left_ankle", "right_hip_pitch", "right_knee", "right_ankle"):
        assert ranges[joint]["max_deg"] - ranges[joint]["min_deg"] >= 120.0, joint
    assert (ranges["head_roll"]["min_deg"], ranges["head_roll"]["max_deg"]) == (-25.0, 25.0)
    built = report["assignments"]["two kits, built"]
    assert built["over_stall"] == [] and built["one_foot"] == {"left": True, "right": True}
    assert report["assignments"]["one kit, lightest"]["over_hold_limit"], "small servos cannot hold the hips"


def test_description_matches_the_parts(robot, report):
    table = load("robot", "microduck-look", "joints.json")
    assert table == describe.joint_table(robot, report)
    assert (ROOT / "robot" / "microduck-look" / "microduck_look.xml").read_text(encoding="utf-8") == describe.mjcf(robot, table)
    assert (ROOT / "robot" / "microduck-look" / "microduck_look.urdf").read_text(encoding="utf-8") == describe.urdf(robot, table)
    boards = [table["joints"][j]["driven_by"] for j in model.JOINTS]
    assert boards.count("board 1") == boards.count("board 2") == 6 and boards.count("driver") == 3
    for board in ("board 1", "board 2"):
        pins = sorted(table["joints"][j]["pin"] for j in model.JOINTS if table["joints"][j]["driven_by"] == board)
        assert pins == [3, 5, 6, 9, 10, 11], "the six outputs of a Braccio shield"


def test_the_model_stands():
    s = sim.LookSim()
    assert abs(float(s.model.body_mass.sum()) - load("reports", "microduck-look", "assembly.json")["mass"]["total_kg"]) < 1e-3
    log = sim.run(s, [(t, s.stand) for t in range(0, 4001, sim.TICK_MS)])
    assert log["fell_at"] is None and log["tilt"].max() < 3.0
    assert log["force_left"][-1] > 3.0 and log["force_right"][-1] > 3.0


def test_simulation_report_and_page(report):
    study = load("reports", "microduck-look", "sim.json")
    assert not study["stand"]["fell"] and not study["head_motion_while_standing"]["fell"]
    assert study["walk"]["search"]["candidates"] > 0 and "truly_steps" in study["walk"]
    assert load("config", "microduck-look", "gait.json")["period_s"] == study["walk"]["params"]["period_s"]
    page = (ROOT / "docs" / "microduck-look.md").read_text(encoding="utf-8")
    assert LINE in page and "M5Stack Servo Kit 180" in page and "Firmware for this build is not written" in page
    assert f"| mass (kg) | {report['mass']['total_kg']} |" in page
    assert f"{report['dimensions']['height_stand_mm']} at the stand pose" in page
    assert f"{study['walk']['speed_mm_s']} mm/s forward" in page
    for name in report["pictures"].values():
        assert (ROOT / name).is_file() and name.split("/")[-1] in page or "back" in name or "one-foot" in name
