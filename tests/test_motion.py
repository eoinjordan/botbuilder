# SPDX-License-Identifier: MIT
"""The motion study: the servo and command-path model, the presets, the
search, every trajectory against the firmware's limits, and the headline
numbers of reports/motion.json rerun with tolerances."""
import json
from dataclasses import replace

import numpy as np
import pytest

from conftest import ROOT, needs_stls
from microduck import cmaes, gait, gaitsearch, motions, motionsim, protocol, variant
from microduck import motion_experiments as mx
from microduck.protocol import JOINTS


@pytest.fixture(scope="module")
def report():
    with open(ROOT / "reports" / "motion.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def manifest():
    with open(ROOT / "trajectories" / "manifest.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def gaits():
    return mx.load_gaits()


@pytest.fixture(scope="module")
def duck():
    return motionsim.MotionSim("drawn")


# --- the model ---------------------------------------------------------------

def test_every_physics_parameter_is_stated_with_a_reason():
    config = variant.load_json("motion.json")
    for name, item in {**config["physics"], **config["firmware"]}.items():
        assert "value" in item and len(item["why"]) > 20, name
    for needed in ("transport_delay_ms", "pwm_latency_ms", "deadband_deg", "backlash_deg", "flex_nm_per_rad",
                   "supply_current_a", "floor_friction"):
        assert needed in config["physics"]


def test_servo_limits_are_the_published_ones(duck, joints):
    for i, name in enumerate(JOINTS):
        assert duck.limits[i] == pytest.approx(joints["joints"][name]["torque_limit_nm"], rel=1e-3)
        assert np.degrees(duck.speed_limits[i]) == pytest.approx(joints["joints"][name]["speed_limit_deg_s"], rel=5e-3)
    assert duck.supply_a == 4.0


def test_the_drawn_preset_keeps_the_real_mass(duck, joints):
    assert duck.mass == pytest.approx(joints["mass_kg"], abs=0.002)
    assert variant.preset_overrides("drawn") == {}


def test_head_mass_is_a_parameter(duck):
    heavier = motionsim.MotionSim("drawn", head={"extra_mass_g": 30.0, "position_mm": [20.0, 0.0, 80.0]})
    assert heavier.mass == pytest.approx(duck.mass + 0.030, abs=1e-4)
    duck.reset()
    assert heavier.com()[2] > duck.com()[2]


def test_a_command_reaches_the_servo_after_the_delays(duck):
    """Transport delay, then the controller tick, then one PWM frame."""
    duck.reset()
    target = list(duck.cal.stand_deg)
    target[0] += 10.0
    before = duck.target.copy()
    duck.send(protocol.format_joints(target))
    duck.tick()
    assert np.allclose(duck.target, before)             # 20 ms: still in transit
    duck.tick()
    assert np.allclose(duck.target, before)             # 40 ms: set by the controller, not yet in a frame
    duck.tick()
    assert duck.target[0] > before[0]                   # 60 ms: the servo acts on it
    step = duck.cal.max_speed_deg_s * 0.02
    assert np.degrees(duck.target[0] - before[0]) == pytest.approx(step, abs=0.1)   # one rate-limited step, rounded to 1 us


def test_no_torque_inside_the_dead_zone(duck):
    phys = duck.phys
    assert np.degrees(duck.dead) == pytest.approx(phys["deadband_deg"] + 0.5 * phys["backlash_deg"])
    duck.reset()
    duck.data.qpos[2] = 1.0                             # in the air: no load on the joints
    duck.model.opt.gravity[:] = 0.0
    duck.target = duck.data.qpos[duck.qadr].copy() + 0.8 * duck.dead
    duck.frame = duck.target.copy()
    duck.controller.mode = protocol.HOLD
    saved = duck.controller.servo_deg
    duck.controller.servo_deg = lambda: duck.cal.servo_deg(np.degrees(duck.frame))
    try:
        duck.tick()
        assert np.abs(duck.data.actuator_force).max() == 0.0
    finally:
        duck.controller.servo_deg = saved
        duck.model.opt.gravity[:] = [0.0, 0.0, -9.81]


def test_torque_never_exceeds_stall_and_current_is_limited(duck):
    duck.reset()
    far = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    cal = replace(duck.cal, max_speed_deg_s=430.0)
    fast = motionsim.MotionSim("drawn", cal=cal)
    log = motionsim.run(fast, [(t, far if t > 200 else list(cal.stand_deg)) for t in range(0, 800, 20)])
    assert (np.abs(log["torque"]) <= fast.limits + 1e-9).all()
    assert log["current"].max() > fast.supply_a         # the move asks for more than the supply has
    assert log["current_limited_fraction"] > 0.0
    assert (np.abs(log["speed"]) <= np.degrees(fast.speed_limits) * 1.25).all()


def test_stands_with_the_fuller_servo_model(duck):
    duck.reset()
    log = motionsim.run(duck, gait.stand(duck.cal.stand_deg, 5.0))
    assert log["fell_at"] is None
    assert log["tilt"].max() < 3.0
    assert set(log["contact_kinds"]) == {"sole"}
    assert np.abs(log["joint"][-1] - np.array(duck.cal.stand_deg)).max() < 3.0


def test_variant_changes_only_the_soles(duck):
    comb = motionsim.MotionSim("comb_feet")
    assert set(variant.preset_overrides("comb_feet")) == {"foot"}
    assert comb.cal.stand_deg == duck.cal.stand_deg
    assert [(j.min_deg, j.max_deg) for j in comb.cal.joints] == [(j.min_deg, j.max_deg) for j in duck.cal.joints]
    assert abs(comb.mass - duck.mass) < 0.02
    for name in ("torso", "left_hip", "left_thigh"):
        a, b = duck.model.body(name), comb.model.body(name)
        assert np.allclose(a.mass, b.mass) and np.allclose(a.ipos, b.ipos)
    presets = variant.load_presets()
    assert "published geometry" in presets["drawn"]["description"]
    for name, preset in presets.items():
        if name != "drawn":
            assert preset["description"].startswith(("Variant", "Rejected")) and "Simulation only" in preset["description"]


def test_comb_soles_do_not_overlap_and_cross_the_centreline():
    comb = motionsim.MotionSim("comb_feet")
    comb.reset()
    m, d = comb.model, comb.data
    boxes = {side: [(d.geom_xpos[g][:2] - m.geom_size[g][:2], d.geom_xpos[g][:2] + m.geom_size[g][:2]) for g in ids]
             for side, ids in comb.feet.items()}
    for lo_a, hi_a in boxes["left"]:
        for lo_b, hi_b in boxes["right"]:
            assert (hi_a < lo_b + 0.004).any() or (hi_b < lo_a + 0.004).any(), "soles closer than 4 mm"
    assert min(lo[1] for lo, _ in boxes["left"]) < -0.02     # the left sole reaches past the centreline
    assert max(hi[1] for _, hi in boxes["right"]) > 0.02


# --- the search --------------------------------------------------------------

def test_cmaes_finds_a_known_optimum_and_is_seeded():
    target = np.array([0.2, 0.7, 0.5, 0.9])
    f = lambda xs: [-float(np.sum((np.array(x) - target) ** 2)) for x in xs]     # noqa: E731
    a = cmaes.maximise(f, 4, seed=3, popsize=12, generations=60)
    b = cmaes.maximise(f, 4, seed=3, popsize=12, generations=60)
    assert a["x"] == b["x"]
    assert np.abs(np.array(a["x"]) - target).max() < 0.01
    assert a["evaluations"] == 12 * 60


def test_searched_motions_record_their_seed_and_budget(gaits):
    for preset in mx.PRESETS:
        for motion in ("walk", "jump"):
            search = gaits[preset][motion]["search"]
            assert search["seed"] >= 0 and search["generations"] > 0 and search["wall_clock_s"] <= search["wall_clock_budget_s"] + 60
            assert search["simulated_runs"] == search["candidates"] * len(gaitsearch.SCENARIOS)
    assert gaits["search"]["total_simulated_runs"] > 1000


def test_gait_generators_respect_the_rate_limit(gaits):
    for preset in mx.PRESETS:
        cal = variant.calibration(preset)
        for speed, turn in ((1.0, 0.0), (1.0, 1.0), (0.25, -1.0)):
            trajectory, _ = mx.walk_trajectory(cal, gaits[preset]["walk"], 6.0, speed, turn)
            assert gait.check_limits(trajectory, cal) == []


# --- the files for the robot and the gamepad page ----------------------------

def test_manifest_lists_every_motion_for_both_presets(manifest):
    names = {e["name"] for e in manifest["trajectories"]}
    for preset in mx.PRESETS:
        for motion in ("walk", "turn_left", "turn_right", "jump", "sit", "stand_up"):
            assert f"{preset}_{motion}" in names
    for entry in manifest["trajectories"]:
        for key in ("name", "file", "preset", "duration_s", "what", "limits", "allowed_on_real_hardware_by_default"):
            assert key in entry, (entry["name"], key)
        assert (ROOT / "trajectories" / entry["file"]).is_file()
    assert manifest["joint_order"] == JOINTS
    assert "never been assembled" in manifest["status"]


def test_every_trajectory_passes_the_firmware_limits(manifest):
    """Through microduck/protocol.py: inside the soft limits (no clamped
    command) and never faster than the speed limit the entry states."""
    default = protocol.load_calibration().max_speed_deg_s
    for entry in manifest["trajectories"]:
        trajectory = gait.read_csv(ROOT / "trajectories" / entry["file"])
        cal = variant.calibration(entry["preset"])
        speed = entry["limits"]["max_speed_deg_s"]
        check = mx.check_trajectory(trajectory, cal, speed)
        assert check == {"limit_problems": 0, "clamped_commands": 0, "max_lag_behind_command_deg": pytest.approx(0.0, abs=0.06)}, entry["name"]
        for key, value in check.items():
            assert entry["limits"][key] == value, (entry["name"], key)
        assert entry["duration_s"] == pytest.approx(trajectory[-1][0] / 1000.0)
        assert all(b[0] - a[0] == protocol.TICK_MS for a, b in zip(trajectory, trajectory[1:]))
        if speed > default:
            assert entry["limits"]["needs_speed_limit_raised"] and not entry["allowed_on_real_hardware_by_default"]
        else:
            assert gait.check_limits(trajectory, protocol.load_calibration()) == [] or entry["preset"] != "drawn"


@needs_stls
def test_drawn_trajectories_do_not_drive_parts_into_each_other(manifest):
    """Exact mesh check of sampled poses of every motion of the drawn robot."""
    for entry in manifest["trajectories"]:
        if entry["preset"] != "drawn":
            continue
        result = mx.mesh_check(gait.read_csv(ROOT / "trajectories" / entry["file"]), poses=4)
        assert result["collisions"] == 0, (entry["name"], result["first"])


def test_the_jump_is_not_allowed_on_real_hardware(manifest):
    jumps = [e for e in manifest["trajectories"] if e["name"].endswith("_jump")]
    assert len(jumps) == len(mx.PRESETS)
    for entry in jumps:
        assert entry["allowed_on_real_hardware_by_default"] is False
        assert "strip gears" in entry["note"]


def test_walk_files_loop(manifest):
    for entry in manifest["trajectories"]:
        if "loop" not in entry:
            continue
        rows = dict(gait.read_csv(ROOT / "trajectories" / entry["file"]))
        start, period = entry["loop"]["from_ms"], entry["loop"]["period_ms"]
        assert period % protocol.TICK_MS == 0
        for t in range(start, start + period, 100):
            if t + period in rows:
                assert np.abs(np.array(rows[t]) - np.array(rows[t + period])).max() <= 0.11, (entry["name"], t)


def test_gait_parameter_file_has_the_tested_envelope(report):
    with open(ROOT / "trajectories" / "gait_params.json", encoding="utf-8") as handle:
        doc = json.load(handle)
    for preset in mx.PRESETS:
        item = doc["presets"][preset]
        env = item["tested_envelope"]
        assert item["params"] == report["presets"][preset]["walk"]["gait"]["params"]
        assert env["tested_speed"] == list(mx.ENVELOPE_SPEED) and env["tested_turn"] == list(mx.ENVELOPE_TURN)
        assert len(item["points"]) == len(mx.ENVELOPE_SPEED) * len(mx.ENVELOPE_TURN)
        ok = {(p["speed"], p["turn"]) for p in item["points"] if p["stayed_up_all_frictions"]}
        for key, axis, other in (("speed_range_all_turns", 0, mx.ENVELOPE_TURN), ("turn_range_all_speeds", 1, mx.ENVELOPE_SPEED)):
            if env[key]:
                for value in env[key]:
                    for o in other:
                        assert ((value, o) if axis == 0 else (o, value)) in ok


# --- headline numbers, rerun --------------------------------------------------

@pytest.mark.parametrize("preset", mx.PRESETS)
def test_walk_headline_numbers(preset, report, gaits):
    recorded = report["presets"][preset]["walk"]["nominal"]
    fresh = mx.walk_run(motionsim.MotionSim(preset), gaits[preset]["walk"], mx.WALK_SECONDS)
    assert fresh["fell"] == recorded["fell"]
    assert fresh["speed_mm_s"] == pytest.approx(recorded["speed_mm_s"], rel=0.35, abs=3.0)
    assert fresh["single_support_fraction"] == pytest.approx(recorded["single_support_fraction"], abs=0.12)
    assert fresh["median_clearance_mm"] == pytest.approx(recorded["median_clearance_mm"], rel=0.5, abs=1.5)
    assert mx.truly_steps(fresh) == report["presets"][preset]["walk"]["truly_steps"]


def test_the_variant_steps_and_the_drawn_robot_does_not(report):
    drawn, comb = report["presets"]["drawn"], report["presets"]["comb_feet"]
    assert drawn["one_foot_test"]["stands_on_one_foot"] is False
    assert comb["one_foot_test"]["stands_on_one_foot"] is True
    assert comb["walk"]["truly_steps"] is True
    assert comb["walk"]["nominal"]["median_clearance_mm"] >= 3.0
    assert comb["walk"]["nominal"]["stance_slip_mm_per_step"] < 0.5 * comb["walk"]["nominal"]["step_length_mm"]
    assert comb["walk"]["nominal"]["peak_torque_fraction"] < 1.0
    assert comb["walk"]["long_horizon"]["fell"] is False
    assert comb["walk"]["robustness"]["fell"] == 0
    assert drawn["walk"]["robustness"]["stepping_runs"] < drawn["walk"]["robustness"]["runs"]


@pytest.mark.parametrize("preset", mx.PRESETS)
def test_jump_headline_numbers(preset, report, gaits):
    recorded = report["presets"][preset]["jump"]
    fresh = mx.jump_run(preset, gaits[preset]["jump"]["params"], recorded["max_speed_deg_s"])
    assert fresh["verdict"] == recorded["result"]["verdict"]
    assert fresh["landed_upright"] == recorded["result"]["landed_upright"]
    assert fresh["feet_rise_mm"] == pytest.approx(recorded["result"]["feet_rise_mm"], rel=0.4, abs=1.5)
    assert fresh["flight_s"] == pytest.approx(recorded["result"]["flight_s"], abs=0.04)
    # it is called what it is
    assert fresh["com_rise_in_flight_mm"] == pytest.approx(recorded["result"]["com_rise_in_flight_mm"], rel=0.4, abs=1.5)
    assert mx.jump_verdict({"flight_s": 0.06, "feet_rise_mm": 4.0, "com_rise_in_flight_mm": 3.0}) == "hop"
    assert mx.jump_verdict({"flight_s": 0.10, "feet_rise_mm": 12.0, "com_rise_in_flight_mm": 4.0}) == "hop"
    assert mx.jump_verdict({"flight_s": 0.15, "feet_rise_mm": 15.0, "com_rise_in_flight_mm": 12.0}) == "jump"
    assert mx.jump_verdict({"flight_s": 0.0, "feet_rise_mm": 0.0, "com_rise_in_flight_mm": 0.0}) == "no flight"
    assert recorded["result"]["verdict"] == "hop"
    assert recorded["result"]["com_rise_in_flight_mm"] <= recorded["no_load_bound"]["ballistic_rise_mm"]
    assert recorded["at_default_speed_limit"]["feet_rise_mm"] <= recorded["result"]["feet_rise_mm"]
    for joint, demand in recorded["result"]["demand"].items():
        assert demand["peak_torque_nm"] <= demand["torque_limit_nm"] + 1e-6, joint


@pytest.mark.parametrize("preset", mx.PRESETS)
def test_sit_and_stand_up(preset, report):
    recorded = report["presets"][preset]["sit"]
    fresh = mx.sit_run(preset)
    for key in ("sat_down", "relaxed_rest_stable", "stood_up", "board_or_head_touched", "parts_that_touched_the_floor"):
        assert fresh[key] == recorded[key], key
    assert fresh["sat_down"] and fresh["stood_up"]
    assert fresh["parts_that_touched_the_floor"] == ["sole"]
    assert fresh["torso_lowered_mm"] == pytest.approx(recorded["torso_lowered_mm"], abs=2.0)
    assert fresh["rising_demand"]["peak_torque_fraction"] < 1.0


def test_document_carries_the_warnings(report):
    text = (ROOT / "docs" / "motion.md").read_text(encoding="utf-8")
    assert "simulation only" in text.lower() and "never been assembled" in text
    assert "can strip gears or break parts" in text
    assert "not the owner's design" in text
    spec = (ROOT / "docs" / "generator-changes.md").read_text(encoding="utf-8")
    assert "not the owner's design" in spec and "comb_feet" in spec
    for preset in mx.PRESETS:
        r = report["presets"][preset]
        assert str(r["walk"]["nominal"]["speed_mm_s"]) in text
        assert str(r["jump"]["result"]["feet_rise_mm"]) in text


def test_readme_and_site_carry_the_reported_numbers(report):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    drawn, comb = report["presets"]["drawn"], report["presets"]["comb_feet"]
    for text in (readme, page):
        assert f"{drawn['walk']['nominal']['speed_mm_s']} mm/s" in text
        assert f"{comb['walk']['nominal']['speed_mm_s']} mm/s" in text
        assert f"{drawn['jump']['result']['com_rise_in_flight_mm']} mm" in text
        assert "not the" in text and "owner's design" in text
        assert "hop" in text
    assert "docs/generator-changes.md" in readme
    assert "not allowed on real hardware by default" in readme
