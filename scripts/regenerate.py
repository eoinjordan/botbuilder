# SPDX-License-Identifier: MIT
"""Regenerate everything that is generated, in order.

    python scripts/regenerate.py [--design-dir PATH] [--no-record]

1. fetch_stls.py            copy the printable STLs into build/stl
2. run_assembly.py          reports/assembly.json, docs/assembly.md, pictures
3. generate_description.py  robot/*, the firmware table
4. run_sim.py               reports/sim.json, docs/simulation.md, trajectories, recordings
5. build_site.py            site/data and site/images
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--design-dir", type=Path)
    parser.add_argument("--no-record", action="store_true", help="skip the GIF recordings")
    args = parser.parse_args()
    steps = [
        ["fetch_stls.py"] + (["--design-dir", str(args.design_dir)] if args.design_dir else []),
        ["run_assembly.py"],
        ["generate_description.py"],
        ["run_sim.py"] + (["--no-record"] if args.no_record else []),
        ["build_site.py"],
    ]
    for step in steps:
        print(f"== {' '.join(step)}", flush=True)
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / step[0])] + step[1:])
        if done.returncode:
            return done.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
