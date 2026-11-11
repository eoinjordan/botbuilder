# SPDX-License-Identifier: MIT
"""Headless MuJoCo runs: standing, the fall from neutral, watchdog, gait."""
import pytest

from microduck import gait, protocol, sim
from microduck.protocol import JOINTS


@pytest.fixture(scope="module")
def duck():
    return sim.DuckSim()


def test_stands_at_the_stand_pose(duck):
    duck.reset("stand")
    result = sim.play(duck, gait.stand(duck.cal.stand_deg, 5.0))
    assert not result["fell"]
    assert result["max_tilt_deg_while_upright"] < 3.0
    assert abs(result["distance_forward_m"]) < 0.01
    for joint in JOINTS:
        torque = result["torque"][joint]
        assert torque["peak_fraction_of_limit"] < 0.5, f"{joint} needs {torque['peak_nm']} N m to stand"
        assert torque["saturated_fraction_of_time"] == 0.0
    assert result["feet"]["both_loaded_fraction"] > 0.95


def test_falls_backward_with_straight_legs(duck, selected):
    """The assembly test puts the centre of mass behind the heels at the
    neutral pose; the simulation should agree."""
    assert not selected["balance"]["neutral_two_feet"]["inside"]
    duck.reset("neutral")
    result = sim.play(duck, gait.stand([0.0] * 6, 3.0))
    assert result["fell"]
    assert result["fell_how"] == "backward"
    assert result["fell_at_s"] < 2.0


def test_commands_reach_the_joints(duck):
    duck.reset("stand")
    target = list(duck.cal.stand_deg)
    target[0], target[3] = 5.0, 5.0
    duck.send("E")
    for _ in range(60):
        duck.send(protocol.format_joints(target))
        duck.tick()
    measured = duck.joint_deg()
    assert measured[0] == pytest.approx(5.0, abs=2.0)
    assert measured[3] == pytest.approx(5.0, abs=2.0)


def test_simulated_joint_speed_respects_the_controller_limit(duck):
    duck.reset("stand")
    duck.send("E")
    target = list(duck.cal.stand_deg)
    target[2] = target[2] + 40.0        # left knee, off the ground effect is small
    previous = duck.controller.current[2]
    for _ in range(10):
        duck.send(protocol.format_joints(target))
        duck.tick()
        now = duck.controller.current[2]
        assert abs(now - previous) <= duck.cal.max_speed_deg_s * 0.02 + 1e-9
        previous = now


def test_watchdog_holds_the_robot_up(duck):
    duck.reset("stand")
    duck.send("E")
    trajectory = gait.gait(duck.cal.stand_deg, gait.load_params(), 3.0)
    for t, q in trajectory:
        while duck.now_ms < t:
            duck.tick()
        duck.send(protocol.format_joints(q))
    for _ in range(150):                # three seconds of silence
        duck.tick()
    assert duck.controller.mode == protocol.HOLD
    assert duck.fell_at is None


def test_relax_stops_the_drive(duck):
    duck.reset("stand")
    duck.send("E")
    duck.send(protocol.format_joints(duck.cal.stand_deg))
    duck.tick()
    assert duck.send("R") == "OK"
    duck.tick()
    assert duck.controller.pulses_us() == [0] * 6
    assert (duck.model.actuator_gainprm[:, 0] == 0).all()
    duck.send("E")
    duck.tick()
    assert (duck.model.actuator_gainprm[:, 0] > 0).all()


def test_default_gait_outcome_matches_the_report(duck, sim_report):
    """Whatever the experiment found is what a fresh run finds."""
    recorded = sim_report["gait_default"]
    duck.reset("stand")
    result = sim.play(duck, gait.gait(duck.cal.stand_deg, gait.load_params(), 12.0))
    assert result["fell"] == recorded["fell"]
    if not recorded["fell"]:
        assert result["distance_forward_m"] == pytest.approx(recorded["distance_forward_m"], abs=0.05)
    assert abs(result["distance_forward_m"]) < 1.0


def test_report_invariants(sim_report):
    assert "never been assembled" in sim_report["status"]
    assert sim_report["stand"]["fell"] is False
    assert sim_report["neutral"]["fell"] is True
    assert sim_report["gait_sweep"]["runs"] == len(sim_report["gait_sweep"]["rows"])
    assert sim_report["gait_default"]["limit_problems"] == 0
    assert sim_report["suggestions"]
    for joint in JOINTS:
        assert sim_report["stand"]["torque"][joint]["peak_nm"] <= sim_report["stand"]["torque"][joint]["limit_nm"]


def test_mount_error_shows_up_and_calibration_removes_it():
    """A horn mounted 4 degrees off moves the joint 4 degrees; nudging the
    servo back and taking the zero puts it right."""
    error = [0.0, 0.0, 4.0, 0.0, 0.0, 0.0]
    duck = sim.DuckSim(mount_error_deg=error)
    duck.reset("stand")
    duck.send("E")
    for _ in range(40):
        duck.send(protocol.format_joints(duck.cal.stand_deg))
        duck.tick()
    direction = duck.cal.joints[2].direction
    off = duck.joint_deg()[2] - duck.cal.stand_deg[2]
    assert off == pytest.approx(-4.0 / direction, abs=1.5)
    assert duck.send("C 2") == "OK"
    for _ in range(4):
        assert duck.send("N 1").startswith("CAL 2")
        for _ in range(10):
            duck.tick()
    assert duck.joint_deg()[2] == pytest.approx(duck.cal.stand_deg[2], abs=1.5)
