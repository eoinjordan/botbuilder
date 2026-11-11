# SPDX-License-Identifier: MIT
"""The Microduck-look build: fetch its parts, run its assembly test, write its
description, simulate it and write its page.

    python scripts/run_look.py --fetch [--design-dir DIR]   copy the STLs and parameters.json, list them in the manifest
    python scripts/run_look.py                               assembly test, pictures, URDF and MJCF, docs page
    python scripts/run_look.py --sim                         the above, then stand and the walking attempt

The parts are adapted from the Microduck by Pollen Robotics and carry
CC BY-NC-SA 4.0 (stl/microduck-look/LICENSE). This script is MIT.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microduck.look import describe, install, model, page, report, sim  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = os.environ.get("MICRODUCK_LOOK_DESIGN_DIR", model.ROOT.parent / "3d-print-designs" / "microduck-look")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--design-dir", type=Path, default=Path(default))
    parser.add_argument("--sim", action="store_true")
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--popsize", type=int, default=12)
    parser.add_argument("--budget-s", type=float, default=420.0)
    args = parser.parse_args()
    if args.fetch:
        return install.fetch(args.design_dir)
    if not model.have_parts():
        sys.exit("parts not found in stl/microduck-look: run scripts/run_look.py --fetch first")
    report.run()
    describe.generate()
    if args.sim:
        sim.study(1, args.generations, args.popsize, args.budget_s)
    install.summary()
    page.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
