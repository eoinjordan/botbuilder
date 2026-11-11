# SPDX-License-Identifier: MIT
"""The firmware's control core against the Python reference.

DuckControl.hpp is plain C++, so it is compiled for the host and fed the same
script as protocol.Controller. The sketch glue (sketch.ino, DuckServos.cpp)
needs the arduino:zephyr core and is not built here.
"""
import random
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from microduck import firmware_table, protocol

SKETCH = ROOT / "app_lab" / "microduck_agent" / "sketch"


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
    commands = ["S", "E", "R", "X", "Z", "W 300 hold", "W 250 relax", "W 50 hold", "C 2", "C 5", "C 9", "N 1.0", "N -1.5",
                "N 3", "Q", "", "J 1 2 3", "J a b c d e f", "J 1e2 0 0 0 0 0", "E 1", "N", "J 0 0 0 0 0 0 0"]
    for _ in range(lines):
        roll = rng.random()
        if roll < 0.55:
            now += 20
            out.append(f"T {now}")
        elif roll < 0.85:
            q = [rng.uniform(-120, 120) for _ in range(6)]
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
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(SKETCH),
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
    assert any("mode=HOLD" in line for line in want) or any(line == "P 0 0 0 0 0 0" for line in want)
