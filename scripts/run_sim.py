# SPDX-License-Identifier: MIT
"""Run the simulation experiments.

Writes reports/sim.json, docs/simulation.md, trajectories/*.csv and, when
offscreen rendering works, docs/images/sim-*.gif. Needs only the committed
robot/ files; pass --no-record to skip the GIFs.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import experiments  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args()
    result = experiments.run(record=not args.no_record)
    for line in result["verdict"].values():
        print(line)
    print("offscreen rendering:", result.get("offscreen_rendering", "not attempted"))
