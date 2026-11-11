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


@pytest.fixture(scope="session")
def recipe_data():
    """Everything the configurator evaluates, as the site build bundles it."""
    from microduck import recipe
    return recipe.bundle(ROOT)


@pytest.fixture(scope="session")
def all_selections(recipe_data):
    from microduck import recipe
    return list(recipe.combinations(recipe_data["compat"]))


@pytest.fixture(scope="session")
def all_recipes(recipe_data, all_selections):
    """The recipe of every distinct selection, evaluated once for the whole run."""
    from microduck import recipe
    return [recipe.evaluate(recipe_data, sel) for sel in all_selections]
