# SPDX-License-Identifier: MIT
"""Headline simulation results of the crank walkers, pinned with tolerances.
Steady, low-speed results are re-run here; results that sit on a tipping
point are pinned from the committed report."""
import json

import pytest

from conftest import ROOT
from walkers import model, sim

BUILDS = model.BUILDS


@pytest.fixture(scope="module")
def report():
    return json.loads((ROOT / "reports" / "lego" / "sim.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("build", BUILDS)
def test_stands_on_one_foot(build):
    s = sim.WalkerSim(build)
    r = sim.run(s, sim.constant(0.0), 2.0)
    assert not r["fell"] and r["max_tilt_deg"] < 1.0
    assert abs(r["distance_forward_m"]) < 0.002


@pytest.mark.parametrize("build", BUILDS)
def test_walks_at_the_kinematic_speed(build, report):
    s = sim.WalkerSim(build)
    r = sim.run(s, sim.constant(60.0), 6.0)
    assert not r["fell"]
    assert r["speed_mm_s"] == pytest.approx(46.0, abs=2.5)       # 48 mm/s less the start ramp
    assert abs(r["slip_fraction"]) < 0.03
    assert r["max_tilt_deg"] < 1.5 and abs(r["yaw_change_deg"]) < 3.0
    assert r["torque"]["peak_nm"] <= s.stall + 1e-9
    assert r["feet"]["one_fraction"] > 0.95
    pinned = next(x for x in report["builds"][build]["forward"]["runs"] if x["rpm"] == 60)
    assert pinned["speed_mm_s"] == pytest.approx(46.7, abs=1.0)


@pytest.mark.parametrize("build", BUILDS)
def test_differential_speed_does_not_turn_it(build):
    s = sim.WalkerSim(build)
    r = sim.run(s, sim.constant(60.0, 0.0), 8.0)
    assert not r["fell"]
    assert abs(r["yaw_change_deg"]) < 8.0
    assert abs(r["distance_forward_m"]) < 0.06


@pytest.mark.parametrize("build", BUILDS)
def test_in_phase_legs_make_no_progress(build):
    s = sim.WalkerSim(build)
    s.reset(phase_error_deg=180.0)
    r = sim.run(s, sim.constant(60.0), 6.0)
    assert not r["fell"] and abs(r["distance_forward_m"]) < 0.03
    assert r["feet"]["both_fraction"] > 0.8


def test_motor_torque_follows_the_stall_to_no_load_line():
    s = sim.WalkerSim("ev3-pixy2")
    assert s.torque_limits(0.0) == (-0.4, 0.4)
    lo, hi = s.torque_limits(s.w0 / 2)
    assert hi == pytest.approx(0.2) and lo == -0.4
    assert s.torque_limits(s.w0)[1] == pytest.approx(0.0)


def test_pinned_limits(report):
    for build in BUILDS:
        r = report["builds"][build]
        assert r["forward"]["fastest_steady_rpm"] == 90
        assert not any(x["fell"] for x in r["forward"]["runs"] if x["rpm"] <= 90)
        assert r["steps"]["highest_climbed_mm"] <= 2
        assert 4 <= r["slopes"]["uphill"]["steepest_walked_deg"] <= 8
        assert min(r["slopes"]["left_side_high"]["steepest_walked_deg"], r["slopes"]["right_side_high"]["steepest_walked_deg"]) <= 4
        assert all(abs(x["yaw_change_deg"]) < 10 for x in r["turning"])
        assert r["phase_errors"]["tolerated_deg"] == 45
        speeds = [x["speed_mm_s"] for x in r["phase_errors"]["runs"]]
        assert speeds == sorted(speeds, reverse=True) and abs(speeds[-1]) < 3
        slow = [x for x in r["friction"] if x["friction"] >= 0.1]
        assert all(abs(x["slip_fraction"]) < 0.02 for x in slow)
        assert r["stand"]["fell"] is False


def test_recordings_are_small(report):
    for build in BUILDS:
        for path in report["builds"][build]["recordings"].values():
            size = (ROOT / "docs" / path).stat().st_size
            assert 10_000 < size < 1_000_000, path
