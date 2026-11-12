# SPDX-License-Identifier: MIT
"""The Microduck-look build: its parts and their terms, the assembly test,
the model, the simulation report and the recipe that offers it."""
import json

import pytest
import trimesh

from conftest import ROOT
from microduck.look import analyse, combfeet, describe, install, model, sim

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
    assert {f["file"] for f in listed} == on_disk and len(on_disk) == 30
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
    # the model is named plainly, and the comb feet are under the same terms
    source = "Microduck by Pollen Robotics, https://github.com/pollen-robotics/microduck_rl"
    assert install.SOURCE_MODEL == source and load("stl", "microduck-look", "manifest.json")["source_model"] == source
    assert install.COMB_LICENCE in licence and "left_foot_comb.stl" in notice
    for name in ("README.md", "docs/microduck-look.md", "site/credits.html", "site/biped.html"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "Microduck by Pollen Robotics" in text and "github.com/pollen-robotics/microduck_rl" in text and "CC BY-NC-SA 4.0" in text, name
    assert "CC BY-NC-SA 4.0" in combfeet.record()["_licence"]
    for f in listed:
        if f["file"].endswith("_foot_comb.stl"):
            assert f["options"]["feet"] == "comb" and f["made_from"] == f["file"].replace("_comb", "")


def test_the_source_meshes_are_not_here():
    for path in FOLDER.rglob("*"):
        assert not (path.name[:2].isdigit() and path.name[2:3] == "_"), path.name
    assert sum(p.stat().st_size for p in FOLDER.rglob("*") if p.is_file()) < 2_600_000


def test_every_part_is_one_closed_solid():
    for part in model.parameters()["parts"] + combfeet.record()["parts"]:
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


def test_the_comb_feet_are_made_from_the_feet_and_interleave(report, tmp_path):
    made = combfeet.record()
    assert [part["file"] for part in made["parts"]] == ["left_foot_comb.stl", "right_foot_comb.stl"]
    # the committed files are what the generator writes from the committed feet
    for name in ("parameters.json", "left_foot.stl", "right_foot.stl"):
        (tmp_path / name).write_bytes((FOLDER / name).read_bytes())
    assert combfeet.build(tmp_path) == made
    for part in made["parts"]:
        assert (tmp_path / part["file"]).read_bytes() == (FOLDER / part["file"]).read_bytes(), part["file"]
    comb = model.Robot(feet="comb")
    feet = {side: next(s for s in comb.links[f"{side}_foot"].solids if s.kind == "shell") for side in ("left", "right")}
    assert (feet["left"].solid ^ feet["right"].solid).volume() == 0.0
    assert 3.5 < feet["left"].solid.min_gap(feet["right"].solid, 30.0) <= made["comb"]["clear_tip"] + 1e-3
    reach = made["comb"]["tip_past_centre"]
    assert abs(feet["left"].solid.bounding_box()[1] + reach) < 1e-3 and abs(feet["right"].solid.bounding_box()[4] - reach) < 1e-3
    # either foot alone is under the centre of mass with the hips level
    study = report["comb_feet"]
    assert study["interferences"] == {"zero_pose": [], "stand_pose": []}
    stand = report["stand_pose"]["q_deg"]
    for side in ("left", "right"):
        foot = study["one_foot"][side]
        assert foot["found"] and foot["roll_deg"] == 0.0 and foot["margin_mm"] >= analyse.ONE_FOOT_MARGIN and foot["interferences"] == []
        again = analyse.support(comb, analyse.in_stance_frame(comb, foot["q_deg"], side), (side,))
        assert again["margin_mm"] == foot["margin_mm"] > report["one_foot"][side]["margin_mm"]
    assert study["stand_pose"]["q_deg"] == stand
    # what the fingers cost: one hip alone
    assert study["joint_ranges"]["left_hip_yaw"]["max_free_deg"] < report["joint_ranges"]["left_hip_yaw"]["max_free_deg"]


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
    comb = (ROOT / "robot" / "microduck-look" / "microduck_look_comb.xml").read_text(encoding="utf-8")
    assert comb == describe.mjcf(model.Robot(feet="comb"), table, "microduck_look_comb")
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
    comb = sim.LookSim(feet="comb")
    assert abs(float(comb.model.body_mass.sum()) - load("reports", "microduck-look", "assembly.json")["comb_feet"]["mass"]["total_kg"]) < 1e-3
    log = sim.run(comb, [(t, comb.stand) for t in range(0, 4001, sim.TICK_MS)])
    assert log["fell_at"] is None and log["tilt"].max() < 3.0


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
    # the comb feet: the same study, the gait it found played again, and the numbers on the page
    comb = study["comb_feet"]
    walk = comb["walk"]
    assert not comb["stand"]["fell"] and walk["search"]["seed"] == study["walk"]["search"]["seed"]
    assert (walk["search"]["generations"], walk["search"]["popsize"]) == (study["walk"]["search"]["generations"], study["walk"]["search"]["popsize"])
    assert walk["search_refuses_feet_that_overlap"] and walk["feet_overlap"]["poses_with_overlap"] == 0
    assert load("config", "microduck-look", "gait_comb.json")["period_s"] == walk["params"]["period_s"]
    played = sim.LookSim(feet="comb")
    again = sim.describe_run(played, sim.run(played, sim.gait(played.table, walk["params"], 30.0)), walk["params"], 30.0)
    assert again["speed_mm_s"] == walk["speed_mm_s"] and again["truly_steps"] == walk["truly_steps"] and again["fell"] == walk["fell"]
    assert sim.feet_overlap(model.Robot(feet="comb"), sim.one_cycle(played.table, walk["params"])) == walk["feet_overlap"]
    speeds = load("reports", "microduck-look", "summary.json")["walking_speed_by_feet"]
    assert f"| comb | {'yes' if walk['truly_steps'] else 'no'} | {'yes' if walk['fell'] else 'no'} | {walk['speed_mm_s']} |" in page
    assert f"| as generated, with the web | {'yes' if study['walk']['truly_steps'] else 'no'} | {'yes' if study['walk']['fell'] else 'no'} | {study['walk']['speed_mm_s']} |" in page
    faster = max(("flat", "comb"), key=lambda option: speeds[option]["speed_mm_s"])
    assert speeds["faster"] == faster
