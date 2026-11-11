# SPDX-License-Identifier: MIT
"""Trajectory files, their limits, and the player. No test here opens a
serial port or a socket to another machine."""
import importlib.util
import threading

import pytest

from conftest import ROOT
from microduck import gait, player, protocol, sim

TRAJECTORIES = sorted((ROOT / "trajectories").glob("*.csv"))


@pytest.fixture(scope="module")
def cal():
    return protocol.load_calibration()


def test_trajectories_are_committed():
    assert {p.name for p in TRAJECTORIES} >= {"stand.csv", "gait.csv"}


@pytest.mark.parametrize("path", TRAJECTORIES, ids=lambda p: p.name)
def test_trajectory_stays_inside_limits_and_speed(path, cal):
    trajectory = gait.read_csv(path)
    assert trajectory[0][0] == 0
    assert gait.check_limits(trajectory, cal) == []


def test_csv_round_trip(tmp_path, cal):
    trajectory = gait.gait(cal.stand_deg, gait.load_params(), 2.0)
    gait.write_csv(tmp_path / "t.csv", trajectory)
    again = gait.read_csv(tmp_path / "t.csv")
    assert [t for t, _ in again] == [t for t, _ in trajectory]
    for (_, a), (_, b) in zip(again, trajectory):
        assert a == pytest.approx(b, abs=0.05)


def test_gait_starts_from_the_stand_pose_and_is_periodic(cal):
    params = gait.load_params()
    trajectory = gait.gait(cal.stand_deg, params, 6.0)
    assert trajectory[0][1] == cal.stand_deg
    lead = int(params["lead_in_s"] * 1000)
    assert all(q == cal.stand_deg for t, q in trajectory if t <= lead)
    period = int(params["period_s"] * 1000)
    by_time = dict(trajectory)
    assert by_time[4000] == pytest.approx(by_time[4000 + period], abs=1e-6)
    # both hips roll the same way; the pitch offsets are opposite
    q = by_time[4240]
    assert q[0] - cal.stand_deg[0] == pytest.approx(q[3] - cal.stand_deg[3])


def test_limit_check_catches_range_and_speed(cal):
    out_of_range = [(0, list(cal.stand_deg)), (20, [cal.joints[0].max_deg + 5.0] + list(cal.stand_deg[1:]))]
    problems = gait.check_limits(out_of_range, cal)
    assert any("outside" in what for _, _, what in problems)
    jump = [(0, list(cal.stand_deg)), (20, [10.0] + list(cal.stand_deg[1:]))]
    assert any("deg/s" in what for _, _, what in gait.check_limits(jump, cal))


def test_bad_csv_is_rejected(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("t_ms,a,b,c,d,e,f\n0,0,0,0,0,0,0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        gait.read_csv(bad)


def test_player_drives_the_simulator(cal):
    link = player.SimLink(sim.DuckSim())
    trajectory = gait.stand(cal.stand_deg, 2.0)
    result = player.play(link, trajectory, cal)
    assert result["stopped_at_ms"] is None
    assert result["sent"] == len(trajectory)
    assert result["final_status"].startswith("STAT mode=RUN")
    assert link.sim.fell_at is None


def test_player_refuses_an_unplayable_trajectory(cal):
    link = player.SimLink(sim.DuckSim())
    jump = [(0, list(cal.stand_deg)), (20, [40.0] + list(cal.stand_deg[1:]))]
    with pytest.raises(ValueError):
        player.play(link, jump, cal)
    assert link.sim.controller.mode == protocol.RELAX, "nothing was sent"


def test_hardware_links_need_the_explicit_flag():
    with pytest.raises(player.HardwareNotAllowed):
        player.SerialLink("COM99")
    with pytest.raises(player.HardwareNotAllowed):
        player.TcpLink("192.0.2.1", 8766)


def test_player_over_the_robot_socket(cal):
    """The simulator behind the same TCP line protocol the UNO Q agent speaks,
    on this machine only."""
    spec = importlib.util.spec_from_file_location("virtual_robot", ROOT / "scripts" / "virtual_robot.py")
    virtual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(virtual)
    port = []
    ready = threading.Event()
    thread = threading.Thread(target=virtual.serve, daemon=True,
                              kwargs={"port": 0, "once": True, "ready": lambda p: (port.append(p), ready.set())})
    thread.start()
    assert ready.wait(20)
    link = player.TcpLink("127.0.0.1", port[0])
    assert link.hardware is False
    try:
        result = player.play(link, gait.stand(cal.stand_deg, 0.6), cal)
        assert result["stopped_at_ms"] is None
        assert link.send("C 0") == "OK"
        assert player.calibrate_step(link, 0, "+", 1.0).startswith("CAL 0 servo=91.0")
        assert player.calibrate_step(link, 0, "end") == "OK"
        assert link.send("R") == "OK"
    finally:
        link.close()
    thread.join(10)
    assert not thread.is_alive()
