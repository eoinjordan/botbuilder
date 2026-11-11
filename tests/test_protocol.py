# SPDX-License-Identifier: MIT
"""The command format, the calibration table and the reference controller."""
import json

import pytest

from conftest import ROOT
from microduck import protocol
from microduck.protocol import CAL, HOLD, JOINTS, RELAX, RUN, TICK_MS


@pytest.fixture()
def cal():
    return protocol.load_calibration()


@pytest.fixture()
def running(cal):
    controller = protocol.Controller(cal)
    assert controller.handle("E", 0) == "OK"
    return controller


def test_joint_line_round_trip():
    q = [0.0, 45.0, -45.0, 12.3, -0.1, 89.9]
    line = protocol.format_joints(q)
    assert line == "J 0.0 45.0 -45.0 12.3 -0.1 89.9\n"
    assert protocol.parse_joints(line) == q


def test_format_has_no_negative_zero_and_rounds_half_away():
    assert protocol.fmt1(-0.04) == "0.0"
    assert protocol.fmt1(0.05) == "0.1"
    assert protocol.fmt1(-0.05) == "-0.1"
    assert protocol.fmt1(123.44) == "123.4"


@pytest.mark.parametrize("token", ["1e3", "nan", "inf", "0x10", "1_0", "", ".", "--1", "1.2.3", "1234567"])
def test_strict_numbers(token):
    with pytest.raises(ValueError):
        protocol.parse_number(token)


def test_calibration_round_trip(cal):
    q = [10.0, -20.0, 30.0, -40.0, 50.0, -60.0]
    assert cal.joint_deg(cal.servo_deg(q)) == pytest.approx(q)
    for joint in cal.joints:
        assert joint.to_joint(joint.to_servo(17.5)) == pytest.approx(17.5)
        assert joint.to_servo(0.0) == joint.zero_deg
        assert joint.direction in (1, -1)


def test_calibration_table_is_complete(cal, joints):
    assert [j.name for j in cal.joints] == JOINTS
    assert sorted(j.channel for j in cal.joints) == ["M1", "M2", "M3", "M4", "M5", "M6"]
    assert sorted(j.pin for j in cal.joints) == [3, 5, 6, 9, 10, 11]      # Braccio shield M6..M1
    assert cal.soft_start_pin == 12
    for joint in cal.joints:
        assert joint.min_deg == joints["joints"][joint.name]["min_deg"]
        assert joint.max_deg == joints["joints"][joint.name]["max_deg"]
        assert joint.servo == joints["joints"][joint.name]["servo"]
        # the whole joint range must fit in the servo's 0..180 degrees
        assert 0.0 <= joint.to_servo(joint.min_deg) <= 180.0
        assert 0.0 <= joint.to_servo(joint.max_deg) <= 180.0


def test_default_directions_follow_the_shaft_directions(cal, joints):
    """Starting guess only: a servo is taken to turn its horn positively about
    its own shaft for increasing pulse width. Unverified on hardware."""
    for joint in cal.joints:
        j = joints["joints"][joint.name]
        dot = sum(a * b for a, b in zip(j["shaft_direction"], j["axis"]))
        assert joint.direction == (1 if dot > 0 else -1)


def test_pulse_matches_the_sketchbot_mapping(cal):
    assert cal.pulse_us(0.0) == 500
    assert cal.pulse_us(90.0) == 1500
    assert cal.pulse_us(180.0) == 2500
    assert cal.pulse_us(-5.0) == 500 and cal.pulse_us(200.0) == 2500


def test_bad_calibration_is_rejected(tmp_path):
    raw = json.loads((ROOT / "config" / "calibration.json").read_text(encoding="utf-8"))
    raw["joints"][1]["pin"] = raw["joints"][0]["pin"]
    bad = tmp_path / "calibration.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        protocol.load_calibration(bad)
    raw["joints"][1]["pin"] = 10
    raw["joints"][2]["direction"] = 0
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        protocol.load_calibration(bad)


def test_starts_relaxed_and_refuses_motion(cal):
    controller = protocol.Controller(cal)
    assert controller.mode == RELAX
    assert controller.pulses_us() == [0] * 6
    assert controller.handle(protocol.format_joints(cal.stand_deg), 0) == "ERR DISABLED"
    assert controller.handle("E", 0) == "OK"
    assert all(p > 0 for p in controller.pulses_us())


def test_soft_limits_clamp(running, cal):
    reply = running.handle("J 500 0 0 -500 0 0", 20)
    assert reply == "OK CLAMP 2"
    assert running.target[0] == cal.joints[0].max_deg
    assert running.target[3] == cal.joints[3].min_deg


def test_speed_limit(running, cal):
    running.handle("J 0 -45 45 0 -45 45", 0)
    before = list(running.current)
    step = cal.max_speed_deg_s * TICK_MS / 1000.0
    for now in range(TICK_MS, 400, TICK_MS):
        running.handle("J 0 -45 45 0 -45 45", now)
        running.tick(now)
        for a, b in zip(before, running.current):
            assert abs(b - a) <= step + 1e-9
        before = list(running.current)
    assert before[1] < 45.0, "it is moving"
    assert before[1] > -45.0, "but has not jumped there"


def test_watchdog_holds(running):
    running.handle("J 0 -45 0 0 0 0", 0)       # 90 degrees away: 750 ms at the speed limit
    for now in range(TICK_MS, 400, TICK_MS):
        running.tick(now)
    assert running.mode == RUN
    for now in range(400, 800, TICK_MS):
        running.tick(now)
    assert running.mode == HOLD
    frozen = list(running.current)
    assert -45.0 < frozen[1] < 45.0, "stopped part way"
    for now in range(800, 1600, TICK_MS):
        running.tick(now)
    assert running.current == frozen
    assert all(p > 0 for p in running.pulses_us()), "hold keeps the servos powered"
    assert running.handle("J 0 0 0 0 0 0", 1600) == "OK"
    assert running.mode == RUN


def test_watchdog_can_relax(running):
    assert running.handle("W 200 relax", 0) == "OK"
    running.handle("J 0 0 0 0 0 0", 0)
    for now in range(TICK_MS, 400, TICK_MS):
        running.tick(now)
    assert running.mode == RELAX
    assert running.pulses_us() == [0] * 6


def test_watchdog_is_not_armed_before_the_first_target(running):
    for now in range(TICK_MS, 3000, TICK_MS):
        running.tick(now)
    assert running.mode == RUN


def test_status_line(running):
    running.handle("J 0 45 -45 0 45 -45", 100)
    reply = running.handle("S", 160)
    assert reply == "STAT mode=RUN age_ms=60 wd=500 q=0.0,45.0,-45.0,0.0,45.0,-45.0"


def test_calibration_moves_one_joint_by_small_steps(running, cal):
    assert running.handle("N 1", 0) == "ERR NOT CAL"
    assert running.handle("C 2", 0) == "OK"
    assert running.mode == CAL
    assert running.handle("J 0 0 0 0 0 0", 0) == "ERR CAL"
    assert running.handle("N 5", 0) == "ERR STEP"
    before = running.servo_deg()
    reply = running.handle("N 1.5", 0)
    assert reply.startswith("CAL 2 servo=")
    after = running.servo_deg()
    assert after[2] - before[2] == pytest.approx(1.5)
    assert [a for i, a in enumerate(after) if i != 2] == [b for i, b in enumerate(before) if i != 2]
    reply = running.handle("Z", 0)
    assert reply == f"ZERO 2 {protocol.fmt1(after[2])}"
    assert running.current[2] == 0.0
    assert running.servo_deg()[2] == pytest.approx(after[2]), "taking a zero must not move the servo"
    assert running.handle("X", 0) == "OK"
    assert running.mode == HOLD


@pytest.mark.parametrize("line,reply", [
    ("", "ERR EMPTY"), ("Q", "ERR UNKNOWN"), ("JJ 1", "ERR UNKNOWN"), ("J 1 2 3", "ERR ARGS"),
    ("J a 0 0 0 0 0", "ERR ARGS"), ("J 1e2 0 0 0 0 0", "ERR ARGS"), ("J nan 0 0 0 0 0", "ERR ARGS"),
    ("J 2000 0 0 0 0 0", "ERR ARGS"), ("W 50 hold", "ERR ARGS"), ("W 500 drop", "ERR ARGS"),
    ("C 6", "ERR ARGS"), ("C -1", "ERR ARGS"), ("E now", "ERR ARGS"),
])
def test_bad_lines(running, line, reply):
    assert running.handle(line, 0) == reply
