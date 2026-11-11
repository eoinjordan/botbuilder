# SPDX-License-Identifier: MIT
"""Run the motion study: walk, turn, jump, sit and stand up on both presets.

Writes reports/motion.json, docs/motion.md, trajectories/<preset>_*.csv with
trajectories/manifest.json and trajectories/gait_params.json and, when
offscreen rendering works, docs/images/motion-*.gif. Needs only the committed
robot/ and config/ files (the searched motions are in config/gaits.json; run
scripts/optimise_motion.py to search again). Takes about six minutes on one
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
              f"jump is a {jump['verdict']} ({jump['feet_rise_mm']} mm, {jump['flight_s']} s), "
              f"sits {sit['sat_down']}, rest stable {sit['relaxed_rest_stable']}, stands up {sit['stood_up']}")
    print("offscreen rendering:", result.get("offscreen_rendering", "not attempted"))
