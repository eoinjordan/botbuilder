# SPDX-License-Identifier: MIT
"""The firmware's control core against the Python reference.

DuckControl.hpp is plain C++, so it is compiled for the host and fed the same
script as protocol.Controller. The sketch glue (sketch.ino, DuckServos.cpp)
needs the arduino:zephyr core and is not built here.
"""
import json
import random
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from microduck import firmware_table, protocol

SKETCH = ROOT / "app_lab" / "microduck_agent" / "sketch"
STAND = protocol.load_calibration().stand_deg


def test_table_header_is_up_to_date():
    assert firmware_table.TARGET.read_text(encoding="utf-8") == firmware_table.render(protocol.load_calibration())


def test_pulse_constants_match_the_calibration():
    header = (SKETCH / "BraccioPulse.hpp").read_text(encoding="utf-8")
    cal = protocol.load_calibration()
    assert int(re.search(r"MIN_US = (\d+)", header).group(1)) == cal.min_us
    assert int(re.search(r"MAX_US = (\d+)", header).group(1)) == cal.max_us
    assert int(re.search(r"FREQUENCY_HZ = (\d+)", header).group(1)) == cal.frequency_hz


def test_sketch_uses_the_sketchbot_build_profile():
    profile = (SKETCH / "sketch.yaml").read_text(encoding="utf-8")
    assert "fqbn: arduino:zephyr:unoq" in profile
    assert "RoboServo (1.2.0)" in profile
    sketch = (SKETCH / "sketch.ino").read_text(encoding="utf-8")
    assert 'provide_safe("duck_line"' in sketch
    assert "NOT BUILT" in sketch


def test_table_carries_the_leg_clearance_boxes():
    header = firmware_table.TARGET.read_text(encoding="utf-8")
    cal = protocol.load_calibration()
    for side in ("left", "right"):
        leg = cal.clearance["legs"][side]
        assert f"{len(leg['shin'])},  // shin boxes" in header
        assert len(leg["shin"]) <= 8 and len(leg["thigh"]) <= 8      # MAX_BOXES in DuckControl.hpp
    assert "constexpr int MAX_BOXES = 8;" in (SKETCH / "DuckControl.hpp").read_text(encoding="utf-8")


def test_sketch_starts_relaxed():
    """No pulse may leave the board before an E line: setup must not enable."""
    sketch = (SKETCH / "sketch.ino").read_text(encoding="utf-8")
    setup = sketch[sketch.index("void setup()"):sketch.index("void loop()")]
    assert "duckServosEnable" not in setup
    assert "duckServosBegin" in setup


def _script(seed: int, lines: int) -> list:
    rng = random.Random(seed)
    now = 0
    out = []
    commands = ["S", "E", "R", "H", "H", "H 1", "X", "Z", "W 300 hold", "W 250 relax", "W 50 hold", "C 2", "C 5", "C 9", "N 1.0", "N -1.5",
                "N 3", "Q", "", "J 1 2 3", "J a b c d e f", "J 1e2 0 0 0 0 0", "E 1", "N", "J 0 0 0 0 0 0 0"]
    for _ in range(lines):
        roll = rng.random()
        if roll < 0.55:
            now += 20
            out.append(f"T {now}")
        elif roll < 0.85:
            if rng.random() < 0.5:
                q = [rng.uniform(-120, 120) for _ in range(6)]
            else:
                # near the stand pose, where the leg clearance rule decides
                q = [s + rng.uniform(-22, 22) for s in STAND]
            out.append(f"L {now} " + protocol.format_joints(q).strip())
        elif roll < 0.9:
            now += rng.choice([100, 400, 700])
            out.append(f"T {now}")
        else:
            out.append(f"L {now} {rng.choice(commands)}")
    return out


def _reference(script: list) -> list:
    controller = protocol.Controller(protocol.load_calibration())
    out = []
    for row in script:
        kind, _, rest = row.partition(" ")
        now, _, line = rest.partition(" ")
        if kind == "L":
            out.append("R " + controller.handle(line, int(now)))
        else:
            controller.tick(int(now))
            out.append("P " + " ".join(str(p) for p in controller.pulses_us()))
    return out


@pytest.fixture(scope="module")
def host_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("no host C++ compiler")
    binary = tmp_path_factory.mktemp("fw") / "firmware_host"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-ffp-contract=off", "-I", str(SKETCH),
                    str(ROOT / "tests" / "firmware_host.cpp"), "-o", str(binary)], check=True)
    return next(p for p in (binary, binary.with_suffix(".exe")) if p.exists())


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_firmware_core_matches_the_reference(host_binary, seed):
    script = _script(seed, 3000)
    done = subprocess.run([str(host_binary)], input="\n".join(script) + "\n", capture_output=True, text=True, check=True)
    got = done.stdout.splitlines()
    want = _reference(script)
    assert len(got) == len(want)
    for i, (a, b) in enumerate(zip(got, want)):
        assert a == b, f"line {i} ({script[i]!r}): firmware {a!r}, reference {b!r}"
    assert any(line.startswith("R OK CLAMP") for line in want), "the script must exercise the soft limits"
    refused = sum(1 for line in want if line == "R ERR CLEAR")
    taken = sum(1 for row, line in zip(script, want) if row.split()[2:3] == ["J"] and line.startswith("R OK"))
    assert refused > 10 and taken > 10, "the script must exercise the leg clearance rule both ways"
    assert any("mode=HOLD" in line for line in want) or any(line == "P 0 0 0 0 0 0" for line in want)


def test_three_copies_of_the_leg_clearance_rule_agree(host_binary, tmp_path):
    """Python, the host-compiled C++ and the page's JavaScript on the same
    dense sample: 6000 J targets through each controller with a tick after
    every line (replies, including the refused ones, and where each
    controller ends up), and 20000 poses and 2000 angles straight through the
    page's legsClear and sine against the reference."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    from microduck import motions
    cal = protocol.load_calibration()
    rng = random.Random(11)
    lo = [j.min_deg for j in cal.joints]
    hi = [j.max_deg for j in cal.joints]

    def pose(near):
        if near:
            return [round(s + rng.uniform(-22, 22), 1) for s in cal.stand_deg]
        return [round(rng.uniform(a - 5, b + 5), 1) for a, b in zip(lo, hi)]

    lines = [(0, "E")]
    for i in range(6000):
        lines.append((20 * (i + 1), protocol.format_joints(pose(i % 2 == 0)).strip()))
        if i % 500 == 499:
            lines.append((20 * (i + 1) + 5, "H"))
    # reference
    controller = protocol.Controller(cal)
    now, want = 0, []
    for t, line in lines:
        while now + protocol.TICK_MS <= t:
            now += protocol.TICK_MS
            controller.tick(now)
        want.append(controller.handle(line, t))
    refused = want.count("ERR CLEAR")
    accepted = sum(1 for r in want if r.startswith("OK")) - 1
    assert refused > 1000 and accepted > 1000, (refused, accepted)
    # firmware core
    script, now = [], 0
    for t, line in lines:
        while now + protocol.TICK_MS <= t:
            now += protocol.TICK_MS
            script.append(f"T {now}")
        script.append(f"L {t} {line}")
    script.append("L 999999 S")
    done = subprocess.run([str(host_binary)], input="\n".join(script) + "\n", capture_output=True, text=True, check=True)
    got = [row[2:] for row in done.stdout.splitlines() if row.startswith("R ")]
    assert got[:-1] == want
    assert got[-1].split("q=")[1] == controller.handle("S", 999999).split("q=")[1]
    # the page
    poses = [pose(i % 2 == 0) for i in range(20000)]
    angles = [round(rng.uniform(-400, 400), 3) for _ in range(2000)]
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"robot": motions.load_manifest()["robot"], "script": [[t, line] for t, line in lines],
                                   "clear": {"table": cal.clearance, "poses": poses, "angles": angles}}), encoding="utf-8")
    out = json.loads(subprocess.run([node, str(ROOT / "tests" / "js" / "dump_control.mjs"), str(request)], capture_output=True, text=True,
                                    encoding="utf-8", check=True).stdout)
    assert out["script"]["replies"] == want
    assert out["script"]["current"] == controller.current, "bit for bit"
    assert out["clear"] == [protocol.legs_clear(cal.clearance, q) for q in poses]
    assert out["sine"] == [protocol.sine(a) for a in angles], "bit for bit"
    assert 2000 < sum(1 for ok in out["clear"] if not ok) < 18000
