# SPDX-License-Identifier: MIT
"""Run the motion study: walk, turn, jump, sit, stand up, stop and power off.

On the robot as generated (comb soles) and, for comparison, with flat soles.
Writes reports/motion.json, docs/motion.md, the trajectories for the robot as
built with trajectories/manifest.json (in the shape the control page reads)
and trajectories/gait_params.json and, when offscreen rendering works,
docs/images/motion-*.gif. The searched motions are in config/gaits.json (run
scripts/optimise_motion.py to search again). Takes about ten minutes on one
core; pass --no-record to skip the GIFs.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck import motion_experiments  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args()
    result = motion_experiments.run(record=not args.no_record)
    for preset, r in result["presets"].items():
        walk, jump, sit = r["walk"], r["jump"]["result"], r["sit"]
        print(f"{preset}: steps {walk['truly_steps']}, {walk['nominal'].get('speed_mm_s')} mm/s, "
              f"peak torque {walk['nominal'].get('peak_torque_fraction')} of the limit, "
              f"envelope forward {walk['envelope']['forward_range']} turn {walk['envelope']['turn_range']}, "
              f"jump is a {jump['verdict']}, sits {sit['sat_down']}, power-off rest holds {sit['relaxed_rest_holds']}, stands up {sit['stood_up']}")
    print("offscreen rendering:", result.get("offscreen_rendering", "not attempted"))
