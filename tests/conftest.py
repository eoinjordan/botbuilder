# SPDX-License-Identifier: MIT
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from microduck import model  # noqa: E402

needs_stls = pytest.mark.skipif(
    not model.have_stls(),
    reason="printable STLs not present (scripts/fetch_stls.py copies them from the design directory)")


@pytest.fixture(scope="session")
def assembly_report():
    with open(ROOT / "reports" / "assembly.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def selected(assembly_report):
    return assembly_report["variants"][assembly_report["selected"]]


@pytest.fixture(scope="session")
def sim_report():
    with open(ROOT / "reports" / "sim.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def joints():
    with open(ROOT / "robot" / "joints.json", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def robot_with_meshes():
    return model.build_robot()
