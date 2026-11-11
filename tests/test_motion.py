# SPDX-License-Identifier: MIT
"""The motion study: the servo and command-path model, the leg clearance
rule, the search, every shipped trajectory checked over its whole length, the
manifest for the control page, and the headline numbers of
reports/motion.json rerun with tolerances."""
import json
from dataclasses import replace

import numpy as np
import pytest

from conftest import ROOT, needs_stls
from microduck import clearance, cmaes, gait, gaitsearch, motiongen, motionsim, protocol, variant
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
    return motionsim.MotionSim("comb")


@pytest.fixture(scope="module")
def cal():
    return protocol.load_calibration()


# --- the model ---------------------------------------------------------------

def test_every_physics_parameter_is_stated_with_a_reason():
    config = variant.load_json("motion.json")
    for name, item in {**config["physics"], **config["firmware"]}.items():
        assert "value" in item and len(item["why"]) > 20, name
    for needed in ("transport_delay_ms", "pwm_latency_ms", "deadband_deg", "backlash_deg", "flex_nm_per_rad",
                   "supply_current_a", "floor_friction", "sole_sag_mm"):
        assert needed in config["physics"]


def test_servo_limits_are_the_published_ones(duck, joints):
    for i, name in enumerate(JOINTS):
        assert duck.limits[i] == pytest.approx(joints["joints"][name]["torque_limit_nm"], rel=1e-3)
        assert np.degrees(duck.speed_limits[i]) == pytest.approx(joints["joints"][name]["speed_limit_deg_s"], rel=5e-3)
    assert duck.supply_a == 4.0


def test_the_robot_is_the_generated_one(duck, joints):
    assert duck.mass == pytest.approx(joints["mass_kg"], abs=0.002)
    assert variant.preset_overrides("comb") == {}
    assert duck.cal.stand_deg == [joints["stand_pose_deg"][j] for j in JOINTS]
    assert [(j.min_deg, j.max_deg) for j in duck.cal.joints] == [(joints["joints"][j]["min_deg"], joints["joints"][j]["max_deg"]) for j in JOINTS]


def test_head_mass_is_a_parameter(duck):
    heavier = motionsim.MotionSim("comb", head={"extra_mass_g": 32.0, "position_mm": [60.0, 0.0, 110.0]})
    assert heavier.mass == pytest.approx(duck.mass + 0.032, abs=1e-4)
    duck.reset()
    assert heavier.com()[2] > duck.com()[2]


def test_a_command_reaches_the_servo_after_the_delays(duck):
    """Transport delay, then the controller tick, then one PWM frame."""
    duck.reset()
    target = list(duck.cal.stand_deg)
    target[0] += 10.0
    target[3] += 10.0
    before = duck.target.copy()
    duck.send(protocol.format_joints(target))
    duck.tick()
    assert duck.target[0] == before[0]                  # 20 ms: still in transit
    duck.tick()
    assert duck.target[0] == before[0]                  # 40 ms: set by the controller, not yet in a frame
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


def test_torque_never_exceeds_stall_and_current_is_limited():
    fast_cal = replace(variant.calibration("comb"), max_speed_deg_s=430.0)
    fast = motionsim.MotionSim("comb", cal=fast_cal)
    far = motiongen.symmetric(0.0, 0.0, 0.0)
    log = motionsim.run(fast, [(t, far if t > 200 else list(fast_cal.stand_deg)) for t in range(0, 800, 20)])
    assert (np.abs(log["torque"]) <= fast.limits + 1e-9).all()
    assert log["current"].max() > fast.supply_a         # the move asks for more than the supply has
    assert log["current_limited_fraction"] > 0.0


def test_stands(duck):
    duck.reset()
    log = motionsim.run(duck, gait.stand(duck.cal.stand_deg, 5.0))
    assert log["fell_at"] is None
    assert log["tilt"].max() < 3.0
    assert set(log["contact_kinds"]) == {"sole"}
    assert not log["part_on_part"]                      # the legs are apart and clear of the torso
    assert np.abs(log["joint"][-1] - np.array(duck.cal.stand_deg)).max() < 3.0


def test_flat_feet_preset_changes_only_the_soles_and_the_roll_limits(duck):
    flat = motionsim.MotionSim("flat_feet")
    assert set(variant.preset_overrides("flat_feet")) == {"foot", "joint_limits_deg"}
    assert set(variant.preset_overrides("flat_feet")["joint_limits_deg"]) == {"left_hip_roll", "right_hip_roll"}
    assert flat.cal.stand_deg == duck.cal.stand_deg
    assert flat.cal.clearance is None and duck.cal.clearance is not None
    for name in ("torso", "left_hip", "left_thigh"):
        a, b = duck.model.body(name), flat.model.body(name)
        assert np.allclose(a.mass, b.mass) and np.allclose(a.ipos, b.ipos)
    assert flat.mass < duck.mass
    assert len(flat.soles["left"]) == 1 and len(duck.soles["left"]) > 5


# --- the leg clearance rule --------------------------------------------------

def test_clearance_table_is_up_to_date(cal):
    assert cal.clearance == json.loads(json.dumps(clearance.build()))
    assert cal.clearance["margin_mm"] == clearance.MARGIN_MM


def test_own_sine_is_a_sine():
    for deg in (-360.0, -180.0, -90.0, -33.3, 0.0, 12.5, 45.0, 90.0, 135.0, 179.9, 270.0, 360.0):
        assert protocol.sine(deg) == pytest.approx(np.sin(np.radians(deg)), abs=2e-9)
        assert protocol.cosine(deg) == pytest.approx(np.cos(np.radians(deg)), abs=2e-9)


def test_rule_frames_agree_with_the_generated_model(duck, cal):
    """The rule's closed-form leg agrees with MuJoCo's kinematics of robot/microduck.xml."""
    import mujoco
    rng = np.random.default_rng(0)
    m, d = duck.model, duck.data
    for _ in range(20):
        q = rng.uniform(-60, 60, 6)
        mujoco.mj_resetData(m, d)
        d.qpos[2] = 0.0
        d.qpos[duck.qadr] = np.radians(q)
        mujoco.mj_kinematics(m, d)
        for side, k in (("left", 0), ("right", 3)):
            _, p_thigh, shin, p_shin = protocol._leg(cal.clearance["legs"][side], q[k], q[k + 1], q[k + 2])
            body = m.body(f"{side}_shin").id
            assert np.allclose(np.array(p_shin) / 1000.0, d.xpos[body], atol=1e-5)
            assert np.allclose(np.array(shin), d.xmat[body].reshape(3, 3), atol=1e-6)
            assert np.allclose(np.array(p_thigh) / 1000.0, d.xpos[m.body(f"{side}_thigh").id], atol=1e-5)


def test_one_joint_cannot_be_driven_into_the_other_sole(cal):
    """The case the per-joint limits miss: from the stand pose, one hip
    roll alone. The command is refused, a jog stops short, and a
    calibration nudge is refused."""
    stand = list(cal.stand_deg)
    assert protocol.legs_clear(cal.clearance, stand)
    swung = list(stand)
    swung[0] -= 12.0                                    # the left hip rolled inward, inside the limits of that joint
    assert cal.clamp(swung) == swung
    assert not protocol.legs_clear(cal.clearance, swung)
    controller = protocol.Controller(cal)
    controller.handle("E", 0)
    assert controller.handle(protocol.format_joints(swung), 0) == "ERR CLEAR"
    assert controller.target == stand
    # jog the joint a degree at a time: the commanded angle stops while the legs are still apart
    now, q = 0, list(stand)
    for _ in range(40):
        q[0] -= 1.0
        controller.handle(protocol.format_joints(q), now)
        now += 20
        controller.tick(now)
    assert protocol.legs_clear(cal.clearance, controller.current)
    assert stand[0] - 12.0 < controller.current[0] <= stand[0]
    # calibration mode moves a joint directly; it is held to the same rule
    assert controller.handle("C 0", now) == "OK"
    replies = [controller.handle("N -2", now) for _ in range(25)]
    assert "ERR CLEAR" in replies
    assert protocol.legs_clear(cal.clearance, controller.current)


def test_a_step_through_the_other_leg_is_not_taken(cal):
    controller = protocol.Controller(cal)
    controller.handle("E", 0)
    blocked = list(cal.stand_deg)
    blocked[0] -= 12.0
    controller.mode, controller.target = protocol.RUN, blocked     # as if the target had been accepted
    for now in range(20, 2000, 20):
        controller.tick(now)
    assert protocol.legs_clear(cal.clearance, controller.current)
    assert controller.current[0] > blocked[0] + 3.0


@needs_stls
def test_rule_never_accepts_a_pose_the_meshes_reject(cal):
    """A fresh sample against the exact meshes; the full run is in reports/clearance.json."""
    result = clearance.validate(seed=7, uniform=150, near_stand=250, one_joint=20)
    assert result["total"]["false_accepts"] == 0
    assert result["total"]["mesh_colliding"] > 50
    assert result["total"]["false_reject_rate_of_free_poses"] < 0.3


def test_recorded_validation_of_the_rule():
    with open(ROOT / "reports" / "clearance.json", encoding="utf-8") as handle:
        result = json.load(handle)
    assert result["margin_mm"] == clearance.MARGIN_MM
    assert result["total"]["poses"] >= 40000
    assert result["total"]["false_accepts"] == 0
    assert all(s["false_accepts"] == 0 for s in result["sets"].values())


# --- the search and the gait --------------------------------------------------

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
            assert search["seed"] >= 0 and search["generations"] > 0 and search["wall_clock_s"] <= search["wall_clock_budget_s"] + 120
    assert gaits["search"]["total_simulated_runs"] > 1000


def test_walk_is_the_gait_of_gait_py(gaits, cal):
    """Forward 1 and turn 0 give exactly gait.gait(); the control page plays the same formula."""
    params = gaits["comb"]["walk"]["params"]
    ours = motiongen.walk(cal.stand_deg, params, 6.0, 1.0, 0.0, params["lead_in_s"], 1e9)
    theirs = gait.gait(cal.stand_deg, params, 6.0)
    assert [t for t, _ in ours] == [t for t, _ in theirs]
    for (_, a), (_, b) in zip(ours, theirs):
        assert a == pytest.approx(b, abs=0.051)
    on_disk = gait.load_params(ROOT / "config" / "gait_motion.json")
    assert {k: v for k, v in on_disk.items() if not k.startswith("_")} == params


def test_gait_stays_inside_the_rate_limit_over_the_envelope(gaits, manifest, cal):
    for forward in manifest["gait"]["forward"] + [1.0]:
        for turn in manifest["gait"]["turn"] + [0.0]:
            trajectory, _ = mx.walk_trajectory(cal, gaits["comb"]["walk"], 5.0, forward, turn)
            assert gait.check_limits(trajectory, cal) == []
            assert gaitsearch.refused_fraction(cal, trajectory) == 0.0


# --- the files for the robot and the control page ----------------------------

def test_manifest_has_the_shape_the_control_page_reads(manifest, cal):
    assert manifest["version"] == 1
    g = manifest["gait"]
    assert g["params"] == "config/gait_motion.json" and (ROOT / g["params"]).is_file()
    for key in ("forward", "turn"):
        low, high = g[key]
        assert -1.0 <= low <= 0.0 <= high <= 1.0
    assert g["forward"][1] > 0.0
    assert set(manifest["motions"]) <= {"stand", "sit", "jump"}
    for name, entry in manifest["motions"].items():
        assert set(entry) == {"file", "label"}
        path = ROOT / entry["file"]
        assert entry["file"].startswith("trajectories/") and path.is_file()
        assert gait.check_limits(gait.read_csv(path), cal) == []        # what the page's loader checks
    assert "stand" in manifest["motions"] and "sit" in manifest["motions"]
    assert "jump" not in manifest["motions"]
    assert "strip gears" in manifest["unavailable"]["jump"]


def test_every_trajectory_passes_its_checks_over_its_whole_length(manifest):
    """Soft limits, speed limit and the leg clearance rule through
    protocol.Controller, the collision boxes of the two legs and the exact
    meshes of the two legs, for every row of every file."""
    default = protocol.load_calibration().max_speed_deg_s
    names = {f["name"] for f in manifest["study"]["files"]}
    assert names == {"walk", "turn_left", "turn_right", "sit", "stand_up", "jump"}
    for entry in manifest["study"]["files"]:
        trajectory = gait.read_csv(ROOT / entry["file"])
        cal = variant.calibration("comb")
        check = mx.check_trajectory(trajectory, cal, entry["max_speed_deg_s"])
        assert check == entry["checks"], entry["name"]
        assert mx.trajectory_passes(check) and entry["passes_checks"], (entry["name"], check)
        assert check["rows_checked_against_the_leg_meshes"] == len(trajectory)
        assert check["worst_leg_mesh_overlap_mm3"] == 0.0
        assert entry["duration_s"] == pytest.approx(trajectory[-1][0] / 1000.0)
        assert all(b[0] - a[0] == protocol.TICK_MS for a, b in zip(trajectory, trajectory[1:]))
        if entry["max_speed_deg_s"] > default:
            assert entry["needs_speed_limit_raised"] and "restricted/" in entry["file"]


def test_a_trajectory_that_crosses_the_legs_fails_the_checks(cal):
    stand = list(cal.stand_deg)
    crossing = list(stand)
    crossing[0] -= 12.0
    trajectory = motiongen.keyframes([(0.0, stand), (0.5, stand), (1.5, crossing), (2.0, crossing)], 60.0)
    check = mx.check_trajectory(trajectory, cal, cal.max_speed_deg_s)
    assert check["limit_problems"] == 0                 # the per-joint limits do not see it
    assert check["refused_by_the_leg_clearance_rule"] > 0
    assert check["least_gap_between_leg_boxes_mm"] <= 0.0
    assert check["worst_leg_mesh_overlap_mm3"] > 0.5
    assert not mx.trajectory_passes(check)


def test_walk_files_loop(manifest):
    for entry in manifest["study"]["files"]:
        if "loop" not in entry:
            continue
        rows = dict(gait.read_csv(ROOT / entry["file"]))
        start, period = entry["loop"]["from_ms"], entry["loop"]["period_ms"]
        assert period % protocol.TICK_MS == 0
        for t in range(start, start + period, 100):
            if t + period in rows:
                assert np.abs(np.array(rows[t]) - np.array(rows[t + period])).max() <= 0.11, (entry["name"], t)


def test_gait_parameter_file_has_the_tested_envelope(report, manifest):
    with open(ROOT / "trajectories" / "gait_params.json", encoding="utf-8") as handle:
        doc = json.load(handle)
    env = report["presets"]["comb"]["walk"]["envelope"]
    assert doc["params"] == report["presets"]["comb"]["walk"]["gait"]["params"]
    assert doc["forward"] == manifest["gait"]["forward"] == env["forward_range"]
    assert doc["turn"] == manifest["gait"]["turn"] == env["turn_range"]
    assert len(doc["points"]) == len(mx.ENVELOPE_FORWARD) * len(mx.ENVELOPE_TURN)
    ok = {(p["forward"], p["turn"]) for p in doc["points"] if p["ok_at_every_friction"]}
    for f in mx.ENVELOPE_FORWARD:
        for t in mx.ENVELOPE_TURN:
            if doc["forward"][0] <= f <= doc["forward"][1] and doc["turn"][0] <= t <= doc["turn"][1]:
                assert (f, t) in ok, (f, t)


# --- headline numbers, rerun --------------------------------------------------

@pytest.mark.parametrize("preset", mx.PRESETS)
def test_walk_headline_numbers(preset, report, gaits):
    recorded = report["presets"][preset]["walk"]["nominal"]
    fresh = mx.walk_run(motionsim.MotionSim(preset), gaits[preset]["walk"], mx.WALK_SECONDS)
    assert fresh["fell"] == recorded["fell"]
    if not recorded["fell"]:
        assert fresh["speed_mm_s"] == pytest.approx(recorded["speed_mm_s"], rel=0.35, abs=3.0)
        assert fresh["single_support_fraction"] == pytest.approx(recorded["single_support_fraction"], abs=0.12)
        assert fresh["median_clearance_mm"] == pytest.approx(recorded["median_clearance_mm"], rel=0.5, abs=1.5)
        assert fresh["peak_torque_fraction"] == pytest.approx(recorded["peak_torque_fraction"], abs=0.15)


def test_the_comb_robot_steps_with_margin(report):
    comb = report["presets"]["comb"]
    walk = comb["walk"]
    assert comb["one_foot_test"]["stands_on_one_foot"] is True
    assert walk["truly_steps"] is True
    assert walk["nominal"]["torque_margin"] >= 0.2
    assert walk["nominal"]["commands_refused_fraction"] == 0.0
    assert walk["long_horizon"]["fell"] is False
    assert walk["robustness"]["fell"] == 0
    assert walk["robustness"]["worst_peak_torque_fraction"] < 1.0
    assert walk["envelope"]["forward_range"][1] == 1.0
    assert comb["stop"]["watchdog_hold_stays_up"] is True


def test_jump_is_a_hop_and_stays_locked(report, gaits, manifest):
    recorded = report["presets"]["comb"]["jump"]
    fresh = mx.jump_run("comb", gaits["comb"]["jump"]["params"], recorded["max_speed_deg_s"])
    assert fresh["verdict"] == recorded["result"]["verdict"]
    assert fresh["landed_upright"] == recorded["result"]["landed_upright"]
    assert fresh["flight_s"] == pytest.approx(recorded["result"]["flight_s"], abs=0.04)
    assert fresh["com_rise_in_flight_mm"] == pytest.approx(recorded["result"]["com_rise_in_flight_mm"], rel=0.4, abs=1.5)
    assert mx.jump_verdict({"flight_s": 0.06, "feet_rise_mm": 4.0, "com_rise_in_flight_mm": 3.0}) == "hop"
    assert mx.jump_verdict({"flight_s": 0.10, "feet_rise_mm": 12.0, "com_rise_in_flight_mm": 4.0}) == "hop"
    assert mx.jump_verdict({"flight_s": 0.15, "feet_rise_mm": 15.0, "com_rise_in_flight_mm": 12.0}) == "jump"
    assert mx.jump_verdict({"flight_s": 0.0, "feet_rise_mm": 0.0, "com_rise_in_flight_mm": 0.0}) == "no flight"
    assert recorded["result"]["verdict"] != "jump"
    assert recorded["result"]["com_rise_in_flight_mm"] <= recorded["no_load_bound"]["ballistic_rise_mm"]
    assert recorded["at_default_speed_limit"]["verdict"] == "no flight"
    for joint, demand in recorded["result"]["demand"].items():
        assert demand["peak_torque_nm"] <= demand["torque_limit_nm"] + 1e-6, joint
    assert "jump" in manifest["unavailable"]


def test_sit_power_off_and_stand_up(report):
    recorded = report["presets"]["comb"]["sit"]
    fresh = mx.sit_run("comb")
    for key in ("sat_down", "stood_up_without_power_off", "relaxed_rest_holds", "stood_up", "board_or_head_touched",
                "parts_that_touched_the_floor"):
        assert fresh[key] == recorded[key], key
    assert fresh["sat_down"] and fresh["stood_up_without_power_off"]
    assert fresh["parts_that_touched_the_floor"] == ["sole"]
    assert fresh["board_or_head_touched"] is False
    assert fresh["relaxed_rest"]["joints_deg"]["hip_pitch"] == pytest.approx(recorded["relaxed_rest"]["joints_deg"]["hip_pitch"], abs=4.0)


def test_documents_carry_the_safety_warnings(report):
    text = (ROOT / "docs" / "motion.md").read_text(encoding="utf-8")
    assert "can strip gears or break parts" in text
    assert "Power off" in text and "supply" in text.lower()
    comb = report["presets"]["comb"]
    assert str(comb["walk"]["nominal"]["speed_mm_s"]) in text
    assert "ERR CLEAR" in text


def test_readme_and_site_carry_the_reported_numbers(report):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    walk = report["presets"]["comb"]["walk"]["nominal"]
    for text in (readme, page):
        assert f"{walk['speed_mm_s']} mm/s" in text
        assert str(walk["peak_torque_fraction"]) in text
        assert "hop" in text and "strip gears" in text
    assert "ERR CLEAR" in readme
    assert f"{report['leg_clearance_rule']['total']['poses']} poses" in readme
